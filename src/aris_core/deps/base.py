from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, List, Optional

from loguru import logger

from src.aris_core.logging import log_event
from src.aris_core.memory import JSONMemory


@dataclass
class BaseARISDeps:
    """Generic dependencies that every science agent needs."""

    memory: Optional[JSONMemory] = None
    current_step: int = 0
    max_steps: int = 10
    step_history: List[str] = field(default_factory=list)
    step_callback: Optional[Callable[[str], None]] = None

    def log_step(self, message: str) -> None:
        self.step_history.append(message)
        logger.info(log_event("agent.step", step=message))
        callback = self.step_callback
        if callable(callback):
            try:
                callback(message)
            except Exception:  # noqa: BLE001
                logger.warning(log_event("agent.step.callback_failed", step=message))
__all__ = ["BaseARISDeps"]
