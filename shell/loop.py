"""Main REPL loop."""
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

from shell.config.schema import ShellConfig


def _out(text: str) -> None:
    """Write text to stdout and flush. Never blocks."""
    sys.stdout.write(text + "\n")
    sys.stdout.flush()


# One-shot bash bypass flag — set by Ctrl+B, cleared after one command
_bypass_next: bool = False
_offline_mode: bool = False
_budget_hard_stop: bool = False


def set_offline_mode(offline: bool) -> None:
    global _offline_mode
    _offline_mode = offline


def _make_key_bindings(db=None) -> KeyBindings:
    kb = KeyBindings()

    @kb.add("c-b")
    def _ctrl_b(event) -> None:
        global _bypass_next
        _bypass_next = True
        _out("[bash mode] next command runs directly")

    @kb.add("c-t")
    def _ctrl_t(event) -> None:
        try:
            from shell.tui.layout import toggle_sidebar
            toggle_sidebar()
        except Exception:
            pass

    @kb.add("c-x")
    def _ctrl_x(event) -> None:
        event.app.current_buffer.set_document(
            __import__("prompt_toolkit.document", fromlist=["Document"]).Document("/config")
        )
        event.app.current_buffer.validate_and_handle()

    return kb


def _build_backend(config: ShellConfig):
    from shell.llm.ollama import OllamaBackend
    from shell.llm.openai import OpenAIBackend
    from shell.llm.anthropic import AnthropicBackend

    if config.backend == "ollama":
        return OllamaBackend(base_url=config.api_base or "http://localhost:11434", model=config.model)
    elif config.backend == "openai":
        api_key = os.environ.get("OPENAI_API_KEY") or getattr(config, "api_key", "") or ""
        return OpenAIBackend(api_key=api_key, model=config.model)
    elif config.backend == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or getattr(config, "api_key", "") or ""
        return AnthropicBackend(api_key=api_key, model=config.model)
    else:
        return OllamaBackend(base_url=config.api_base or "http://localhost:11434", model=config.model)


def _get_os_info() -> str:
    try:
        return f"{platform.system()} {platform.release()}"
    except Exception:
        return "Linux"


async def _call_llm(backend, user_input: str, cwd: str, config: ShellConfig, session_context: str = ""):
    import httpx
    from shell.llm.base import build_system_prompt

    system = build_system_prompt(
        cwd=cwd,
        user=os.environ.get("USER", os.environ.get("USERNAME", "user")),
        os_info=_get_os_info(),
    )

    nl_input = user_input
    if config.privacy_mode:
        from shell.safety import strip_secrets
        nl_input, count = strip_secrets(user_input)
        if count:
            _out(f"[redacted {count} secret pattern(s)]")

    messages = []
    if session_context:
        messages.append({"role": "user", "content": f"[Previous session context]\n{session_context}"})
        messages.append({"role": "assistant", "content": "Understood, I have the context from your previous session."})
    messages.append({"role": "user", "content": nl_input})

    try:
        response = await backend.complete(messages, system)
        if _offline_mode:
            set_offline_mode(False)
            _out("[model back online]")
        return response
    except (httpx.TimeoutException, httpx.ConnectError, httpx.HTTPStatusError):
        set_offline_mode(True)
        _out("[model offline — running in manual mode]")
        return None


def _display_command_preview(response) -> str | None:
    _out("")
    _out(f"  {response.explanation}")
    _out("  $ " + response.command)
    _out("")

    try:
        answer = input("run? [Enter=yes  e=edit  q=cancel]: ").strip()
    except (EOFError, KeyboardInterrupt):
        return None

    if answer.lower() == "q":
        _out("cancelled")
        return None

    if answer.lower() == "e":
        try:
            edited = input(f"edit> ").strip()
        except (EOFError, KeyboardInterrupt):
            return None
        return edited or response.command

    # Enter or anything else = run as-is
    return response.command


def _audit_log(action: str, command: str, exit_code: int | None = None) -> None:
    import datetime, getpass
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
        pass


def _log_event(db, session_id: str, response, command: str, exit_code: int, nl_input: str) -> None:
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
        pass


def _check_and_enforce_budget(db, config: ShellConfig, session_id: str) -> bool:
    global _budget_hard_stop
    if _budget_hard_stop:
        _out("Budget exhausted. Use '/budget reset' to continue.")
        return False
    if db is None:
        return True
    try:
        status = db.check_budget(config, session_id)
        if status == "HARD_STOP":
            _budget_hard_stop = True
            _out("Budget limit reached. LLM calls disabled. Use '/budget reset' to clear.")
            return False
        elif status == "WARNING":
            _out("Warning: Budget at 80%+ — approaching limit.")
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
        import pathlib
        pathlib.Path.home().joinpath(".local", "share", "agentic-shell", "exit_requested").touch()
        raise SystemExit(0)

    if cmd == "/model":
        _out(f"backend: {config.backend}  model: {config.model}")
        return True

    if cmd == "/mode":
        current = getattr(config, "routing_mode", "auto")
        new_mode = "prefix" if current == "auto" else "auto"
        config.routing_mode = new_mode
        if new_mode == "prefix":
            _out("Routing mode: prefix — prefix your request with >> to send to LLM")
        else:
            _out("Routing mode: auto — shell auto-detects bash vs natural language")
        return True

    if cmd == "/new":
        _start_new_session()
        return True

    if cmd in ("/config", "Ctrl+X"):
        try:
            from shell.tui.panel import render_settings_panel
            new_config = render_settings_panel(config)
            if new_config is not None:
                for field in vars(new_config):
                    setattr(config, field, getattr(new_config, field))
        except Exception as exc:
            _out(f"Settings panel error: {exc}")
        return True

    if cmd == "/budget reset":
        _budget_hard_stop = False
        _out("Budget hard-stop cleared.")
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
    if db is None:
        _out("Telemetry not available.")
        return
    try:
        rows = db.get_stats(days=7)
        _out("\nToken Usage — Last 7 Days")
        _out(f"{'Day':<12} {'Calls':>6} {'Tokens':>8} {'Cost':>10}")
        _out("-" * 40)
        for r in rows:
            _out(f"{r['day']:<12} {r['calls']:>6} {r['tokens'] or 0:>8} ${r['cost']:.4f}" if r["cost"] else f"{r['day']:<12} {r['calls']:>6} {r['tokens'] or 0:>8} $0.0000")
        _out("")
    except Exception as exc:
        _out(f"Stats error: {exc}")


def _show_stats_csv(db) -> None:
    if db is None:
        _out("day,calls,tokens,cost")
        return
    try:
        rows = db.get_stats(days=7)
        _out("day,calls,tokens,cost")
        for r in rows:
            _out(f"{r['day']},{r['calls']},{r['tokens'] or 0},{r['cost'] or 0:.6f}")
    except Exception as exc:
        _out(f"Stats error: {exc}")


def _show_memory(session_id: str) -> None:
    from shell.memory.store import load_session_context
    username = os.environ.get("USER", os.environ.get("USERNAME", "user"))
    ctx = load_session_context(username)
    if not ctx:
        _out("No session context loaded.")
        return
    _out("\nActive session context:")
    _out("─" * 60)
    _out(ctx[:1000])
    if len(ctx) > 1000:
        _out("... (truncated)")
    _out("")
    try:
        answer = input("[c]lear context or Enter to keep: ").strip().lower()
        if answer == "c":
            from shell.memory.store import save_session_context
            save_session_context(session_id, "", [], 0)
            _out("Context cleared.")
    except (EOFError, KeyboardInterrupt):
        pass


def _start_new_session() -> None:
    import subprocess, shutil, time
    if not shutil.which("tmux"):
        _out("tmux not found — restarting shell process.")
        os.execv(sys.executable, [sys.executable, "-m", "shell.main"])
        return

    _out("Starting new session...")
    try:
        result = subprocess.run(["tmux", "display-message", "-p", "#S"], capture_output=True, text=True)
        current_session = result.stdout.strip()
    except Exception:
        current_session = ""

    new_name = f"agentic-{int(time.time()) % 10000}"
    install_dir = os.environ.get("PYTHONPATH", "")
    venv_python = os.environ.get("AGENTIC_PYTHON", sys.executable)

    try:
        # Create session with proper dimensions
        subprocess.run(["tmux", "new-session", "-d", "-s", new_name, "-x", "220", "-y", "50"], check=True)

        # Pane 0 = shell (left), split right for telemetry (pane 1, 45 cols)
        subprocess.run(["tmux", "split-window", "-h", "-t", f"{new_name}:0.0", "-l", "45"], check=True)
        subprocess.run(["tmux", "swap-pane", "-s", f"{new_name}:0.0", "-t", f"{new_name}:0.1"], check=True)

        # Telemetry in pane 1 (right after swap)
        subprocess.run(["tmux", "send-keys", "-t", f"{new_name}:0.1",
            f"trap '' INT; while true; do PYTHONPATH={install_dir} PROMPT_TOOLKIT_NO_CPR=1 {venv_python} -m shell.telemetry.watch; sleep 2; done",
            "Enter"], check=True)

        # Shell in pane 0 (left after swap)
        subprocess.run(["tmux", "send-keys", "-t", f"{new_name}:0.0",
            f"trap '' INT; while true; do PYTHONPATH={install_dir} PROMPT_TOOLKIT_NO_CPR=1 NO_TMUX=1 {venv_python} -m shell.main; echo '[shell exited — restarting in 2s]'; sleep 2; done",
            "Enter"], check=True)

        subprocess.run(["tmux", "select-pane", "-t", f"{new_name}:0.0"], check=True)
        subprocess.run(["tmux", "switch-client", "-t", new_name], check=True)

        if current_session and current_session != new_name:
            subprocess.run(["tmux", "kill-session", "-t", current_session])
    except Exception as exc:
        _out(f"Failed to create new session: {exc}")


def start(config: ShellConfig, session_id: str, session_context: str = "") -> None:
    global _bypass_next

    from shell.executor import execute_bash
    from shell.router import classify, Route
    from shell.safety import is_destructive, confirm_destructive
    from shell.planner import execute_plan

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

        if _handle_builtin(line, db, session_id, config):
            continue

        if _bypass_next:
            _bypass_next = False
            exit_code, _ = execute_bash(line, cwd)
            if exit_code != 0:
                _out(f"exit {exit_code}")
            continue

        if _offline_mode:
            exit_code, _ = execute_bash(line, cwd)
            if exit_code != 0:
                _out(f"exit {exit_code}")
            continue

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
            if is_destructive(line):
                if not confirm_destructive(line):
                    _audit_log("destructive_blocked", line)
                    continue
            exit_code, _ = execute_bash(line, cwd)
            _audit_log("bash", line, exit_code)
            if exit_code != 0:
                _out(f"exit {exit_code}")
            continue

        if not _check_and_enforce_budget(db, config, session_id):
            exit_code, _ = execute_bash(line, cwd)
            if exit_code != 0:
                _out(f"exit {exit_code}")
            continue

        try:
            response = asyncio.run(_call_llm(backend, line, cwd, config, session_context))
        except KeyboardInterrupt:
            _out("cancelled")
            continue

        if response is None:
            exit_code, _ = execute_bash(line, cwd)
            if exit_code != 0:
                _out(f"exit {exit_code}")
            continue

        if response.plan:
            last_exit = execute_plan(response.plan, cwd, description=line)
            _log_event(db, session_id, response, str(response.plan), last_exit, line)
            continue

        command = _display_command_preview(response)
        if command is None:
            continue

        final_safe = response.safe and not is_destructive(command)
        if not final_safe:
            if not confirm_destructive(command):
                continue

        exit_code, _ = execute_bash(command, cwd)
        if exit_code != 0:
            _out(f"exit {exit_code}")

        _log_event(db, session_id, response, command, exit_code, line)
        _audit_log("agentic", command, exit_code)
