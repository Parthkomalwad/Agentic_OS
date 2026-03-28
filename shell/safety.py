"""Safety guard — runs every command through blocklist and entropy checks.

Applied on both the bash path and the agentic path before any execution.

Key responsibilities:
- DESTRUCTIVE_PATTERNS regex blocklist
- Shannon entropy check for secrets in privacy mode
- Confirmation flow (requires literal 'YES')
- Dry-run option for file-touching commands
- strip_secrets() for privacy mode
"""
from __future__ import annotations
import math
import re
import sys
from collections import Counter

DESTRUCTIVE_PATTERNS: list[str] = [
    r"\brm\s+(-[^\s]*f[^\s]*\s+|--force\s+)",
    r"\bdd\s+if=",
    r"\bchmod\s+777\b",
    r"\bkill\s+-9\b",
    r"\bcurl\b.*\|\s*(bash|sh)\b",
    r"\bwget\b.*\|\s*(bash|sh)\b",
    r"\bshutdown\b",
    r"\breboot\b",
    r"\bmkfs\b",
    r"\bfdisk\b",
    r"\bformat\b.*(/dev/)",
    r">\s*/dev/sd[a-z]",
    r"\biptables\s+-F\b",
]

SECRET_PATTERNS: list[str] = [
    r"AKIA[A-Z0-9]{16}",
    r"(?i)secret[_\s]?key[\s:=]+\S{20,}",
    r"eyJ[A-Za-z0-9\-_]{20,}\.[A-Za-z0-9\-_]+",
    r"-----BEGIN\s+(?:RSA\s+)?PRIVATE\s+KEY-----",
    r"(?i)bearer\s+[A-Za-z0-9\-_\.]{20,}",
    r"(?i)api[_\-]?key[\s:=]+[A-Za-z0-9\-_\.]{20,}",
    r'"type"\s*:\s*"service_account"',
]


def shannon_entropy(s: str) -> float:
    """Calculate Shannon entropy of a string."""
    counts = Counter(s)
    length = len(s)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def looks_like_secret(token: str) -> bool:
    """Return True if the token looks like a secret based on length and entropy."""
    return len(token) >= 20 and shannon_entropy(token) > 4.5


def is_destructive(command: str) -> bool:
    """Return True if command matches any destructive pattern."""
    for pattern in DESTRUCTIVE_PATTERNS:
        if re.search(pattern, command):
            return True
    return False


def confirm_destructive(command: str) -> bool:
    """Display warning and require 'YES' to proceed. Returns True if confirmed."""
    sys.stdout.write(f"\n! destructive operation detected\n  command: {command}\n  This operation may be destructive or irreversible.\n")
    sys.stdout.flush()
    try:
        answer = input("  type YES to confirm: ").strip()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer == "YES"


def strip_secrets(text: str) -> tuple[str, int]:
    """Redact secrets from text before sending to LLM.

    Returns:
        Tuple of (redacted_text, redaction_count).
    """
    redacted = 0
    for pattern in SECRET_PATTERNS:
        matches = re.findall(pattern, text)
        redacted += len(matches)
        text = re.sub(pattern, "[REDACTED]", text)
    # entropy-based catch for unknown secret formats
    tokens = text.split()
    result_tokens = []
    for token in tokens:
        if looks_like_secret(token):
            result_tokens.append("[REDACTED]")
            redacted += 1
        else:
            result_tokens.append(token)
    return " ".join(result_tokens), redacted
