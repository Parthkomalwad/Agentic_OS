"""SQLite session database.

Database path: ~/.local/share/agentic-shell/sessions.db
Always opened with WAL mode and NORMAL synchronous for performance.

Tables:
- token_events: per-call telemetry
- session_memory: compressed context snapshots
"""
from __future__ import annotations

import json
import sqlite3
from datetime import date
from pathlib import Path

from shell.telemetry.events import TokenEvent

DB_PATH = Path.home() / ".local" / "share" / "agentic-shell" / "sessions.db"

_CREATE_TOKEN_EVENTS = """
CREATE TABLE IF NOT EXISTS token_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    session_id TEXT NOT NULL,
    action_type TEXT NOT NULL,
    nl_input TEXT,
    command TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    completion_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd REAL NOT NULL DEFAULT 0.0,
    model TEXT,
    exit_code INTEGER
)
"""

_CREATE_SESSION_MEMORY = """
CREATE TABLE IF NOT EXISTS session_memory (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL,
    username TEXT NOT NULL,
    compressed TEXT NOT NULL,
    raw_turns TEXT NOT NULL,
    token_count INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
)
"""


class Database:
    """Manages the SQLite session database."""

    def __init__(self) -> None:
        """Open (or create) the sessions.db file with WAL mode."""
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute(_CREATE_TOKEN_EVENTS)
        self._conn.execute(_CREATE_SESSION_MEMORY)
        self._conn.commit()

    def write_event(self, event: TokenEvent) -> None:
        """Insert a TokenEvent into token_events table."""
        self._conn.execute(
            """
            INSERT INTO token_events
                (timestamp, session_id, action_type, nl_input, command,
                 prompt_tokens, completion_tokens, total_tokens, cost_usd, model, exit_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.timestamp,
                event.session_id,
                event.action_type,
                event.nl_input,
                event.command,
                event.prompt_tokens,
                event.completion_tokens,
                event.total_tokens,
                event.cost_usd,
                event.model,
                event.exit_code,
            ),
        )
        self._conn.commit()

    def get_daily_spend(self) -> float:
        """Return cumulative cost_usd for today."""
        today = date.today().isoformat()
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM token_events WHERE timestamp LIKE ?",
            (f"{today}%",),
        ).fetchone()
        return float(row[0])

    def get_session_spend(self, session_id: str) -> float:
        """Return cumulative cost_usd for the current session."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(cost_usd), 0.0) FROM token_events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return float(row[0])

    def check_budget(self, config, session_id: str) -> str:
        """Return 'OK', 'WARNING' (>=80%), or 'HARD_STOP' (>=100%).

        Checks both daily and session budgets. Returns the worst status.
        """
        status = "OK"

        if config.daily_token_budget:
            daily_cost = self.get_daily_spend()
            # Estimate tokens from cost — use a rough $0.001/1k tokens as fallback
            # For budget enforcement we track cost_usd directly
            daily_pct = daily_cost / max(config.daily_token_budget * 0.000001, 0.000001)
            if daily_pct >= 1.0:
                return "HARD_STOP"
            elif daily_pct >= 0.8:
                status = "WARNING"

        if config.session_token_budget:
            session_tokens = self._get_session_total_tokens(session_id)
            session_pct = session_tokens / config.session_token_budget
            if session_pct >= 1.0:
                return "HARD_STOP"
            elif session_pct >= 0.8:
                status = "WARNING"

        return status

    def _get_session_total_tokens(self, session_id: str) -> int:
        """Return total tokens used in this session."""
        row = self._conn.execute(
            "SELECT COALESCE(SUM(total_tokens), 0) FROM token_events WHERE session_id = ?",
            (session_id,),
        ).fetchone()
        return int(row[0])

    def get_stats(self, days: int = 7) -> list[dict]:
        """Return per-day aggregated stats for the last N days."""
        rows = self._conn.execute(
            """
            SELECT
                substr(timestamp, 1, 10) AS day,
                COUNT(*) AS calls,
                SUM(total_tokens) AS tokens,
                SUM(cost_usd) AS cost
            FROM token_events
            WHERE timestamp >= date('now', ?)
            GROUP BY day
            ORDER BY day DESC
            """,
            (f"-{days} days",),
        ).fetchall()
        return [{"day": r[0], "calls": r[1], "tokens": r[2], "cost": r[3]} for r in rows]

    def save_session_memory(
        self,
        session_id: str,
        username: str,
        compressed: str,
        raw_turns: list[dict],
        token_count: int,
    ) -> None:
        """Insert a compressed context snapshot into session_memory table."""
        from datetime import datetime, timezone
        self._conn.execute(
            """
            INSERT INTO session_memory (session_id, username, compressed, raw_turns, token_count, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                username,
                compressed,
                json.dumps(raw_turns),
                token_count,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        self._conn.commit()

    def get_latest_session_memory(self, username: str) -> dict | None:
        """Return the most recent session_memory row for this user, or None."""
        row = self._conn.execute(
            """
            SELECT compressed, raw_turns, token_count, created_at
            FROM session_memory
            WHERE username = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (username,),
        ).fetchone()
        if row is None:
            return None
        return {
            "compressed": row[0],
            "raw_turns": json.loads(row[1]),
            "token_count": row[2],
            "created_at": row[3],
        }

    def get_last_model(self) -> str:
        """Return the most recently used model name, or 'unknown'."""
        row = self._conn.execute(
            "SELECT model FROM token_events WHERE model IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row[0] if row else "unknown"

    def get_today_stats(self) -> dict:
        """Return today's total calls, tokens, and cost."""
        today = date.today().isoformat()
        row = self._conn.execute(
            """SELECT COUNT(*), COALESCE(SUM(total_tokens), 0), COALESCE(SUM(cost_usd), 0.0)
               FROM token_events WHERE timestamp LIKE ?""",
            (f"{today}%",),
        ).fetchone()
        return {"calls": row[0], "tokens": row[1], "cost": row[2]}

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()
