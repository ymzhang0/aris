from __future__ import annotations

import asyncio
import json
import os
import shutil
from collections import deque
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any


class WorkerProcessError(RuntimeError):
    """Raised when the isolated worker process cannot satisfy a request."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int = 500,
        payload: Mapping[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = int(status_code)
        self.payload = dict(payload or {"error": message})


@dataclass(frozen=True)
class WorkerProcessSnapshot:
    status: str
    pid: int | None
    command: tuple[str, ...]
    cwd: str | None
    restart_count: int
    last_error: str | None


@dataclass(frozen=True)
class WorkerRuntimeKey:
    """Identity of one isolated project AiiDA runtime."""

    project_id: str
    python_interpreter_path: str
    profile_name: str | None = None

    @classmethod
    def from_context(cls, context: Mapping[str, Any]) -> "WorkerRuntimeKey":
        project_id = str(context.get("project_id") or "").strip()
        python_path = str(context.get("python_interpreter_path") or "").strip()
        if not project_id:
            raise WorkerProcessError("Worker project_id is required", status_code=422)
        if not python_path:
            raise WorkerProcessError("Project python_interpreter_path is required", status_code=422)
        interpreter = Path(python_path).expanduser()
        if not interpreter.is_absolute():
            interpreter = Path.cwd() / interpreter
        return cls(
            project_id=project_id,
            python_interpreter_path=str(interpreter),
            profile_name=str(context.get("profile_name") or "").strip() or None,
        )


class WorkerProcessManager:
    """Own one newline-delimited JSON-RPC worker subprocess."""

    def __init__(
        self,
        command: Sequence[str],
        *,
        cwd: str | Path | None = None,
        env: Mapping[str, str] | None = None,
        request_timeout: float = 10.0,
    ) -> None:
        normalized_command = tuple(str(item).strip() for item in command if str(item).strip())
        if not normalized_command:
            raise ValueError("Worker command is required")
        self._command = normalized_command
        self._cwd = str(Path(cwd).expanduser().resolve()) if cwd is not None else None
        self._env = {str(key): str(value) for key, value in dict(env or {}).items()}
        self._request_timeout = max(0.2, float(request_timeout))
        self._process: asyncio.subprocess.Process | None = None
        self._stderr_task: asyncio.Task[None] | None = None
        self._stderr_lines: deque[str] = deque(maxlen=50)
        self._request_ids = count(1)
        self._lock = asyncio.Lock()
        self._restart_count = 0
        self._last_error: str | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def snapshot(self) -> WorkerProcessSnapshot:
        return WorkerProcessSnapshot(
            status="online" if self.is_running else "offline",
            pid=self._process.pid if self.is_running and self._process is not None else None,
            command=self._command,
            cwd=self._cwd,
            restart_count=self._restart_count,
            last_error=self._last_error,
        )

    async def start(self) -> dict[str, Any]:
        self._loop = asyncio.get_running_loop()
        async with self._lock:
            await self._ensure_started_locked()
            return await self._exchange_locked("runtime.status", {})

    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        context: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        cleaned_method = str(method or "").strip()
        if not cleaned_method:
            raise ValueError("Worker method is required")
        async with self._lock:
            await self._ensure_started_locked()
            return await self._exchange_locked(
                cleaned_method,
                dict(params or {}),
                context=dict(context or {}),
                timeout=timeout,
            )

    async def stop(self) -> None:
        async with self._lock:
            process = self._process
            if process is None:
                return
            if process.returncode is None:
                try:
                    await self._exchange_locked("runtime.shutdown", {}, timeout=3.0)
                except WorkerProcessError:
                    pass
            try:
                await asyncio.wait_for(process.wait(), timeout=3.0)
            except asyncio.TimeoutError:
                process.terminate()
                try:
                    await asyncio.wait_for(process.wait(), timeout=2.0)
                except asyncio.TimeoutError:
                    process.kill()
                    await process.wait()
            await self._finish_stderr_task()
            self._process = None

    async def _ensure_started_locked(self) -> None:
        if self.is_running:
            return
        if self._process is not None:
            await self._finish_stderr_task()
            self._restart_count += 1

        environment = os.environ.copy()
        environment.update(self._env)
        try:
            process = await asyncio.create_subprocess_exec(
                *self._command,
                cwd=self._cwd,
                env=environment,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except (FileNotFoundError, OSError) as exc:
            self._last_error = str(exc)
            raise WorkerProcessError(f"Failed to start worker process: {exc}") from exc

        self._process = process
        self._last_error = None
        self._stderr_task = asyncio.create_task(self._capture_stderr(process))

    async def _exchange_locked(
        self,
        method: str,
        params: dict[str, Any],
        *,
        context: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        process = self._process
        if process is None or process.stdin is None or process.stdout is None or process.returncode is not None:
            raise WorkerProcessError("Worker process is not running")

        request_id = next(self._request_ids)
        request = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        if context:
            request["context"] = context
        try:
            process.stdin.write((json.dumps(request, ensure_ascii=True) + "\n").encode("utf-8"))
            await process.stdin.drain()
            raw_line = await asyncio.wait_for(
                process.stdout.readline(),
                timeout=max(0.2, float(timeout or self._request_timeout)),
            )
        except (BrokenPipeError, ConnectionError, asyncio.TimeoutError) as exc:
            self._last_error = str(exc)
            reason = str(exc) or "timeout"
            await self._invalidate_process_locked()
            raise WorkerProcessError(f"Worker request failed for {method}: {reason}") from exc

        if not raw_line:
            stderr = "\n".join(self._stderr_lines)
            self._last_error = stderr or f"Worker exited with status {process.returncode}"
            await self._invalidate_process_locked()
            raise WorkerProcessError(self._last_error)

        try:
            response = json.loads(raw_line.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            self._last_error = str(exc)
            await self._invalidate_process_locked()
            raise WorkerProcessError(f"Worker returned invalid JSON: {exc}") from exc

        if not isinstance(response, dict) or response.get("id") != request_id:
            self._last_error = "Worker returned a mismatched JSON-RPC response"
            await self._invalidate_process_locked()
            raise WorkerProcessError("Worker returned a mismatched JSON-RPC response")
        error = response.get("error")
        if isinstance(error, dict):
            message = str(error.get("message") or "Worker request failed")
            error_code = error.get("code")
            data = error.get("data")
            payload = dict(data) if isinstance(data, dict) else {"reason": data}
            default_status = 422 if error_code == -32602 else 500
            status_code = payload.get("status_code", default_status)
            try:
                normalized_status = int(status_code)
            except (TypeError, ValueError):
                normalized_status = 500
            raise WorkerProcessError(
                message,
                status_code=normalized_status,
                payload={"error": message, **payload},
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise WorkerProcessError("Worker result must be a JSON object")
        return result

    async def _invalidate_process_locked(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            try:
                process.terminate()
            except ProcessLookupError:
                pass
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                try:
                    process.kill()
                except ProcessLookupError:
                    pass
                await process.wait()
        await self._finish_stderr_task()

    async def _capture_stderr(self, process: asyncio.subprocess.Process) -> None:
        if process.stderr is None:
            return
        while True:
            line = await process.stderr.readline()
            if not line:
                return
            self._stderr_lines.append(line.decode("utf-8", errors="replace").rstrip())

    async def _finish_stderr_task(self) -> None:
        task = self._stderr_task
        if task is None:
            return
        if not task.done():
            task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        self._stderr_task = None


class ProjectWorkerProcessManager:
    """Own one worker subprocess per explicit project interpreter/profile key."""

    def __init__(
        self,
        *,
        runtime_context_provider: Callable[[], Mapping[str, Any] | None],
        worker_package_source: str | Path | None = None,
        request_timeout: float = 60.0,
        auto_install_worker: bool = True,
    ) -> None:
        self._runtime_context_provider = runtime_context_provider
        self._worker_package_source = (
            Path(worker_package_source).expanduser().resolve()
            if worker_package_source is not None
            else None
        )
        self._request_timeout = max(0.2, float(request_timeout))
        self._auto_install_worker = bool(auto_install_worker)
        self._managers: dict[WorkerRuntimeKey, WorkerProcessManager] = {}
        self._manager_lock = asyncio.Lock()
        self._active_key: WorkerRuntimeKey | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    @property
    def loop(self) -> asyncio.AbstractEventLoop | None:
        return self._loop

    def _resolve_context(self, context: Mapping[str, Any] | None) -> dict[str, Any]:
        resolved = dict(context or {})
        if not resolved.get("project_id") or not resolved.get("python_interpreter_path"):
            fallback = self._runtime_context_provider()
            if fallback:
                for field_name, value in fallback.items():
                    resolved.setdefault(field_name, value)
        return resolved

    async def _worker_module_is_available(self, key: WorkerRuntimeKey) -> bool:
        process = await asyncio.create_subprocess_exec(
            key.python_interpreter_path,
            "-c",
            "import importlib.util; raise SystemExit(0 if importlib.util.find_spec('aris_aiida_worker') else 1)",
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        return await process.wait() == 0

    async def _install_worker(self, key: WorkerRuntimeKey) -> None:
        source = self._worker_package_source
        if source is None or not source.is_dir():
            raise WorkerProcessError(
                "aris-aiida-worker is not installed in the project environment",
                status_code=503,
                payload={"python_interpreter_path": key.python_interpreter_path},
            )
        uv_executable = shutil.which("uv")
        if not uv_executable:
            raise WorkerProcessError(
                "Cannot install aris-aiida-worker because uv is unavailable",
                status_code=503,
            )
        process = await asyncio.create_subprocess_exec(
            uv_executable,
            "pip",
            "install",
            "--python",
            key.python_interpreter_path,
            "--editable",
            str(source),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await process.communicate()
        if process.returncode != 0:
            reason = stderr.decode("utf-8", errors="replace").strip() or stdout.decode(
                "utf-8", errors="replace"
            ).strip()
            raise WorkerProcessError(
                "Failed to install aris-aiida-worker in the project environment",
                status_code=503,
                payload={
                    "python_interpreter_path": key.python_interpreter_path,
                    "reason": reason,
                },
            )

    async def _get_manager(self, context: Mapping[str, Any]) -> tuple[WorkerRuntimeKey, WorkerProcessManager]:
        key = WorkerRuntimeKey.from_context(context)
        async with self._manager_lock:
            manager = self._managers.get(key)
            if manager is not None:
                self._active_key = key
                return key, manager

            interpreter = Path(key.python_interpreter_path)
            if not interpreter.is_file() or not os.access(interpreter, os.X_OK):
                raise WorkerProcessError(
                    "Project Python interpreter is unavailable",
                    status_code=404,
                    payload={"python_interpreter_path": key.python_interpreter_path},
                )
            if not await self._worker_module_is_available(key):
                if not self._auto_install_worker:
                    raise WorkerProcessError(
                        "aris-aiida-worker is not installed in the project environment",
                        status_code=503,
                    )
                await self._install_worker(key)

            workspace_path = str(context.get("workspace_path") or "").strip() or None
            environment = {"AIIDA_PROFILE": key.profile_name} if key.profile_name else None
            manager = WorkerProcessManager(
                [key.python_interpreter_path, "-u", "-m", "aris_aiida_worker"],
                cwd=workspace_path,
                env=environment,
                request_timeout=self._request_timeout,
            )
            status = await manager.start()
            actual_python = str(status.get("python_interpreter_path") or "").strip()
            try:
                same_interpreter = bool(actual_python) and os.path.samefile(
                    key.python_interpreter_path,
                    actual_python,
                )
            except (FileNotFoundError, OSError):
                same_interpreter = False
            actual_profile = str(status.get("profile") or "").strip() or None
            if not same_interpreter or (
                key.profile_name is not None and actual_profile != key.profile_name
            ):
                await manager.stop()
                raise WorkerProcessError(
                    "Project worker started with the wrong runtime identity",
                    status_code=503,
                    payload={
                        "expected_python_interpreter_path": key.python_interpreter_path,
                        "actual_python_interpreter_path": actual_python,
                        "expected_profile_name": key.profile_name,
                        "actual_profile_name": actual_profile,
                    },
                )
            self._managers[key] = manager
            self._active_key = key
            return key, manager

    async def start(self, *, context: Mapping[str, Any] | None = None) -> dict[str, Any]:
        self._loop = asyncio.get_running_loop()
        resolved_context = self._resolve_context(context)
        key, manager = await self._get_manager(resolved_context)
        status = await manager.start()
        return {**status, "project_id": key.project_id}

    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
        context: Mapping[str, Any] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        self._loop = asyncio.get_running_loop()
        resolved_context = self._resolve_context(context)
        key, manager = await self._get_manager(resolved_context)
        result = await manager.request(
            method,
            params,
            context=resolved_context,
            timeout=timeout,
        )
        return result

    def snapshot(self) -> WorkerProcessSnapshot:
        if self._active_key is not None:
            manager = self._managers.get(self._active_key)
            if manager is not None:
                return manager.snapshot()
        return WorkerProcessSnapshot(
            status="offline",
            pid=None,
            command=(),
            cwd=None,
            restart_count=0,
            last_error=None,
        )

    async def stop(self) -> None:
        managers = list(self._managers.values())
        self._managers.clear()
        self._active_key = None
        for manager in managers:
            await manager.stop()


WorkerManager = WorkerProcessManager | ProjectWorkerProcessManager
_worker_process_manager: WorkerManager | None = None


def configure_worker_process_manager(manager: WorkerManager | None) -> None:
    global _worker_process_manager
    _worker_process_manager = manager


def get_worker_process_manager() -> WorkerManager | None:
    return _worker_process_manager
