#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/.local/share/agentic-shell/venv"
WRAPPER="/usr/local/bin/agentic-shell"
AUDIT_LOG_DIR="/var/log/agentic-shell"
CURRENT_USER="$(whoami)"

echo "==> Installing agentic-shell for user: $CURRENT_USER"
echo "    Install dir: $INSTALL_DIR"

echo "==> Creating virtualenv at $VENV_DIR"
mkdir -p "$(dirname "$VENV_DIR")"
python3 -m venv "$VENV_DIR"

echo "==> Installing Python dependencies"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

echo "==> Pre-caching tiktoken encodings"
"$VENV_DIR/bin/python" -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" || true

echo "==> Writing wrapper to $WRAPPER"
sudo tee "$WRAPPER" > /dev/null <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$INSTALL_DIR"
export TERM=xterm-256color
export PROMPT_TOOLKIT_NO_CPR=1
PYTHON="$VENV_DIR/bin/python"
SESSION="agentic-shell-\${USER}"
STAMP_FILE="\$HOME/.local/share/agentic-shell/install_stamp"
CURRENT_STAMP="$INSTALL_DIR:$VENV_DIR"

if command -v tmux &>/dev/null && [ -z "\$TMUX" ]; then
    # Kill existing session if install dir has changed
    SAVED_STAMP="\$(cat "\$STAMP_FILE" 2>/dev/null || echo '')"
    if tmux has-session -t "\$SESSION" 2>/dev/null && [ "\$SAVED_STAMP" != "\$CURRENT_STAMP" ]; then
        tmux kill-session -t "\$SESSION" 2>/dev/null || true
    fi
    echo "\$CURRENT_STAMP" > "\$STAMP_FILE"

    if tmux has-session -t "\$SESSION" 2>/dev/null; then
        exec tmux attach-session -t "\$SESSION"
    else
        # Create session with auto-restart loop for the shell pane
        tmux new-session -d -s "\$SESSION" -x 220 -y 50
        tmux split-window -h -t "\$SESSION":0.0 -l 45

        # Telemetry sidebar (pane 1) — restart on crash
        tmux send-keys -t "\$SESSION":0.1 "while true; do PYTHONPATH=$INSTALL_DIR PROMPT_TOOLKIT_NO_CPR=1 $VENV_DIR/bin/python -m shell.telemetry.watch; sleep 2; done" Enter

        # Main shell (pane 0) — restart on crash, with 1s delay to show error
        tmux send-keys -t "\$SESSION":0.0 "while true; do PYTHONPATH=$INSTALL_DIR PROMPT_TOOLKIT_NO_CPR=1 NO_TMUX=1 $VENV_DIR/bin/python -m shell.main; echo '[shell exited — restarting in 2s]'; sleep 2; done" Enter

        tmux select-pane -t "\$SESSION":0.0
        exec tmux attach-session -t "\$SESSION"
    fi
else
    exec "\$PYTHON" -m shell.main
fi
EOF
sudo chmod +x "$WRAPPER"

echo "==> Creating audit log directory"
sudo mkdir -p "$AUDIT_LOG_DIR"
sudo chmod 1777 "$AUDIT_LOG_DIR"
sudo touch "$AUDIT_LOG_DIR/audit.log"
sudo chmod 0666 "$AUDIT_LOG_DIR/audit.log"

if ! grep -q "$WRAPPER" /etc/shells; then
    echo "==> Registering $WRAPPER in /etc/shells"
    echo "$WRAPPER" | sudo tee -a /etc/shells > /dev/null
fi

echo "==> Setting login shell to $WRAPPER for $CURRENT_USER"
chsh -s "$WRAPPER" "$CURRENT_USER"

echo ""
echo "✓ agentic-shell installed successfully."
