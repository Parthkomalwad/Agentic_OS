"""Session context persistence.

Loads and saves compressed context to/from the session_memory SQLite table.
Used on login (resume) and after each compression cycle.
"""
from __future__ import annotations

MAX_RESUME_TOKENS = 500


def load_session_context(username: str) -> str | None:
    """Load the most recent compressed context for this user.

    Only loads if the context is under 500 tokens to avoid bloating prompts.

    Args:
        username: OS username of the logged-in user.

    Returns:
        Compressed context string, or None if unavailable/too large.
    """
    try:
        from shell.telemetry.db import Database

        db = Database()
        row = db.get_latest_session_memory(username)
        db.close()

        if row is None:
            return None

        if row["token_count"] > MAX_RESUME_TOKENS:
            return None

        return row["compressed"]
    except Exception:
        return None


def save_session_context(
    session_id: str, compressed: str, raw_turns: list[dict], token_count: int
) -> None:
    """Persist a compressed context snapshot to session_memory table.

    Args:
        session_id: UUID for the current shell session.
        compressed: Compressed context string.
        raw_turns: Full raw turn list archived as JSON.
        token_count: Token count of the compressed block.
    """
    import os

    try:
        from shell.telemetry.db import Database

        username = os.environ.get("USER", os.environ.get("USERNAME", "unknown"))
        db = Database()
        db.save_session_memory(
            session_id=session_id,
            username=username,
            compressed=compressed,
            raw_turns=raw_turns,
            token_count=token_count,
        )
        db.close()
    except Exception:
        pass  # Fail silently — memory persistence is best-effort
