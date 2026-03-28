"""Telemetry sidebar process.

Run as: python -m shell.telemetry.watch
Polls sessions.db every 2 seconds and re-renders the Rich panel in the tmux sidebar pane.
Uses Console(force_terminal=True) so Rich renders ANSI in the pane.
"""
from __future__ import annotations

import sys
import time
import os
import subprocess
from datetime import datetime

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console(force_terminal=True, file=sys.stdout)

_start_time = datetime.now()


def _uptime() -> str:
    delta = datetime.now() - _start_time
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    return f"{m}m {s}s"


def _cpu_usage() -> str:
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        fields = list(map(int, line.strip().split()[1:]))
        idle = fields[3]
        total = sum(fields)
        _cpu_usage._prev = getattr(_cpu_usage, "_prev", (idle, total))
        prev_idle, prev_total = _cpu_usage._prev
        _cpu_usage._prev = (idle, total)
        d_total = total - prev_total
        d_idle = idle - prev_idle
        if d_total == 0:
            return "0%"
        return f"{100 * (d_total - d_idle) / d_total:.0f}%"
    except Exception:
        return "n/a"


def _mem_usage() -> str:
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                info[k.strip()] = int(v.strip().split()[0])
        total = info["MemTotal"]
        available = info["MemAvailable"]
        used = total - available
        pct = 100 * used / total
        return f"{used // 1024}MB / {total // 1024}MB ({pct:.0f}%)"
    except Exception:
        return "n/a"


def _last_command(db) -> str:
    try:
        row = db._conn.execute(
            "SELECT command FROM token_events WHERE command IS NOT NULL ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row and row[0]:
            cmd = row[0]
            return cmd[:30] + "..." if len(cmd) > 30 else cmd
        return "none"
    except Exception:
        return "n/a"


def _current_dir() -> str:
    try:
        result = subprocess.run(
            ["tmux", "display-message", "-p", "#{pane_current_path}"],
            capture_output=True, text=True
        )
        path = result.stdout.strip()
        if path:
            home = os.path.expanduser("~")
            if path.startswith(home):
                path = "~" + path[len(home):]
            return path[-28:] if len(path) > 28 else path
    except Exception:
        pass
    return os.getcwd()


def _render_panel(db) -> Panel:
    today = db.get_today_stats()
    stats = db.get_stats(days=7)
    model = db.get_last_model()

    content = Text()

    # Model
    content.append("Model  ", style="dim")
    content.append(model + "\n", style="bold magenta")

    # Uptime
    content.append("Uptime ", style="dim")
    content.append(_uptime() + "\n", style="cyan")

    # Current dir
    content.append("CWD    ", style="dim")
    content.append(_current_dir() + "\n", style="yellow")

    # Last command
    content.append("Last   ", style="dim")
    content.append(_last_command(db) + "\n", style="white")

    content.append("\n")

    # System
    content.append("System\n", style="bold cyan")
    content.append("  CPU  ", style="dim")
    content.append(_cpu_usage() + "\n", style="green")
    content.append("  RAM  ", style="dim")
    content.append(_mem_usage() + "\n", style="green")

    content.append("\n")

    # Today
    content.append("Today\n", style="bold cyan")
    content.append("  Cost     ", style="dim")
    content.append(f"${today['cost']:.4f}\n", style="bold green")
    content.append("  Tokens   ", style="dim")
    content.append(f"{today['tokens']:,}\n", style="bold yellow")
    content.append("  Calls    ", style="dim")
    content.append(f"{today['calls']}\n", style="bold white")
    if today["calls"] > 0:
        avg = today["cost"] / today["calls"]
        content.append("  Avg/call ", style="dim")
        content.append(f"${avg:.4f}\n", style="white")

    content.append("\n")

    # 7-day history
    table = Table(show_header=True, header_style="bold cyan", box=None, padding=(0, 1))
    table.add_column("Date", style="dim", width=11)
    table.add_column("Calls", justify="right", width=5)
    table.add_column("Cost", justify="right", width=8)
    for row in stats[:7]:
        table.add_row(
            row["day"],
            str(row["calls"]),
            f"${row['cost']:.4f}" if row["cost"] else "$0.0000",
        )

    from io import StringIO
    buf = StringIO()
    tmp = Console(file=buf, force_terminal=False, width=38)
    tmp.print(table)
    content.append(buf.getvalue())

    return Panel(
        content,
        title="[bold cyan]token usage[/bold cyan]",
        border_style="cyan",
    )


def run() -> None:
    """Main loop for the telemetry sidebar process."""
    from shell.telemetry.db import Database

    db = Database()
    try:
        while True:
            console.clear()
            console.print(_render_panel(db))
            time.sleep(2)
    except KeyboardInterrupt:
        pass
    finally:
        db.close()


if __name__ == "__main__":
    run()
