"""Shared pytest fixtures for the towncommoniq test suite."""
import logging

import pytest

_TOWNCOMMONIQ_LOGGER = 'towncommoniq'


@pytest.fixture(autouse=True)
def _isolate_towncommoniq_logger():
    """Restore the towncommoniq logger's handlers after every test.

    cli.main() calls logging_setup.configure_logging() on every invocation.
    Tests that exercise cli.main() (e.g. test_cli.py's TestMain) trigger a
    real, unmocked call to it — attaching a real file handler pointed at the
    live data/<town>/logs/ directory for the rest of the pytest process.
    Without this fixture, every subsequent test in the same run that logs a
    warning (many do, deliberately, to test the logging behavior) writes
    mocked exception tracebacks into the real project's log file.
    """
    logger = logging.getLogger(_TOWNCOMMONIQ_LOGGER)
    saved_handlers = list(logger.handlers)
    yield
    logger.handlers = saved_handlers
