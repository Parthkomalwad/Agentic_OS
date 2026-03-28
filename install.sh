#!/usr/bin/env bash
# install.sh — Install agentic-shell as the login shell for the current user.
#
# Usage: bash install.sh
# Must be run as the user who will use the shell (not root).
# Requires: python3.10+, pip, sudo (for chsh and audit log setup)

set -euo pipefail

INSTALL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_DIR="$HOME/.local/share/agentic-shell/venv"
WRAPPER="/usr/local/bin/agentic-shell"
AUDIT_LOG_DIR="/var/log/agentic-shell"
CURRENT_USER="$(whoami)"

echo "==> Installing agentic-shell for user: $CURRENT_USER"
echo "    Install dir: $INSTALL_DIR"

# --- 1. Create virtualenv ---
echo "==> Creating virtualenv at $VENV_DIR"
mkdir -p "$(dirname "$VENV_DIR")"
python3 -m venv "$VENV_DIR"

# --- 2. Install dependencies ---
echo "==> Installing Python dependencies"
"$VENV_DIR/bin/pip" install --quiet --upgrade pip
"$VENV_DIR/bin/pip" install --quiet -r "$INSTALL_DIR/requirements.txt"

# --- 3. Pre-cache tiktoken encodings (avoids first-run latency) ---
echo "==> Pre-caching tiktoken encodings"
"$VENV_DIR/bin/python" -c "import tiktoken; tiktoken.get_encoding('cl100k_base')" || true

# --- 4. Write the wrapper script ---
echo "==> Writing wrapper to $WRAPPER"
sudo tee "$WRAPPER" > /dev/null <<EOF
#!/usr/bin/env bash
# agentic-shell wrapper — activates venv and launches the Python shell
export PYTHONPATH="$INSTALL_DIR"
exec "$VENV_DIR/bin/python" -m shell.main "\$@"
EOF
sudo chmod +x "$WRAPPER"

# --- 5. Create audit log directory ---
echo "==> Creating audit log directory"
sudo mkdir -p "$AUDIT_LOG_DIR"
sudo chmod 1777 "$AUDIT_LOG_DIR"  # sticky bit — users can create their own log files
sudo touch "$AUDIT_LOG_DIR/audit.log"
sudo chmod 0666 "$AUDIT_LOG_DIR/audit.log"

# --- 6. Register as login shell ---
if ! grep -q "$WRAPPER" /etc/shells; then
    echo "==> Registering $WRAPPER in /etc/shells"
    echo "$WRAPPER" | sudo tee -a /etc/shells > /dev/null
fi

echo "==> Setting login shell to $WRAPPER for $CURRENT_USER"
chsh -s "$WRAPPER" "$CURRENT_USER"

echo ""
echo "✓ agentic-shell installed successfully."
echo "  Log out and back in (or SSH again) to start using it."
echo "  Config will be created on first launch."
