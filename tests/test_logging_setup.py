"""Tests for logging_setup.py."""
import logging
import unittest
from unittest.mock import patch

from towncommoniq import logging_setup


class TestLoggingSetup(unittest.TestCase):

    def test_configure_formatter(self):
        """Test that formatters are configured with the correct format string."""
        log_formatter = logging_setup._build_formatter('log')
        self.assertEqual(
            log_formatter._style._fmt,
            '{asctime} [{filename:<20}][{funcName:<20}][{levelname:8}] {message}',
        )

        console_formatter = logging_setup._build_formatter('console')
        self.assertEqual(
            console_formatter._style._fmt,
            '{asctime} [{filename}] {funcName} [{levelname}] {message}',
        )

        other_formatter = logging_setup._build_formatter('other')
        self.assertEqual(other_formatter._style._fmt, '{message}')

    @patch('towncommoniq.logging_setup.boto3.set_stream_logger')
    @patch('towncommoniq.logging_setup.logging_handlers.TimedRotatingFileHandler')
    @patch('towncommoniq.logging_setup.LOG_DIRECTORY')
    def test_configure_logging_attaches_handlers(self, mock_log_dir, mock_handler, mock_boto3):
        """Test that configure_logging() sets up the logger and its handlers."""
        logger = logging.getLogger(logging_setup._LOGGER_NAME)
        logger.handlers = []
        logging_setup.configure_logging()
        mock_log_dir.mkdir.assert_called_once_with(parents=True, exist_ok=True)
        mock_boto3.assert_called_with(name='botocore.credentials', level=logging_setup.logging.ERROR)
        self.assertEqual(len(logger.handlers), 2)
        logger.handlers = []

    @patch('towncommoniq.logging_setup.boto3.set_stream_logger')
    @patch('towncommoniq.logging_setup.logging_handlers.TimedRotatingFileHandler')
    @patch('towncommoniq.logging_setup.LOG_DIRECTORY')
    def test_configure_logging_is_idempotent(self, mock_log_dir, mock_handler, mock_boto3):
        """A second call should be a no-op and not attach handlers again."""
        logger = logging.getLogger(logging_setup._LOGGER_NAME)
        logger.handlers = [logging.NullHandler()]
        logging_setup.configure_logging()
        mock_log_dir.mkdir.assert_not_called()
        self.assertEqual(len(logger.handlers), 1)
        logger.handlers = []


if __name__ == '__main__':
    unittest.main()
