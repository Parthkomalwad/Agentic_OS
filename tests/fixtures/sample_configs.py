"""Sample ShellConfig objects for testing."""
from __future__ import annotations

OLLAMA_CONFIG = {
    "backend": "ollama",
    "model": "llama3.1",
    "api_base": "http://localhost:11434",
    "routing_mode": "auto",
    "daily_token_budget": None,
    "session_token_budget": None,
    "privacy_mode": False,
    "setup_complete": True,
}

OPENAI_CONFIG = {
    "backend": "openai",
    "model": "gpt-4o-mini",
    "api_base": None,
    "routing_mode": "auto",
    "daily_token_budget": 100000,
    "session_token_budget": 20000,
    "privacy_mode": True,
    "setup_complete": True,
}

ANTHROPIC_CONFIG = {
    "backend": "anthropic",
    "model": "claude-3-5-haiku-20241022",
    "api_base": None,
    "routing_mode": "prefix",
    "daily_token_budget": None,
    "session_token_budget": None,
    "privacy_mode": False,
    "setup_complete": True,
}

INVALID_CONFIG_MISSING_BACKEND = {
    "model": "gpt-4o",
    "api_base": None,
    "routing_mode": "auto",
    "privacy_mode": False,
    "setup_complete": False,
}

INVALID_CONFIG_BAD_ROUTING_MODE = {
    "backend": "openai",
    "model": "gpt-4o",
    "api_base": None,
    "routing_mode": "invalid_mode",
    "daily_token_budget": None,
    "session_token_budget": None,
    "privacy_mode": False,
    "setup_complete": True,
}
