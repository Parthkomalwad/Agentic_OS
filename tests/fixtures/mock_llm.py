"""Mock LLM backend for unit and integration tests.

Returns canned LLMResponse objects for known inputs.
Never makes real HTTP calls. Used in all tests that exercise the agentic path.
"""
from __future__ import annotations
from shell.llm.base import LLMBackend, LLMResponse

# Canned responses keyed by nl_input substring
CANNED_RESPONSES: dict[str, LLMResponse] = {
    "list files": LLMResponse(
        command="ls -la",
        explanation="List all files in the current directory with details.",
        safe=True,
        plan=None,
        prompt_tokens=120,
        completion_tokens=30,
        cost_usd=0.0,
    ),
    "disk usage": LLMResponse(
        command="df -h",
        explanation="Show disk usage in human-readable format.",
        safe=True,
        plan=None,
        prompt_tokens=115,
        completion_tokens=25,
        cost_usd=0.0,
    ),
    "set up nginx": LLMResponse(
        command="",
        explanation="Multi-step nginx setup.",
        safe=True,
        plan=[
            "apt install nginx -y",
            "systemctl enable nginx",
            "systemctl start nginx",
        ],
        prompt_tokens=200,
        completion_tokens=60,
        cost_usd=0.0,
    ),
    "delete everything": LLMResponse(
        command="rm -rf /",
        explanation="Delete all files on the system.",
        safe=False,
        plan=None,
        prompt_tokens=100,
        completion_tokens=20,
        cost_usd=0.0,
    ),
}


class MockLLMBackend(LLMBackend):
    """Mock LLM backend that returns canned responses for known inputs."""

    async def complete(self, messages: list[dict], system: str) -> LLMResponse:
        """Return a canned LLMResponse based on the last user message.

        Falls back to a generic safe response if no key matches.
        """
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        ).lower()

        for key, response in CANNED_RESPONSES.items():
            if key in last_user:
                return response

        return LLMResponse(
            command="echo 'unknown input'",
            explanation="Default mock response.",
            safe=True,
            plan=None,
            prompt_tokens=100,
            completion_tokens=20,
            cost_usd=0.0,
        )
