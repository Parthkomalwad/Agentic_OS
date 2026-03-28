"""Unit tests for shell/config/schema.py.

Tests:
- ShellConfig.from_dict() accepts valid configs
- ShellConfig.from_dict() rejects invalid configs
- ShellConfig.to_dict() round-trips correctly

No LLM calls, no subprocess, no file I/O.
"""
import pytest
from shell.config.schema import ShellConfig
from tests.fixtures.sample_configs import (
    OLLAMA_CONFIG,
    OPENAI_CONFIG,
    ANTHROPIC_CONFIG,
    INVALID_CONFIG_MISSING_BACKEND,
    INVALID_CONFIG_BAD_ROUTING_MODE,
)


class TestFromDict:
    def test_valid_ollama_config(self):
        config = ShellConfig.from_dict(OLLAMA_CONFIG)
        assert config.backend == "ollama"
        assert config.model == "llama3.1"
        assert config.routing_mode == "auto"
        assert config.setup_complete is True

    def test_valid_openai_config(self):
        config = ShellConfig.from_dict(OPENAI_CONFIG)
        assert config.backend == "openai"
        assert config.privacy_mode is True
        assert config.daily_token_budget == 100000

    def test_valid_anthropic_config(self):
        config = ShellConfig.from_dict(ANTHROPIC_CONFIG)
        assert config.backend == "anthropic"
        assert config.routing_mode == "prefix"

    def test_invalid_missing_backend_raises(self):
        with pytest.raises((ValueError, KeyError)):
            ShellConfig.from_dict(INVALID_CONFIG_MISSING_BACKEND)

    def test_invalid_routing_mode_raises(self):
        with pytest.raises(ValueError):
            ShellConfig.from_dict(INVALID_CONFIG_BAD_ROUTING_MODE)


class TestToDict:
    def test_round_trip(self):
        config = ShellConfig.from_dict(OLLAMA_CONFIG)
        assert config.to_dict() == OLLAMA_CONFIG
