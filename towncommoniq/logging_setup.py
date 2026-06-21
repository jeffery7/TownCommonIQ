"""Logging configuration for the towncommoniq CLI and pipeline modules.

Call configure_logging() once, from cli.py:main(), before any pipeline code
runs.  Other modules just do `logging.getLogger(__name__)` and log normally —
as descendants of the 'towncommoniq' logger they inherit its handlers.
"""
import logging
import re
from logging import handlers as logging_handlers

import boto3

from towncommoniq import data_store

_ANSI_ESCAPE_RE = re.compile(r'\x1b\[[0-9;]*m')

LOG_BACKUP_COUNT = 10
FILE_LOG_LEVEL = logging.DEBUG
CONSOLE_LOG_LEVEL = logging.WARNING
LOG_DIRECTORY = data_store.DATA_DIR / 'logs'
LOG_FILE = LOG_DIRECTORY / 'towncommoniq.log'
_HANDLER_TYPE_LOG = 'log'
_HANDLER_TYPE_CONSOLE = 'console'
_LOGGER_NAME = 'towncommoniq'


def configure_logging() -> None:
    """Attach a rotating file handler and a console handler to the towncommoniq logger.

    Safe to call more than once — later calls are no-ops so handlers are never
    attached twice.  Logs are written under data/<town>/logs/, alongside that
    town's other cached data (TOWNCOMMONIQ_TOWN selects which).
    """
    logger = logging.getLogger(_LOGGER_NAME)
    if logger.handlers:
        return
    logger.setLevel(FILE_LOG_LEVEL)
    logger.propagate = False

    console_handler = logging.StreamHandler()
    console_handler.setLevel(CONSOLE_LOG_LEVEL)
    console_handler.setFormatter(_build_formatter(_HANDLER_TYPE_CONSOLE))
    logger.addHandler(console_handler)

    LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)
    file_handler = logging_handlers.TimedRotatingFileHandler(
        str(LOG_FILE), when='midnight', backupCount=LOG_BACKUP_COUNT,
    )
    file_handler.setFormatter(_build_formatter(_HANDLER_TYPE_LOG))
    logger.addHandler(file_handler)

    boto3.set_stream_logger(name='botocore.credentials', level=logging.ERROR)


def strip_ansi(text: str) -> str:
    """Remove ANSI color escape codes so log files stay readable as plain text."""
    return _ANSI_ESCAPE_RE.sub('', text)


def _build_formatter(handler_type: str = _HANDLER_TYPE_LOG) -> logging.Formatter:
    """Return the log line formatter for the given handler type."""
    if handler_type == _HANDLER_TYPE_LOG:
        fmt_string = '{asctime} [{filename:<20}][{funcName:<20}][{levelname:8}] {message}'
    elif handler_type == _HANDLER_TYPE_CONSOLE:
        fmt_string = '{asctime} [{filename}] {funcName} [{levelname}] {message}'
    else:
        fmt_string = '{message}'
    return logging.Formatter(fmt=fmt_string, style='{')
