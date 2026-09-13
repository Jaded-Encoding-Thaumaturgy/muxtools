import logging
import re
import sys
import time
from typing import Any

__all__ = [
    "crit",
    "debug",
    "error",
    "exit",
    "info",
    "warn",
    "logger",
    "danger",
    "LoggingException",
    "setup_logging",
    "log_escape",
]

logging.addLevelName(35, "DANGER")
logging.addLevelName(logging.WARNING, "WARN")

logger = logging.getLogger("muxtools")
logger.addHandler(logging.NullHandler())


class LoggingException(Exception):
    """Custom exception returned from log.crit and log.error"""


def log_escape(text: str) -> str:
    from rich.markup import escape

    return escape(text)


def setup_logging(force: bool = False) -> None:
    if not force and _has_active_handlers(logger):
        return

    from rich.console import Console
    from rich.logging import RichHandler
    from rich.theme import Theme

    format_str = "%(name)s | %(message)s"
    console = Console(theme=Theme({"logging.level.warn": "gold3", "logging.level.danger": "red"}))
    handler = RichHandler(markup=True, omit_repeated_times=False, show_path=False, console=console)
    handler.setFormatter(logging.Formatter(format_str, datefmt="[%X]"))

    logger.handlers = [h for h in logger.handlers if not isinstance(h, (logging.NullHandler, handler.__class__))]
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False


def _has_active_handlers(log: logging.Logger) -> bool:
    curr: logging.Logger | None = log
    while curr:
        if any(not isinstance(h, logging.NullHandler) for h in curr.handlers):
            return True
        if not curr.propagate:
            break
        curr = curr.parent
    return False


def _is_rich_active() -> bool:
    if "rich.logging" not in sys.modules:
        return False

    from rich.logging import RichHandler

    curr: logging.Logger | None = logger
    while curr:
        if any(isinstance(h, RichHandler) and getattr(h, "markup", False) for h in curr.handlers):
            return True
        if not curr.propagate:
            break
        curr = curr.parent
    return False


def _ensure_logging() -> None:
    if not _has_active_handlers(logger):
        setup_logging()


def _strip_markup(msg: str) -> str:
    try:
        from rich.text import Text

        return Text.from_markup(msg).plain
    except Exception:
        return re.sub(r"\[/?(?:[a-zA-Z#/@][^]]*?)\]", "", msg)


def _format_msg(msg: str, caller: Any) -> str:
    _ensure_logging()

    if caller is not None and not isinstance(caller, str):
        if isinstance(caller, type):
            caller = caller.__qualname__
        elif hasattr(caller, "__class__") and caller.__class__.__name__ not in ("function", "method"):
            caller = caller.__class__.__qualname__
        elif hasattr(caller, "__qualname__"):
            caller = caller.__qualname__
        elif hasattr(caller, "__name__"):
            caller = caller.__name__
        else:
            caller = str(caller)

    if _is_rich_active():
        return msg if caller is None else f"[bold]{caller}:[/] {msg}"

    plain_msg = _strip_markup(msg)
    return plain_msg if caller is None else f"{caller}: {plain_msg}"


def crit(msg: str, caller: Any = None) -> LoggingException:
    message = _format_msg(msg, caller)
    logger.critical(message)
    return LoggingException(message)


def debug(msg: str, caller: Any = None):
    from .env import is_debug

    if not is_debug():
        return
    message = _format_msg(msg, caller)
    logger.debug(message)


def info(msg: str, caller: Any = None):
    message = _format_msg(msg, caller)
    logger.info(message)


def warn(msg: str, caller: Any = None, sleep: int = 0):
    message = _format_msg(msg, caller)
    logger.warning(message)
    if sleep:
        time.sleep(sleep)


def danger(msg: str, caller: Any = None, sleep: int = 0):
    message = _format_msg(msg, caller)
    logger.log(35, message)

    from .env import get_setup_attr

    if get_setup_attr("error_on_danger", False):
        raise LoggingException(message)

    if sleep:
        time.sleep(sleep)


def error(msg: str, caller: Any = None) -> LoggingException:
    message = _format_msg(msg, caller)
    logger.error(message)
    return LoggingException(message)


def exit(msg: str, caller: Any = None):
    message = _format_msg(msg, caller)
    logger.info(message)

    sys.exit(0)
