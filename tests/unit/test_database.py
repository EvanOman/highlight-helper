"""Tests for database durability configuration."""

import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.core.database import _configure_sqlite_pragmas


class TestSQLitePragmas:
    """Tests for SQLite pragma configuration."""

    def test_configure_sqlite_pragmas_sets_wal_mode(self):
        """Test that WAL mode is enabled."""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor

        # Simulate WAL mode being successfully set
        mock_cursor.fetchone.return_value = ("wal",)

        _configure_sqlite_pragmas(mock_connection, None)

        # Verify all pragmas are set
        pragma_calls = [call[0][0] for call in mock_cursor.execute.call_args_list]
        assert "PRAGMA journal_mode=WAL" in pragma_calls
        assert "PRAGMA synchronous=NORMAL" in pragma_calls
        assert "PRAGMA busy_timeout=5000" in pragma_calls

    def test_configure_sqlite_pragmas_warns_on_wal_failure(self):
        """Test that a warning is logged if WAL mode fails to enable."""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor

        # Simulate WAL mode NOT being set (returns 'delete' instead)
        mock_cursor.fetchone.return_value = ("delete",)

        with patch("app.core.database.logger") as mock_logger:
            _configure_sqlite_pragmas(mock_connection, None)

            # Verify warning was logged
            mock_logger.warning.assert_called_once()
            warning_msg = mock_logger.warning.call_args[0][0]
            assert "Failed to enable WAL mode" in warning_msg
            assert "delete" in warning_msg

    def test_configure_sqlite_pragmas_logs_success(self):
        """Test that success is logged when WAL mode is enabled."""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor

        # Simulate WAL mode being successfully set
        mock_cursor.fetchone.return_value = ("wal",)

        with patch("app.core.database.logger") as mock_logger:
            _configure_sqlite_pragmas(mock_connection, None)

            # Verify debug log for success
            mock_logger.debug.assert_called_once()
            debug_msg = mock_logger.debug.call_args[0][0]
            assert "WAL mode enabled successfully" in debug_msg

    def test_configure_sqlite_pragmas_closes_cursor(self):
        """Test that the cursor is properly closed after configuration."""
        mock_connection = MagicMock()
        mock_cursor = MagicMock()
        mock_connection.cursor.return_value = mock_cursor
        mock_cursor.fetchone.return_value = ("wal",)

        _configure_sqlite_pragmas(mock_connection, None)

        mock_cursor.close.assert_called_once()


class TestWALModeIntegration:
    """Integration tests for WAL mode with real SQLite database."""

    @pytest.mark.asyncio
    async def test_wal_mode_enabled_on_real_database(self):
        """Test that WAL mode is actually enabled on a real SQLite database."""
        import sqlite3

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            db_path = f.name

        # Create a real connection and configure pragmas
        conn = sqlite3.connect(db_path)
        _configure_sqlite_pragmas(conn, None)

        # Verify WAL mode is enabled
        cursor = conn.cursor()
        cursor.execute("PRAGMA journal_mode")
        result = cursor.fetchone()
        assert result[0].lower() == "wal"

        # Verify synchronous mode
        cursor.execute("PRAGMA synchronous")
        result = cursor.fetchone()
        # NORMAL = 1
        assert result[0] == 1

        # Verify busy_timeout
        cursor.execute("PRAGMA busy_timeout")
        result = cursor.fetchone()
        assert result[0] == 5000

        cursor.close()
        conn.close()

        # Cleanup
        import os

        os.unlink(db_path)
        # WAL files may have been created
        for suffix in ["-wal", "-shm"]:
            try:
                os.unlink(db_path + suffix)
            except FileNotFoundError:
                pass
