"""Main REPL loop.

Provides the prompt_toolkit-based input loop with:
- cwd-based prompt string
- FileHistory for persistent command history
- Input routing via router.py
- Ctrl+B escape hatch (one-shot bash bypass)
- Ctrl+T sidebar toggle
- Offline fallback flag handling
- Budget enforcement (warn at 80%, hard stop at 100%)
- /budget reset, /stats, /memory built-in commands
- Session memory compression and telemetry logging
"""
from __future__ import annotations

import asyncio
import os
import platform
import sys
from pathlib import Path

os.environ["PROMPT_TOOLKIT_NO_CPR"] = "1"

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from prompt_toolkit.formatted_text import HTML
from prompt_toolkit.key_binding import KeyBindings
from rich.console import Console
from rich.syntax import Syntax
from rich.table import Table

from shell.config.schema import ShellConfig

console = Console(force_terminal=True, force_jupyter=False, highlight=False, width=120)

# One-shot bash bypass flag — set by Ctrl+B, cleared after one command
_bypass_next: bool = False

# Offline mode flag — set when LLM is unreachable, cleared on next success
_offline_mode: bool = False

# Hard-stop flag — set when budget is exhausted
_budget_hard_stop: bool = False


def set_offline_mode(offline: bool) -> None:
    """Set offline mode flag. When True, LLM calls skip to bash directly."""
    global _offline_mode
    _offline_mode = offline


def _make_key_bindings(db=None) -> KeyBindings:
    """Build custom key bindings (Ctrl+B escape hatch, Ctrl+T sidebar toggle)."""
    kb = KeyBindings()

    @kb.add("c-b")
    def _ctrl_b(event) -> None:
        global _bypass_next
        _bypass_next = True
        console.print("[dim][bash mode] next command runs directly[/dim]")

    @kb.add("c-t")
    def _ctrl_t(event) -> None:
        try:
            from shell.tui.layout import toggle_sidebar
            toggle_sidebar()
        except Exception:
            pass

    @kb.add("c-x")
    def _ctrl_x(event) -> None:
        # Insert /config as the current buffer text — handled in main loop
        event.app.current_buffer.set_document(
            __import__("prompt_toolkit.document", fromlist=["Document"]).Document("/config")
        )
        event.app.current_buffer.validate_and_handle()

    return kb


def _build_backend(config: ShellConfig):
    """Instantiate the configured LLM backend."""
    from shell.llm.ollama import OllamaBackend
    from shell.llm.openai import OpenAIBackend
    from shell.llm.anthropic import AnthropicBackend

    if config.backend == "ollama":
        return OllamaBackend(
            base_url=config.api_base or "http://localhost:11434",
            model=config.model,
        )
    elif config.backend == "openai":
        api_key = os.environ.get("OPENAI_API_KEY") or getattr(config, "api_key", "") or ""
        return OpenAIBackend(api_key=api_key, model=config.model)
    elif config.backend == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or getattr(config, "api_key", "") or ""
        return AnthropicBackend(api_key=api_key, model=config.model)
    else:
        return OllamaBackend(
            base_url=config.api_base or "http://localhost:11434",
            model=config.model,
        )


def _get_os_info() -> str:
    try:
        return f"{platform.system()} {platform.release()}"
    except Exception:
        return "Linux"


async def _call_llm(backend, user_input: str, cwd: str, config: ShellConfig, session_context: str = ""):
    """Call the LLM backend and return an LLMResponse, handling offline fallback."""
    import httpx
    from shell.llm.base import build_system_prompt

    os_info = _get_os_info()
    system = build_system_prompt(
        cwd=cwd,
        user=os.environ.get("USER", os.environ.get("USERNAME", "user")),
        os_info=os_info,
    )

    nl_input = user_input
    if config.privacy_mode:
        from shell.safety import strip_secrets
        nl_input, count = strip_secrets(user_input)
        if count:
            console.print(f"[dim]⚑ redacted {count} secret pattern(s) before sending to model[/dim]")

    messages = []
    if session_context:
        messages.append({"role": "user", "content": f"[Previous session context]\n{session_context}"})
        messages.append({"role": "assistant", "content": "Understood, I have the context from your previous session."})
    messages.append({"role": "user", "content": nl_input})

    try:
        response = await backend.complete(messages, system)
        if _offline_mode:
            set_offline_mode(False)
            console.print("[dim][model back online][/dim]")
        return response
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError):
        set_offline_mode(True)
        console.print("[yellow][model offline — running in manual mode][/yellow]")
        return None


def _display_command_preview(response) -> str | None:
    """Show the LLM response and let user edit/confirm/cancel.

    Returns the (possibly edited) command to run, or None if cancelled.
    """
    from prompt_toolkit import prompt as pt_prompt
    from prompt_toolkit.formatted_text import HTML as PTHTML

    console.print()
    console.print(f"[bold green]✓ understood:[/bold green] {response.explanation}")
    console.print("─" * 60)
    console.print(Syntax(response.command, "bash", theme="monokai", background_color="default"))
    console.print()

    try:
        answer = pt_prompt(
            PTHTML("<ansiyellow>run?</ansiyellow> [Enter]  <ansicyan>edit [e]</ansicyan>  <ansired>cancel [q]</ansired>  > "),
            default=response.command,
        )
    except (EOFError, KeyboardInterrupt):
        return None

    if answer.strip().lower() == "q":
        console.print("[dim]cancelled[/dim]")
        return None

    return answer.strip() or None


def _audit_log(action: str, command: str, exit_code: int | None = None) -> None:
    """Append a line to the audit log. Fails silently on permission error."""
    import datetime
    import getpass

    log_path = "/var/log/agentic-shell/audit.log"
    try:
        user = getpass.getuser()
    except Exception:
        user = "unknown"
    timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
    line = f"{timestamp} user={user} action={action} cmd={command!r} exit={exit_code}\n"
    try:
        with open(log_path, "a") as f:
            f.write(line)
    except (PermissionError, OSError):
        pass  # Fail silently — audit log is best-effort


def _log_event(db, session_id: str, response, command: str, exit_code: int, nl_input: str) -> None:
    """Write a TokenEvent to the telemetry database."""
    try:
        from datetime import datetime, timezone
        from shell.telemetry.events import TokenEvent

        event = TokenEvent(
            timestamp=datetime.now(timezone.utc).isoformat(),
            session_id=session_id,
            action_type="nl_route",
            nl_input=nl_input,
            command=command,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            total_tokens=response.prompt_tokens + response.completion_tokens,
            cost_usd=response.cost_usd,
            model=getattr(response, "model", None),
            exit_code=exit_code,
        )
        db.write_event(event)
    except Exception:
        pass  # Telemetry failure is never fatal


def _check_and_enforce_budget(db, config: ShellConfig, session_id: str) -> bool:
    """Check budget. Returns False (block) if HARD_STOP, True (allow) otherwise."""
    global _budget_hard_stop

    if _budget_hard_stop:
        console.print("[red]Budget exhausted. Use '/budget reset' to continue.[/red]")
        return False

    if db is None:
        return True

    try:
        status = db.check_budget(config, session_id)
        if status == "HARD_STOP":
            _budget_hard_stop = True
            console.print("[bold red]⛔ Budget limit reached. LLM calls disabled.[/bold red]")
            console.print("[dim]Use '/budget reset' to clear the hard-stop flag.[/dim]")
            return False
        elif status == "WARNING":
            console.print("[yellow]⚠ Budget at 80%+ — approaching limit.[/yellow]")
    except Exception:
        pass

    return True


_HELP_TEXT = (
    "\nAgentic Shell - Built-in Commands\n"
    "----------------------------------\n"
    "  /new           Start a fresh tmux session\n"
    "  /clear         Clear the terminal screen\n"
    "  /exit          Exit the shell\n"
    "  /config        Open settings panel (Ctrl+X)\n"
    "  /mode          Toggle routing: auto / prefix\n"
    "  /model         Show current LLM model\n"
    "  /stats         Last 7 days token usage\n"
    "  /budget reset  Clear hard-stop budget flag\n"
    "  /memory        View/clear session context\n"
    "\n"
    "  >> text        Force agentic (prefix mode)\n"
    "  Ctrl+B         Next command runs as raw bash\n"
    "  Ctrl+T         Toggle telemetry sidebar\n"
)


def _handle_builtin(line: str, db, session_id: str, config: ShellConfig) -> bool:
    """Handle built-in slash commands. Returns True if handled, False otherwise."""
    global _budget_hard_stop

    cmd = line.strip()

    if cmd in ("/help", "/?"):
        sys.stdout.write(_HELP_TEXT + "\n")
        sys.stdout.flush()
        return True

    if cmd == "/clear":
        os.system("clear")
        return True

    if cmd in ("/exit", "/quit"):
        raise SystemExit(0)

    if cmd == "/model":
        console.print(f"[dim]backend:[/dim] [bold]{config.backend}[/bold]  [dim]model:[/dim] [bold magenta]{config.model}[/bold magenta]")
        return True

    if cmd == "/mode":
        current = getattr(config, "routing_mode", "auto")
        new_mode = "prefix" if current == "auto" else "auto"
        config.routing_mode = new_mode
        if new_mode == "prefix":
            console.print("[cyan]Routing mode: prefix[/cyan] — prefix your request with [bold]>>[/bold] to send to LLM")
        else:
            console.print("[cyan]Routing mode: auto[/cyan] — shell auto-detects bash vs natural language")
        return True

    if cmd == "/new":
        _start_new_session()
        return True

    if cmd in ("/config", "Ctrl+X"):
        try:
            from shell.tui.panel import render_settings_panel
            new_config = render_settings_panel(config)
            if new_config is not None:
                # Mutate config in place so the running loop picks up changes
                for field in vars(new_config):
                    setattr(config, field, getattr(new_config, field))
        except Exception as exc:
            console.print(f"[red]Settings panel error: {exc}[/red]")
        return True

    if cmd == "/budget reset":
        _budget_hard_stop = False
        console.print("[green]✓ Budget hard-stop cleared.[/green]")
        return True

    if cmd in ("/stats", "shell stats"):
        _show_stats(db)
        return True

    if cmd == "shell stats --csv":
        _show_stats_csv(db)
        return True

    if cmd in ("/memory", "shell memory"):
        _show_memory(session_id)
        return True

    return False


def _show_stats(db) -> None:
    """Display a Rich table of last 7 days token usage."""
    if db is None:
        console.print("[dim]Telemetry not available.[/dim]")
        return

    try:
        rows = db.get_stats(days=7)
        table = Table(title="Token Usage — Last 7 Days", show_header=True)
        table.add_column("Day", style="cyan")
        table.add_column("Calls", justify="right")
        table.add_column("Tokens", justify="right")
        table.add_column("Cost (USD)", justify="right", style="green")

        for r in rows:
            table.add_row(
                r["day"],
                str(r["calls"]),
                str(r["tokens"] or 0),
                f"${r['cost']:.4f}" if r["cost"] else "$0.0000",
            )

        console.print()
        console.print(table)
        console.print()
    except Exception as exc:
        console.print(f"[red]Stats error: {exc}[/red]")


def _show_stats_csv(db) -> None:
    """Output stats as CSV."""
    if db is None:
        console.print("day,calls,tokens,cost")
        return

    try:
        rows = db.get_stats(days=7)
        console.print("day,calls,tokens,cost")
        for r in rows:
            console.print(f"{r['day']},{r['calls']},{r['tokens'] or 0},{r['cost'] or 0:.6f}")
    except Exception as exc:
        console.print(f"[red]Stats error: {exc}[/red]")


def _show_memory(session_id: str) -> None:
    """Display active session context with option to clear."""
    from shell.memory.store import load_session_context
    import os

    username = os.environ.get("USER", os.environ.get("USERNAME", "user"))
    ctx = load_session_context(username)

    if not ctx:
        console.print("[dim]No session context loaded.[/dim]")
        return

    console.print()
    console.print("[bold]Active session context:[/bold]")
    console.print("─" * 60)
    console.print(ctx[:1000])
    if len(ctx) > 1000:
        console.print("[dim]... (truncated)[/dim]")
    console.print()

    try:
        answer = input("[c]lear context or Enter to keep: ").strip().lower()
        if answer == "c":
            # Clear by saving empty context
            from shell.memory.store import save_session_context
            save_session_context(session_id, "", [], 0)
            console.print("[green]✓ Context cleared.[/green]")
    except (EOFError, KeyboardInterrupt):
        pass


def _start_new_session() -> None:
    """Kill current tmux session and start a fresh agentic-shell."""
    import subprocess
    import shutil
    import time

    tmux_pane = os.environ.get("TMUX_PANE") or os.environ.get("TMUX")
    if not tmux_pane or not shutil.which("tmux"):
        console.print("[yellow]Not inside tmux — restarting shell process.[/yellow]")
        os.execv(sys.executable, [sys.executable, "-m", "shell.main"])
        return

    console.print("[dim]Starting new session...[/dim]")
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#S"],
            capture_output=True, text=True
        )
        current_session = result.stdout.strip()
    except Exception:
        current_session = ""

    new_name = f"agentic-{int(time.time()) % 10000}"
    try:
        subprocess.run(["tmux", "new-session", "-d", "-s", new_name, "-x", "220", "-y", "50"], check=True)
        subprocess.run(["tmux", "send-keys", "-t", new_name, "agentic-shell", "Enter"], check=True)
        subprocess.run(["tmux", "switch-client", "-t", new_name], check=True)
        if current_session and current_session != new_name:
            subprocess.run(["tmux", "kill-session", "-t", current_session])
    except Exception as exc:
        console.print(f"[red]Failed to create new session: {exc}[/red]")


def start(config: ShellConfig, session_id: str, session_context: str = "") -> None:
    """Start the interactive shell loop.

    Args:
        config: Shell configuration (LLM backend, safety settings, etc.)
        session_id: Unique session identifier for telemetry and memory.
    """
    global _bypass_next

    from shell.executor import execute_bash
    from shell.router import classify, Route
    from shell.safety import is_destructive, confirm_destructive
    from shell.planner import execute_plan

    # Initialize telemetry database (best-effort)
    db = None
    try:
        from shell.telemetry.db import Database
        db = Database()
    except Exception:
        pass

    history_file = Path.home() / ".local" / "share" / "agentic-shell" / "history"
    history_file.parent.mkdir(parents=True, exist_ok=True)

    kb = _make_key_bindings(db=db)
    os.environ.setdefault("PROMPT_TOOLKIT_NO_CPR", "1")
    session = PromptSession(history=FileHistory(str(history_file)), key_bindings=kb)

    backend = _build_backend(config)

    while True:
        try:
            cwd = os.getcwd()
            user_input = session.prompt(
                HTML(f'<ansigreen>{cwd}</ansigreen> <ansicyan>❯</ansicyan> '),
                in_thread=True
            )
        except EOFError:
            break

        line = user_input.strip()
        if not line:
            continue

        # --- Built-in commands ---
        if _handle_builtin(line, db, session_id, config):
            continue

        # --- Ctrl+B one-shot bash bypass ---
        if _bypass_next:
            _bypass_next = False
            exit_code, _ = execute_bash(line, cwd)
            if exit_code != 0:
                console.print(f"[red]exit {exit_code}[/red]")
            continue

        # --- Offline mode: route everything to bash ---
        if _offline_mode:
            exit_code, _ = execute_bash(line, cwd)
            if exit_code != 0:
                console.print(f"[red]exit {exit_code}[/red]")
            continue

        # --- Route input ---
        route = classify(line, mode=config.routing_mode)

        if route == Route.AMBIGUOUS:
            try:
                choice = session.prompt(
                    HTML("<ansiyellow>[b]ash or [a]gentic? </ansiyellow>")
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                choice = "b"
            route = Route.AGENTIC if choice == "a" else Route.BASH

        if route == Route.BASH:
            # Safety check even on bash path
            if is_destructive(line):
                if not confirm_destructive(line):
                    _audit_log("destructive_blocked", line)
                    continue
            exit_code, _ = execute_bash(line, cwd)
            _audit_log("bash", line, exit_code)
            if exit_code != 0:
                console.print(f"[red]exit {exit_code}[/red]")
            continue

        # --- Budget check before LLM call ---
        if not _check_and_enforce_budget(db, config, session_id):
            # Hard stop — fall back to bash
            exit_code, _ = execute_bash(line, cwd)
            if exit_code != 0:
                console.print(f"[red]exit {exit_code}[/red]")
            continue

        # --- Agentic path: call LLM ---
        try:
            response = asyncio.run(_call_llm(backend, line, cwd, config, session_context))
        except KeyboardInterrupt:
            console.print("[yellow]cancelled[/yellow]")
            continue

        if response is None:
            # Offline fallback: run input directly as bash
            exit_code, _ = execute_bash(line, cwd)
            if exit_code != 0:
                console.print(f"[red]exit {exit_code}[/red]")
            continue

        # --- Multi-step plan ---
        if response.plan:
            last_exit = execute_plan(response.plan, cwd, description=line)
            _log_event(db, session_id, response, str(response.plan), last_exit, line)
            continue

        # --- Single command: display preview, let user edit/confirm ---
        command = _display_command_preview(response)
        if command is None:
            continue

        # Safety check on the (possibly edited) command
        final_safe = response.safe and not is_destructive(command)
        if not final_safe:
            if not confirm_destructive(command):
                continue

        exit_code, _ = execute_bash(command, cwd)
        if exit_code != 0:
            console.print(f"[red]exit {exit_code}[/red]")

        # Log telemetry + audit
        _log_event(db, session_id, response, command, exit_code, line)
        _audit_log("agentic", command, exit_code)
