#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# If run via sudo, use the real user's home — not root's
if [ -n "${SUDO_USER:-}" ]; then
    REAL_USER="$SUDO_USER"
    REAL_HOME="$(getent passwd "$SUDO_USER" | cut -d: -f6)"
else
    REAL_USER="$(whoami)"
    REAL_HOME="$HOME"
fi

VENV_DIR="$REAL_HOME/.local/share/agentic-shell/venv"
WRAPPER="/usr/local/bin/agentic-shell"
AUDIT_LOG_DIR="/var/log/agentic-shell"

echo "==> Installing agentic-shell for user: $REAL_USER"
echo "    Install dir: $INSTALL_DIR"
echo "    Venv dir:    $VENV_DIR"

echo "==> Creating virtualenv at $VENV_DIR"
sudo -u "$REAL_USER" mkdir -p "$(dirname "$VENV_DIR")"
sudo -u "$REAL_USER" python3 -m venv "$VENV_DIR"

echo "==> Installing Python dependencies"
sudo -u "$REAL_USER" "$VENV_DIR/bin/pip" install --quiet --upgrade pip
sudo -u "$REAL_USER" "$VENV_DIR/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

echo "==> Pre-caching tiktoken encodings"
sudo -u "$REAL_USER" "$VENV_DIR/bin/python" -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" || true

echo "==> Writing wrapper to $WRAPPER"
sudo tee "$WRAPPER" > /dev/null <<EOF
#!/usr/bin/env bash
export PYTHONPATH="$INSTALL_DIR"
export TERM=xterm-256color
export PROMPT_TOOLKIT_NO_CPR=1
export AGENTIC_PYTHON="$VENV_DIR/bin/python"
PYTHON="$VENV_DIR/bin/python"
SESSION="agentic-shell-\${USER}"
STAMP_FILE="\$HOME/.local/share/agentic-shell/install_stamp"
CURRENT_STAMP="$INSTALL_DIR:$VENV_DIR"

if command -v tmux &>/dev/null && [ -z "\$TMUX" ]; then
    if tmux has-session -t "\$SESSION" 2>/dev/null; then
        # Session exists — just reattach (second SSH connection, don't kill it)
        exec tmux attach-session -t "\$SESSION"
    fi

    # No existing session — create fresh with 2 panes
    echo "\$CURRENT_STAMP" > "\$STAMP_FILE"
    tmux new-session -d -s "\$SESSION" -x 220 -y 50
    tmux split-window -h -t "\$SESSION":0.0 -l 48
    tmux swap-pane -s "\$SESSION":0.0 -t "\$SESSION":0.1

    # Telemetry sidebar (right pane)
    tmux send-keys -t "\$SESSION":0.1 "trap '' INT; clear; while true; do PYTHONPATH=$INSTALL_DIR PROMPT_TOOLKIT_NO_CPR=1 $VENV_DIR/bin/python -m shell.telemetry.watch; sleep 2; done" Enter

    # Main shell (left pane)
    tmux send-keys -t "\$SESSION":0.0 "trap '' INT; EXIT_FLAG=\$HOME/.local/share/agentic-shell/exit_requested; while true; do rm -f \"\$EXIT_FLAG\"; clear; PYTHONPATH=$INSTALL_DIR PROMPT_TOOLKIT_NO_CPR=1 NO_TMUX=1 $VENV_DIR/bin/python -m shell.main; if [ -f \"\$EXIT_FLAG\" ]; then rm -f \"\$EXIT_FLAG\"; break; fi; echo '[shell exited — restarting in 2s]'; sleep 2; done" Enter

    tmux select-pane -t "\$SESSION":0.0
    exec tmux attach-session -t "\$SESSION"
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

echo "==> Setting login shell to $WRAPPER for $REAL_USER"
sudo chsh -s "$WRAPPER" "$REAL_USER"

echo ""
echo "✓ agentic-shell installed successfully for $REAL_USER."
echo "  Venv: $VENV_DIR"
echo "  Run: agentic-shell"
