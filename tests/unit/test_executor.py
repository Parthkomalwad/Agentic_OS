"""Unit tests for shell/executor.py.

Tests:
- cd interception calls os.chdir (not subprocess)
- Non-cd commands are routed to ptyprocess
- cd with ~ expands correctly
- cd with missing directory returns error

No LLM calls, no real subprocess, no file I/O beyond os.chdir.
"""
import os
import pytest
from unittest.mock import patch, MagicMock
from shell.executor import execute_bash


class TestCdInterception:
    def test_cd_calls_os_chdir(self, tmp_path):
        """cd must update the Python process cwd via os.chdir, not subprocess."""
        exit_code, output = execute_bash(f"cd {tmp_path}", cwd=str(tmp_path))
        assert exit_code == 0
        assert os.getcwd() == str(tmp_path)

    def test_cd_missing_dir_returns_error(self, tmp_path):
        exit_code, output = execute_bash("cd /nonexistent_path_xyz", cwd=str(tmp_path))
        assert exit_code == 1
        assert "No such file or directory" in output

    def test_cd_no_arg_goes_home(self):
        """'cd' with no argument should go to home directory."""
        with patch("os.chdir") as mock_chdir:
            execute_bash("cd", cwd="/tmp")
            mock_chdir.assert_called_once_with(os.path.expanduser("~"))

    def test_cd_tilde_expands(self):
        """'cd ~' should expand to home directory."""
        with patch("os.chdir") as mock_chdir:
            execute_bash("cd ~", cwd="/tmp")
            mock_chdir.assert_called_once_with(os.path.expanduser("~"))


class TestPtyProcessRouting:
    def test_non_cd_uses_ptyprocess(self):
        """Non-cd commands must go through PtyProcessUnicode, not subprocess."""
        with patch("shell.executor.PtyProcessUnicode") as mock_pty_class:
            mock_proc = MagicMock()
            mock_proc.read.side_effect = EOFError
            mock_proc.exitstatus = 0
            mock_pty_class.spawn.return_value = mock_proc

            execute_bash("ls -la", cwd="/tmp")

            mock_pty_class.spawn.assert_called_once()
            args = mock_pty_class.spawn.call_args[0][0]
            assert args == ["/bin/bash", "-c", "ls -la"]

    def test_echo_command_not_intercepted_as_cd(self):
        """'echo cd' should not trigger the cd interceptor."""
        with patch("shell.executor.PtyProcessUnicode") as mock_pty_class:
            mock_proc = MagicMock()
            mock_proc.read.side_effect = EOFError
            mock_proc.exitstatus = 0
            mock_pty_class.spawn.return_value = mock_proc

            execute_bash("echo cd /tmp", cwd="/tmp")

            mock_pty_class.spawn.assert_called_once()
