"""Telemetry sidebar process."""
from __future__ import annotations
import sys, time, os, subprocess
from datetime import datetime
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

console = Console(force_terminal=True, file=sys.stdout, width=40)
_start_time = datetime.now()

def _uptime():
    delta = datetime.now() - _start_time
    h, rem = divmod(int(delta.total_seconds()), 3600)
    m, s = divmod(rem, 60)
    return f"{h}h {m}m" if h else f"{m}m {s}s"

def _cpu_usage():
    try:
        with open("/proc/stat") as f:
            line = f.readline()
        fields = list(map(int, line.strip().split()[1:]))
        idle, total = fields[3], sum(fields)
        _cpu_usage._prev = getattr(_cpu_usage, "_prev", (idle, total))
        prev_idle, prev_total = _cpu_usage._prev
        _cpu_usage._prev = (idle, total)
        d_total = total - prev_total
        d_idle = idle - prev_idle
        return f"{100*(d_total-d_idle)/d_total:.0f}%" if d_total else "0%"
    except: return "n/a"

def _mem_usage():
    try:
        info = {}
        with open("/proc/meminfo") as f:
            for line in f:
                k, v = line.split(":")
                info[k.strip()] = int(v.strip().split()[0])
        total, avail = info["MemTotal"], info["MemAvailable"]
        used = total - avail
        return f"{used//1024}MB/{total//1024}MB ({100*used//total}%)"
    except: return "n/a"

def _last_command(db):
    try:
        row = db._conn.execute("SELECT command FROM token_events WHERE command IS NOT NULL ORDER BY id DESC LIMIT 1").fetchone()
        if row and row[0]:
            cmd = row[0]
            return cmd[:28]+"..." if len(cmd)>28 else cmd
        return "none"
    except: return "n/a"

def _current_dir():
    try:
        result = subprocess.run(["tmux","display-message","-t","0.0","-p","#{pane_current_path}"], capture_output=True, text=True)
        path = result.stdout.strip()
        if path:
            home = os.path.expanduser("~")
            if path.startswith(home): path = "~"+path[len(home):]
            return path[-26:] if len(path)>26 else path
    except: pass
    return os.getcwd()

def _get_config_model():
    try:
        import json
        from pathlib import Path
        cfg = json.loads((Path.home() / ".config/agentic-shell/config.json").read_text())
        return cfg.get("model", "unknown")
    except:
        return "unknown"


def _render_panel(db):
    today = db.get_today_stats()
    stats = db.get_stats(days=7)
    model = db.get_last_model()
    if model == "unknown":
        model = _get_config_model()
    content = Text()
    # Theme: soft purple accent (#875fd7 = color 98), dim labels, green for money
    content.append("Model  ", style="color(238)"); content.append(model+"\n", style="color(141) bold")
    content.append("Uptime ", style="color(238)"); content.append(_uptime()+"\n", style="color(153)")
    content.append("CWD    ", style="color(238)"); content.append(_current_dir()+"\n", style="color(153)")
    content.append("Last   ", style="color(238)"); content.append(_last_command(db)+"\n", style="color(250)")
    content.append("\nSystem\n", style="color(141) bold")
    content.append("  CPU  ", style="color(238)"); content.append(_cpu_usage()+"\n", style="color(114)")
    content.append("  RAM  ", style="color(238)"); content.append(_mem_usage()+"\n", style="color(114)")
    content.append("\nToday\n", style="color(141) bold")
    content.append("  Cost     ", style="color(238)"); content.append(f"${today['cost']:.4f}\n", style="color(114) bold")
    content.append("  Tokens   ", style="color(238)"); content.append(f"{today['tokens']:,}\n", style="color(153)")
    content.append("  Calls    ", style="color(238)"); content.append(f"{today['calls']}\n", style="color(250)")
    if today["calls"]>0:
        content.append("  Avg/call ", style="color(238)"); content.append(f"${today['cost']/today['calls']:.4f}\n", style="color(114)")
    content.append("\n")
    table = Table(show_header=True, header_style="color(141)", box=None, padding=(0,1))
    table.add_column("Date", style="color(238)", width=11)
    table.add_column("Calls", justify="right", width=5, style="color(250)")
    table.add_column("Cost", justify="right", width=8, style="color(114)")
    for row in stats[:7]:
        table.add_row(row["day"], str(row["calls"]), f"${row['cost']:.4f}" if row["cost"] else "$0.0000")
    from io import StringIO
    buf = StringIO()
    Console(file=buf, force_terminal=False, width=38).print(table)
    content.append(buf.getvalue())
    return Panel(content, title="[color(141) bold]✦ agentic[/color(141) bold]", border_style="color(55)")

def run():
    from shell.telemetry.db import Database
    db = Database()
    try:
        while True:
            console.clear()
            console.print(_render_panel(db))
            time.sleep(2)
    except KeyboardInterrupt: pass
    finally: db.close()

if __name__ == "__main__":
    run()
