"""LaptopAI - Personal Agentic AI for Laptop Management.

Usage:
  python main.py chat                    - Interactive chat
  python main.py status                  - System status report
  python main.py repos                   - List all git repos
  python main.py ingest <path>           - Ingest documents into RAG
  python main.py verify-audit            - Verify audit log integrity
  python main.py mcp                     - Start MCP server (stdio)
"""

import sys
import yaml
import typer
from rich.console import Console
from rich.table import Table
from pathlib import Path

from src.security.audit import get_audit
from src.security.permissions import load_guard
from src.agent.tools import set_guard

app = typer.Typer(help="LaptopAI - Personal Agentic AI")
console = Console()


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@app.command()
def chat(query: str = typer.Option(None, "--query", "-q", help="Single query (non-interactive)")):
    """Interactive chat with LaptopAI agent."""
    cfg = load_config()
    guard = load_guard()
    set_guard(guard)

    from src.agent.graph import run_agent

    if query:
        console.print(f"\n[bold cyan]You:[/] {query}")
        result = run_agent(query, cfg)
        console.print(f"\n[bold green]LaptopAI:[/] {result}\n")
        return

    console.print("[bold]LaptopAI Agent[/] - type 'exit' to quit\n")
    while True:
        try:
            user_input = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            break
        if user_input.lower() in ("exit", "quit", "q"):
            break
        if not user_input:
            continue
        result = run_agent(user_input, cfg)
        console.print(f"\n[bold green]LaptopAI:[/] {result}\n")


@app.command()
def status():
    """Print current system status."""
    import psutil, platform
    from datetime import datetime

    disk = psutil.disk_usage("C:\\")
    mem = psutil.virtual_memory()
    battery = psutil.sensors_battery()

    table = Table(title="System Status", show_header=True)
    table.add_column("Metric", style="cyan")
    table.add_column("Value", style="green")

    table.add_row("CPU", f"{psutil.cpu_percent(interval=1):.1f}%")
    table.add_row("Memory", f"{mem.percent:.1f}% ({mem.available/1e9:.1f} GB free)")
    table.add_row("Disk C:", f"{disk.percent:.1f}% ({disk.free/1e9:.1f} GB free)")
    if battery:
        table.add_row("Battery", f"{battery.percent:.0f}% {'(charging)' if battery.power_plugged else ''}")
    table.add_row("Platform", platform.platform())
    table.add_row("Boot time", datetime.fromtimestamp(psutil.boot_time()).strftime("%Y-%m-%d %H:%M"))

    console.print(table)


@app.command()
def repos():
    """List all git repos in C:\\Gitrepos."""
    import subprocess

    table = Table(title="Git Repositories in C:\\Gitrepos")
    table.add_column("Name", style="cyan")
    table.add_column("Branch", style="yellow")
    table.add_column("Remote", style="green")

    base = Path("C:\\Gitrepos")
    for d in sorted(base.iterdir()):
        if d.is_dir() and (d / ".git").exists():
            r = subprocess.run(["git", "-C", str(d), "remote", "get-url", "origin"],
                               capture_output=True, text=True, timeout=5)
            b = subprocess.run(["git", "-C", str(d), "branch", "--show-current"],
                               capture_output=True, text=True, timeout=5)
            table.add_row(d.name, b.stdout.strip() or "?", r.stdout.strip() or "(no remote)")
    console.print(table)


@app.command()
def ingest(path: str = typer.Argument(..., help="File or directory to ingest")):
    """Ingest documents into the RAG knowledge base."""
    from src.rag.knowledge_base import LaptopKnowledgeBase
    cfg = load_config()
    rag_cfg = cfg.get("rag", {})
    kb = LaptopKnowledgeBase(
        chroma_path=rag_cfg.get("chroma_path", "./data/chroma_db"),
        collection_name=rag_cfg.get("collection_name", "laptop_knowledge"),
        chunk_size=rag_cfg.get("chunk_size", 512),
    )
    p = Path(path)
    if p.is_file():
        n = kb.ingest_file(str(p))
        console.print(f"[green]Ingested {n} chunks from {p.name}[/]")
    elif p.is_dir():
        results = kb.ingest_directory(str(p))
        total = sum(v for v in results.values() if v > 0)
        console.print(f"[green]Ingested {total} total chunks from {len(results)} files[/]")
    else:
        console.print(f"[red]Path not found: {path}[/]")
    console.print(f"Knowledge base now has {kb.count()} total chunks.")


@app.command()
def verify_audit():
    """Verify integrity of the audit log chain."""
    audit = get_audit()
    valid, msg = audit.verify_chain()
    if valid:
        console.print(f"[green]Audit log intact:[/] {msg}")
    else:
        console.print(f"[red]AUDIT LOG COMPROMISED:[/] {msg}")


@app.command()
def mcp():
    """Start the MCP server (for Claude Desktop / Claude Code integration)."""
    import asyncio
    from src.mcp.server import main as mcp_main
    console.print("[bold]Starting LaptopAI MCP Server...[/]")
    asyncio.run(mcp_main())


if __name__ == "__main__":
    app()
