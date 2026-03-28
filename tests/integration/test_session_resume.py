"""Integration tests: session context resume on login.

Requires Docker. Tests that compressed context is loaded and injected
into LLM calls correctly on re-login.
"""
import pytest

pytestmark = pytest.mark.integration


class TestSessionResume:
    def test_context_loaded_on_login(self):
        """Compressed context from previous session is loaded at startup."""
        raise NotImplementedError("Phase 2: implement test_context_loaded_on_login")

    def test_context_not_loaded_if_too_large(self):
        """Context over 500 tokens is not loaded (would bloat prompts)."""
        raise NotImplementedError("Phase 2: implement test_context_not_loaded_if_too_large")

    def test_resume_banner_displayed(self):
        """Login banner shows compressed turn count and token size."""
        raise NotImplementedError("Phase 2: implement test_resume_banner_displayed")

    def test_context_injected_into_llm_system_prompt(self):
        """Loaded context appears in the system prompt for LLM calls."""
        raise NotImplementedError("Phase 2: implement test_context_injected_into_llm_system_prompt")
