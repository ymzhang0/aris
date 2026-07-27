from __future__ import annotations

import asyncio
import json
import os
from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from itertools import count
from pathlib import Path
from typing import Any


class WorkerProcessError(RuntimeError):
    """Raised when the isolated worker process cannot satisfy a request."""


@dataclass(frozen=True)
class WorkerProcessSnapshot:
    status: str
    pid: int | None
    command: tuple[str, ...]
    cwd: str | None
    restart_count: int
    last_error: str | None


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

    @property
    def is_running(self) -> bool:
        return self._process is not None and self._process.returncode is None

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
        async with self._lock:
            await self._ensure_started_locked()
            return await self._exchange_locked("runtime.status", {})

    async def request(
        self,
        method: str,
        params: Mapping[str, Any] | None = None,
        *,
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
            reason = error.get("data")
            raise WorkerProcessError(f"{message}: {reason}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise WorkerProcessError("Worker result must be a JSON object")
        return result

    async def _invalidate_process_locked(self) -> None:
        process = self._process
        if process is not None and process.returncode is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), timeout=1.0)
            except asyncio.TimeoutError:
                process.kill()
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


_worker_process_manager: WorkerProcessManager | None = None


def configure_worker_process_manager(manager: WorkerProcessManager | None) -> None:
    global _worker_process_manager
    _worker_process_manager = manager


def get_worker_process_manager() -> WorkerProcessManager | None:
    return _worker_process_manager
