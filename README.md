# Agentic Shell

A Python login shell that replaces `/bin/bash` on Linux. Every command you type is routed either to bash or to a language model. The LLM generates a shell command, shows it to you for review, and executes it. A tmux sidebar shows live token cost and session memory in real time.

---

## Features

- **Smart routing** — heuristic auto-detects natural language vs shell commands; prefix `>>` to force AI mode
- **Three LLM backends** — Ollama (local, free), OpenAI, Anthropic
- **Command preview** — see the AI-generated command before it runs; edit or cancel
- **Multi-step plans** — LLM can return a plan array; each step shown upfront, with `[c]ontinue/[r]etry/[a]bort` on failure
- **Safety blocklist** — 13 destructive patterns (rm -rf, dd, mkfs, ...) require explicit `YES` confirmation
- **Secret redaction** — privacy mode strips API keys, tokens, and high-entropy strings before sending to the model
- **Budget tracking** — daily and session token budgets; warn at 80%, hard-stop at 100%
- **Session memory** — context compressed with token-reducer between sessions; resumes on login
- **Telemetry sidebar** — tmux pane polls SQLite every 2s; shows cost, tokens, 7-day history
- **Audit log** — every command appended to `/var/log/agentic-shell/audit.log`
- **SSH bypass** — `SSH_ORIGINAL_COMMAND` always executed via `/bin/bash` (scp, rsync, git push all work)

---

## Quick Start (Docker)

```bash
# Build
docker build -t agentic-shell -f docker/Dockerfile .

# Run with Ollama backend (default)
docker run -it agentic-shell

# Run with OpenAI
docker run -it -e OPENAI_API_KEY=sk-... \
  --build-arg AGENTIC_BACKEND=openai \
  --build-arg AGENTIC_MODEL=gpt-4o-mini \
  agentic-shell

# Run with Anthropic
docker run -it -e ANTHROPIC_API_KEY=sk-ant-... \
  --build-arg AGENTIC_BACKEND=anthropic \
  --build-arg AGENTIC_MODEL=claude-3-5-haiku-20241022 \
  agentic-shell
```

---

## Install as Login Shell

```bash
# Clone and install
git clone <repo> agentic-shell
cd agentic-shell
bash install.sh
```

`install.sh` will:
1. Create a virtualenv at `~/.local/share/agentic-shell/venv`
2. Install all dependencies
3. Pre-cache tiktoken encodings
4. Write `/usr/local/bin/agentic-shell`
5. Register it in `/etc/shells`
6. Run `chsh` to set it as your login shell
7. Create `/var/log/agentic-shell/audit.log`

Log out and back in (or SSH again) — the first launch runs the setup wizard.

### Uninstall

```bash
bash uninstall.sh          # restores login shell to /bin/bash
bash uninstall.sh /bin/zsh # or another shell
```

---

## Configuration

Config is stored at `~/.config/agentic-shell/config.json` (permissions: 600).

Run the wizard again any time:

```bash
python3 -m shell.main  # re-runs wizard if setup_complete=false
```

Or edit inline with `/config` (or `Ctrl+X`) from the shell prompt.

### Config fields

| Field | Default | Description |
|-------|---------|-------------|
| `backend` | `ollama` | `ollama` / `openai` / `anthropic` |
| `model` | `llama3.1` | Model name for the selected backend |
| `api_base` | `http://localhost:11434` | Ollama server URL (ignored for cloud backends) |
| `routing_mode` | `auto` | `auto` (heuristic) or `prefix` (`>>` to invoke AI) |
| `daily_token_budget` | `null` | Stop LLM calls after N tokens/day |
| `session_token_budget` | `null` | Stop after N tokens this session |
| `privacy_mode` | `false` | Redact secrets before sending to model |

### API keys

- **Ollama** — no key needed
- **OpenAI** — set `OPENAI_API_KEY` env var (or stored in config.json in Phase 1)
- **Anthropic** — set `ANTHROPIC_API_KEY` env var

---

## Usage

```
/home/user ❯ ls -la          # → runs as bash
/home/user ❯ show disk usage  # → routed to AI
/home/user ❯ >> compress all png files in this dir  # >> prefix forces AI
```

### Keyboard shortcuts

| Key | Action |
|-----|--------|
| `Ctrl+B` | One-shot bash bypass (next command skips AI) |
| `Ctrl+T` | Toggle telemetry sidebar visibility |
| `Ctrl+X` | Open settings panel (`/config`) |
| `Ctrl+C` | Interrupt current command |
| `Ctrl+D` | Exit shell |

### Built-in commands

| Command | Description |
|---------|-------------|
| `/stats` | Token usage table for last 7 days |
| `shell stats --csv` | CSV output of stats |
| `/budget reset` | Clear the hard-stop flag after budget exhaustion |
| `/memory` | Show active session context; `[c]` to clear |
| `/config` | Open settings overlay (live edit + save) |

---

## Architecture

```
shell/main.py         SSH bypass, startup, config load, session resume
shell/loop.py         prompt_toolkit REPL, routing, budget, audit log
shell/router.py       NL vs bash heuristic classifier
shell/executor.py     ptyprocess execution, cd interception
shell/safety.py       destructive blocklist, entropy check, secret redaction
shell/planner.py      multi-step plan execution
shell/llm/
  base.py             LLMBackend ABC, LLMResponse, system prompt, JSON fallback
  ollama.py           Ollama NDJSON streaming
  openai.py           OpenAI SSE streaming
  anthropic.py        Anthropic SSE streaming (anthropic-version header required)
  pricing.json        Per-model token pricing table
shell/config/
  schema.py           ShellConfig dataclass + validation
  wizard.py           First-run interactive setup
  keyring.py          secretstorage keyring integration
shell/telemetry/
  db.py               SQLite WAL-mode, token_events + session_memory tables
  events.py           TokenEvent dataclass
  watch.py            Sidebar polling process (2s interval)
shell/memory/
  compressor.py       token-reducer compression, last-2-turns preservation
  store.py            session context load/save
shell/tui/
  layout.py           libtmux 80/20 split, sidebar toggle
  panel.py            Rich telemetry panel, settings overlay
```

---

## Running Tests

```bash
# Unit tests (no LLM, no subprocess, runs anywhere)
pytest tests/unit/ -v

# Integration tests (requires Docker)
docker build -t agentic-shell-test -f docker/Dockerfile .
docker run --rm agentic-shell-test pytest tests/integration/ -v
```

---

## Dependencies

All from `requirements.txt`:

```
prompt_toolkit   REPL and interactive input
pygments         Syntax highlighting
ptyprocess       PTY execution (vim, htop, etc. all work)
httpx            Async HTTP for LLM backends
httpx-sse        Server-sent events for OpenAI/Anthropic streaming
rich             Console output, panels, tables, syntax highlight
tiktoken==0.9.0  Token counting
libtmux>=0.55,<0.56  tmux session management
token-reducer    Context compression
secretstorage    Linux keyring (Phase 2+, Linux only)
```

---

## Security Notes

- The SSH bypass (`SSH_ORIGINAL_COMMAND`) is the first executable line of `main.py` — this is non-negotiable. Without it, `scp`, `rsync`, and `git push` over SSH hang.
- The system prompt explicitly marks file contents as **UNTRUSTED DATA** to mitigate prompt injection.
- Destructive commands (rm -rf, dd, mkfs, ...) always require typing `YES` literally.
- Audit log at `/var/log/agentic-shell/audit.log` records every command with user, timestamp, and exit code.
- Config file permissions are always set to `600` (owner read/write only).
