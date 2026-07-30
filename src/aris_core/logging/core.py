from __future__ import annotations

import logging
import os
import sys
from collections import deque
from datetime import datetime
from threading import Lock
from typing import Any

from loguru import logger
from rich.logging import RichHandler
from rich.markup import escape as rich_escape
from rich.panel import Panel
from rich.syntax import Syntax


_MODULE = sys.modules[__name__]
for _alias in (
    "aris_core.logging.core",
    "src.aris_core.logging.core",
):
    sys.modules.setdefault(_alias, _MODULE)


_LEVEL_MAP: dict[str, int] = {
    "TRACE": logging.DEBUG,
    "DEBUG": logging.DEBUG,
    "INFO": logging.INFO,
    "SUCCESS": logging.INFO,
    "WARNING": logging.WARNING,
    "ERROR": logging.ERROR,
    "CRITICAL": logging.CRITICAL,
}
_VALID_LEVELS = set(_LEVEL_MAP.keys())
_SOURCE_WIDTH = 38
_FUNC_MAX_LEN = 30
_TRACEBACK_MARKER = "Traceback (most recent call last):"
_DEFAULT_EVENT_STYLE = "yellow"


class _RingLogBuffer:
    def __init__(self, maxlen: int = 600) -> None:
        self._lines: deque[str] = deque(maxlen=maxlen)
        self._version = 0
        self._lock = Lock()

    def append(self, line: str) -> None:
        with self._lock:
            self._lines.append(line)
            self._version += 1

    def snapshot(self, limit: int = 120) -> tuple[int, list[str]]:
        with self._lock:
            lines = list(self._lines)
            if limit > 0:
                lines = lines[-limit:]
            return self._version, lines


def _get_env_value(*env_names: str) -> str | None:
    for env_name in env_names:
        value = os.getenv(env_name)
        if value is None:
            continue
        cleaned = str(value).strip()
        if cleaned:
            return cleaned
    return None


def _get_env_int(*env_names: str, default: int) -> int:
    raw_value = _get_env_value(*env_names)
    if raw_value is None:
        return default
    try:
        return int(raw_value)
    except ValueError:
        return default


_LOG_BUFFER = _RingLogBuffer(
    maxlen=max(100, _get_env_int("ARIS_LOG_BUFFER_SIZE", default=600))
)


def _normalize_level(value: str | None, fallback: str = "INFO") -> str:
    candidate = (value or "").strip().upper()
    if candidate in _VALID_LEVELS:
        return candidate
    return fallback


def _logging_level(level_name: str) -> int:
    return _LEVEL_MAP.get(level_name.upper(), logging.INFO)


def _short_module(module_name: Any) -> str:
    module = str(module_name or "-")
    return module.split(".")[-1] or "-"


def _short_function(function_name: Any) -> str:
    function = str(function_name or "-")
    if len(function) <= _FUNC_MAX_LEN:
        return function
    return function[: (_FUNC_MAX_LEN - 3)] + "..."


def _compact_source(module_name: Any, function_name: Any, line: Any) -> str:
    module = _short_module(module_name)
    function = _short_function(function_name)
    return f"{module}.{function}:{line}"


def _patch_record(record: dict[str, Any]) -> None:
    extra = record["extra"]
    source_module = extra.get("py_name") or record.get("name")
    source_function = extra.get("py_func") or record.get("function")
    source_line = extra.get("py_line") or record.get("line")
    extra["src"] = _compact_source(source_module, source_function, source_line)


def _render_plain_line(record: dict[str, Any]) -> str:
    ts = record["time"].strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
    level = str(record["level"].name).upper().ljust(8)
    src = str(record["extra"].get("src", "-")).ljust(_SOURCE_WIDTH)
    message = str(record.get("message", ""))
    return f"{ts} | {level} | {src} | {message}"


def _ring_buffer_sink(message: Any) -> None:
    _LOG_BUFFER.append(_render_plain_line(message.record))


def _split_event_segments(message: str) -> list[str]:
    if " | " not in message:
        return [message]

    segments: list[str] = []
    current: list[str] = []
    in_single_quote = False
    index = 0
    while index < len(message):
        chunk = message[index : index + 3]
        char = message[index]
        if char == "'" and (index == 0 or message[index - 1] != "\\"):
            in_single_quote = not in_single_quote
            current.append(char)
            index += 1
            continue
        if not in_single_quote and chunk == " | ":
            segments.append("".join(current).strip())
            current = []
            index += 3
            continue
        current.append(char)
        index += 1
    segments.append("".join(current).strip())
    return [segment for segment in segments if segment]


def _deserialize_field(raw_value: str) -> str:
    value = raw_value.strip()
    if len(value) >= 2 and value[0] == "'" and value[-1] == "'":
        inner = value[1:-1]
        return inner.replace("\\'", "'").replace("\\n", "\n")
    return value.replace("\\n", "\n")


def _parse_event_message(message: str) -> tuple[str | None, list[tuple[str, str]], list[str]]:
    segments = _split_event_segments(message)
    event: str | None = None
    fields: list[tuple[str, str]] = []
    loose_segments: list[str] = []

    for segment in segments:
        if "=" not in segment:
            loose_segments.append(segment)
            continue
        key, value = segment.split("=", 1)
        normalized_key = key.strip()
        fields.append((normalized_key, value.strip()))
        if normalized_key == "evt" and event is None:
            event = _deserialize_field(value)

    return event, fields, loose_segments


def _looks_like_traceback(text: str) -> bool:
    normalized = text.replace("\\n", "\n")
    if _TRACEBACK_MARKER in normalized:
        return True
    return "  File \"" in normalized and "Error" in normalized


def _event_style(event: str | None) -> str:
    if not event:
        return _DEFAULT_EVENT_STYLE
    normalized = event.strip().lower()
    if normalized.startswith("error."):
        return "bold red"
    if "agent" in normalized:
        return "green"
    if "worker" in normalized:
        return "blue"
    if normalized.startswith("engine."):
        return "magenta"
    return _DEFAULT_EVENT_STYLE


def _level_style(level_name: str) -> str:
    normalized = level_name.strip().upper()
    if normalized in {"TRACE", "DEBUG"}:
        return "cyan"
    if normalized in {"WARNING"}:
        return "yellow"
    if normalized in {"ERROR", "CRITICAL"}:
        return "bold red"
    if normalized in {"SUCCESS"}:
        return "green"
    return "white"


def _render_event_markup(message: str) -> tuple[str, str | None, dict[str, str], str | None]:
    event, fields, loose_segments = _parse_event_message(message)
    decoded_fields: list[tuple[str, str]] = [
        (key, _deserialize_field(raw_value)) for key, raw_value in fields
    ]
    field_map = {key: value for key, value in decoded_fields}

    traceback_text: str | None = None
    traceback_key: str | None = None
    for key, value in decoded_fields:
        if key == "evt":
            continue
        if _looks_like_traceback(value):
            traceback_text = value
            traceback_key = key
            break

    parts: list[str] = []
    if event:
        style = _event_style(event)
        parts.append(f"[cyan]evt[/]=[{style}]{rich_escape(event)}[/]")
    elif not decoded_fields and not loose_segments:
        return "", None, field_map, None

    for key, value in decoded_fields:
        if key == "evt":
            continue
        if key == traceback_key:
            rendered_value = "[bold red]<traceback shown below>[/]"
        else:
            compact_value = value.replace("\n", " ↩ ")
            rendered_value = f"[white]{rich_escape(compact_value)}[/]"
        parts.append(f"[bright_black]{rich_escape(key)}[/]={rendered_value}")

    for segment in loose_segments:
        parts.append(f"[white]{rich_escape(segment)}[/]")

    if parts:
        return " [dim]|[/] ".join(parts), event, field_map, traceback_text

    fallback = message.replace("\n", " ↩ ")
    return f"[white]{rich_escape(fallback)}[/]", event, field_map, traceback_text


def _turn_id_from_fields(fields: dict[str, str]) -> str | None:
    for key in ("turn_id", "turn"):
        if key in fields:
            value = str(fields[key]).strip()
            if value:
                return value
    return None


class ARISRichHandler(RichHandler):
    def __init__(self) -> None:
        super().__init__(
            show_time=False,
            show_level=False,
            show_path=False,
            markup=True,
            rich_tracebacks=True,
            tracebacks_show_locals=False,
        )
        self._last_turn_id: str | None = None

    def _maybe_render_turn_rule(self, event: str | None, fields: dict[str, str]) -> None:
        if not event or not event.endswith(".chat_turn.start"):
            return
        turn_id = _turn_id_from_fields(fields)
        if turn_id and self._last_turn_id == turn_id:
            return
        self._last_turn_id = turn_id
        title = f"Chat Turn {turn_id}" if turn_id else "Chat Turn"
        self.console.rule(title, style="bright_black")

    def emit(self, record: logging.LogRecord) -> None:
        try:
            ts = datetime.fromtimestamp(record.created).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]
            level_name = str(record.levelname or "INFO").upper()
            level_text = level_name.ljust(8)
            src = _compact_source(record.name, record.funcName, record.lineno).ljust(_SOURCE_WIDTH)
            message = record.getMessage()

            event_markup, event_name, fields, traceback_text = _render_event_markup(message)
            self._maybe_render_turn_rule(event_name, fields)

            level_style = _level_style(level_name)
            header = (
                f"[green]{ts}[/] [dim]|[/] "
                f"[{level_style}]{rich_escape(level_text)}[/] [dim]|[/] "
                f"[cyan]{rich_escape(src)}[/] [dim]|[/] "
                f"{event_markup}"
            )
            record.msg = header
            record.args = ()
            super().emit(record)

            if traceback_text:
                syntax = Syntax(
                    traceback_text,
                    "python",
                    line_numbers=False,
                    word_wrap=True,
                )
                panel = Panel(
                    syntax,
                    title="[bold red]Traceback[/]",
                    border_style="red",
                )
                self.console.print(panel)
        except Exception:
            super().emit(record)

class InterceptHandler(logging.Handler):
    """Route stdlib logging records into Loguru with original call-site metadata."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            level: str | int = logger.level(record.levelname).name
        except ValueError:
            level = record.levelno

        logger.bind(
            py_name=record.name,
            py_func=record.funcName,
            py_line=record.lineno,
        ).opt(
            exception=record.exc_info,
        ).log(level, record.getMessage())


def setup_logging(default_level: str = "INFO") -> str:
    """
    Configure unified logging for Loguru + stdlib logging + Uvicorn loggers.

    Environment variables:
    - ARIS_LOG_LEVEL: global level for app logs.
    - ARIS_ACCESS_LOG_LEVEL: level for uvicorn access logs.
    - ARIS_HTTPX_LOG_LEVEL: level for httpx/httpcore logs.
    """
    global_level = _normalize_level(
        _get_env_value("ARIS_LOG_LEVEL"),
        fallback=_normalize_level(default_level),
    )
    access_level = _normalize_level(
        _get_env_value("ARIS_ACCESS_LOG_LEVEL"),
        fallback="WARNING",
    )
    httpx_level = _normalize_level(
        _get_env_value("ARIS_HTTPX_LOG_LEVEL"),
        fallback="WARNING",
    )
    alembic_level = _normalize_level(
        _get_env_value("ARIS_ALEMBIC_LOG_LEVEL"),
        fallback="WARNING",
    )
    watchfiles_level = _normalize_level(
        _get_env_value("ARIS_WATCHFILES_LOG_LEVEL"),
        fallback="WARNING",
    )

    logger.remove()
    logger.configure(patcher=_patch_record)

    rich_handler = ARISRichHandler()
    logger.add(
        rich_handler,
        level=global_level,
        format="{message}",
        colorize=False,
        backtrace=False,
        diagnose=False,
        enqueue=False,
        catch=False,
    )
    logger.add(
        _ring_buffer_sink,
        level="TRACE",
        colorize=False,
        backtrace=False,
        diagnose=False,
        enqueue=False,
        catch=False,
    )

    root_logger = logging.getLogger()
    root_logger.handlers = [InterceptHandler()]
    root_logger.setLevel(_logging_level(global_level))

    for name in (
        "uvicorn",
        "uvicorn.error",
        "uvicorn.access",
        "watchfiles",
        "watchfiles.main",
        "fastapi",
        "alembic",
        "httpx",
        "httpcore",
    ):
        logging_logger = logging.getLogger(name)
        logging_logger.handlers = [InterceptHandler()]
        logging_logger.propagate = False

    logging.getLogger("uvicorn").setLevel(_logging_level(global_level))
    logging.getLogger("uvicorn.error").setLevel(_logging_level(global_level))
    logging.getLogger("uvicorn.access").setLevel(_logging_level(access_level))
    logging.getLogger("watchfiles").setLevel(_logging_level(watchfiles_level))
    logging.getLogger("watchfiles.main").setLevel(_logging_level(watchfiles_level))
    logging.getLogger("httpx").setLevel(_logging_level(httpx_level))
    logging.getLogger("httpcore").setLevel(_logging_level(httpx_level))
    logging.getLogger("alembic").setLevel(_logging_level(alembic_level))

    return global_level


def get_log_buffer_snapshot(limit: int = 120) -> tuple[int, list[str]]:
    return _LOG_BUFFER.snapshot(limit=limit)


def _serialize_field(value: Any) -> str:
    if isinstance(value, str):
        compact = value.replace("\n", "\\n")
        if (not compact) or any(ch in compact for ch in (" ", "|", "'")):
            escaped = compact.replace("'", "\\'")
            return f"'{escaped}'"
        return compact
    if value is None:
        return "None"
    return str(value)


def log_event(event: str, **fields: Any) -> str:
    """Build a consistent `evt=... | key=value` log message."""
    parts = [f"evt={event}"]
    for key, value in fields.items():
        parts.append(f"{key}={_serialize_field(value)}")
    return " | ".join(parts)
