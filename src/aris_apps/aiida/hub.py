from __future__ import annotations

from pathlib import Path

from loguru import logger

from src.aris_apps.aiida.client import (
    WorkerRPCError,
    WorkerOfflineError,
    worker_call_sync,
)
from src.aris_core.logging import log_event


class AiiDAHub:
    """Worker-backed profile hub with bridge-sourced profile state only."""

    def __init__(self) -> None:
        self._profiles: list[dict] = []
        self._current_profile: str | None = None
        self._profiles_supported = True

    def start(self) -> None:
        if not self._profiles_supported:
            return
        logger.info(log_event("aiida.hub.start.begin", current_profile=self.current_profile))
        try:
            payload = worker_call_sync("profile.list", timeout=6.0)
            self._apply_profiles_payload(payload)
            logger.success(log_event("aiida.hub.start.done", profiles=len(self._profiles)))
        except WorkerOfflineError:
            logger.warning(log_event("aiida.hub.start.offline"))
        except WorkerRPCError as exc:
            if int(exc.status_code or 0) == 404:
                self._profiles_supported = False
                self._profiles = []
                self._current_profile = None
                logger.info(log_event("aiida.hub.start.unsupported", reason="worker-profiles-endpoint-missing"))
                return
            logger.warning(log_event("aiida.hub.start.failed", error=str(exc)))
        except Exception as exc:  # noqa: BLE001
            logger.exception(log_event("aiida.hub.start.failed", error=str(exc)))

    @property
    def current_profile(self) -> str | None:
        return self._current_profile

    def _apply_profiles_payload(self, payload: object) -> None:
        if not isinstance(payload, dict):
            self._profiles = []
            self._current_profile = None
            return

        remote_profiles = payload.get("profiles")
        if isinstance(remote_profiles, list):
            self._profiles = [entry for entry in remote_profiles if isinstance(entry, dict)]
        else:
            self._profiles = []

        current_profile = payload.get("current_profile")
        if isinstance(current_profile, str) and current_profile.strip():
            self._current_profile = current_profile.strip()
            return

        self._current_profile = None
        for entry in self._profiles:
            if not isinstance(entry, dict):
                continue
            if not bool(entry.get("is_active")):
                continue
            name = str(entry.get("name") or "").strip()
            if name:
                self._current_profile = name
                break

    def switch_profile(self, name: str) -> None:
        cleaned = str(name or "").strip()
        if not cleaned:
            logger.warning(log_event("aiida.profile.switch.missing", profile=name))
            return

        if cleaned == self.current_profile:
            logger.info(log_event("aiida.profile.switch.skip", profile=cleaned))
            return

        logger.info(
            log_event(
                "aiida.profile.switch.begin",
                old_profile=self.current_profile,
                new_profile=cleaned,
                profile_type="remote",
            )
        )

        try:
            payload = worker_call_sync(
                "POST",
                "/management/profiles/switch",
                json={"profile": cleaned},
                timeout=8.0,
            )
        except (WorkerOfflineError, WorkerRPCError) as exc:
            logger.warning(log_event("aiida.profile.switch.failed", profile=cleaned, error=str(exc)))
            return
        except Exception as exc:  # noqa: BLE001
            logger.exception(log_event("aiida.profile.switch.failed", profile=cleaned, error=str(exc)))
            return

        if isinstance(payload, dict):
            current = payload.get("current_profile")
            if isinstance(current, str) and current.strip():
                self._current_profile = current.strip()
            else:
                self._current_profile = cleaned
        else:
            self._current_profile = cleaned

        self.start()
        logger.success(log_event("aiida.profile.switch.done", profile=self._current_profile))

    def import_archive(self, path: Path) -> str:
        archive_path = Path(path).expanduser().resolve()

        try:
            payload = worker_call_sync(
                "POST",
                "/management/profiles/load-archive",
                json={"path": str(archive_path)},
                timeout=15.0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception(log_event("aiida.profile.import.failed", path=str(archive_path), error=str(exc)))
            return archive_path.stem

        profile_name = None
        if isinstance(payload, dict):
            maybe_current = payload.get("current_profile")
            if isinstance(maybe_current, str) and maybe_current.strip():
                profile_name = maybe_current.strip()

        self.start()
        if profile_name:
            self._current_profile = profile_name
        elif not self._current_profile:
            self._current_profile = archive_path.stem

        logger.success(log_event("aiida.profile.import.done", profile=self._current_profile, path=str(archive_path)))
        return self._current_profile or archive_path.stem

    def get_display_list(self) -> list[list[object]]:
        display: list[list[object]] = []
        active_name = self.current_profile
        for entry in self._profiles:
            name = str(entry.get("name") or "").strip()
            if not name:
                continue
            label = str(entry.get("label") or name)
            is_active = bool(entry.get("is_active")) or (active_name == name)
            display.append([name, label, is_active])
        return display


hub = AiiDAHub()
