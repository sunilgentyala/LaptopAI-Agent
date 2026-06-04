"""System tools exposed to the LaptopAI agent."""

import subprocess
import platform
from datetime import datetime
from pathlib import Path
from typing import Any

import psutil
from langchain_core.tools import tool

from src.security.audit import get_audit
from src.security.permissions import PermissionGuard


_guard: PermissionGuard | None = None


def set_guard(g: PermissionGuard) -> None:
    global _guard
    _guard = g


def _audit(action: str, target: str, result: str, meta: dict | None = None) -> None:
    get_audit().log("TOOL_CALL", "LaptopAI-Agent", action, target, result, meta)


@tool
def get_system_status() -> dict[str, Any]:
    """Return CPU, memory, disk, and battery status of this laptop."""
    disk = psutil.disk_usage("C:\\")
    mem = psutil.virtual_memory()
    cpu = psutil.cpu_percent(interval=1)
    battery = psutil.sensors_battery()
    result = {
        "cpu_percent": cpu,
        "memory_percent": mem.percent,
        "memory_available_gb": round(mem.available / 1e9, 2),
        "disk_used_percent": disk.percent,
        "disk_free_gb": round(disk.free / 1e9, 2),
        "platform": platform.platform(),
        "boot_time": datetime.fromtimestamp(psutil.boot_time()).isoformat(),
        "battery_percent": battery.percent if battery else None,
        "plugged_in": battery.power_plugged if battery else None,
    }
    _audit("get_system_status", "localhost", "ok")
    return result


@tool
def list_gitrepos(base_path: str = "C:\\Gitrepos") -> list[dict[str, str]]:
    """List all git repositories in C:\\Gitrepos with their remote URLs."""
    repos = []
    try:
        for d in Path(base_path).iterdir():
            if d.is_dir() and (d / ".git").exists():
                try:
                    r = subprocess.run(
                        ["git", "-C", str(d), "remote", "get-url", "origin"],
                        capture_output=True, text=True, timeout=5
                    )
                    remote = r.stdout.strip() or "(no remote)"
                    b = subprocess.run(
                        ["git", "-C", str(d), "branch", "--show-current"],
                        capture_output=True, text=True, timeout=5
                    )
                    repos.append({
                        "name": d.name,
                        "path": str(d),
                        "remote": remote,
                        "branch": b.stdout.strip() or "?",
                    })
                except Exception as e:
                    repos.append({"name": d.name, "path": str(d), "remote": f"error: {e}", "branch": "?"})
    except Exception as e:
        return [{"error": str(e)}]
    _audit("list_gitrepos", base_path, f"{len(repos)} repos")
    return repos


@tool
def run_git_status(repo_name: str) -> str:
    """Run git status in a named repo under C:\\Gitrepos."""
    repo_path = Path("C:\\Gitrepos") / repo_name
    if _guard:
        _guard.check_path(str(repo_path), "read")
    if not repo_path.exists():
        return f"Repo '{repo_name}' not found in C:\\Gitrepos"
    r = subprocess.run(
        ["git", "-C", str(repo_path), "status", "--short"],
        capture_output=True, text=True, timeout=15
    )
    result = r.stdout.strip() or "Clean working tree"
    _audit("run_git_status", str(repo_path), result[:200])
    return result


@tool
def list_running_processes(top_n: int = 20) -> list[dict[str, Any]]:
    """List top N processes by CPU usage."""
    procs = []
    for p in psutil.process_iter(["pid", "name", "cpu_percent", "memory_percent"]):
        try:
            procs.append(p.info)
        except psutil.NoSuchProcess:
            pass
    procs.sort(key=lambda x: x.get("cpu_percent", 0), reverse=True)
    result = procs[:top_n]
    _audit("list_running_processes", "localhost", f"{len(result)} procs")
    return result


@tool
def read_file(file_path: str) -> str:
    """Read a text file from an allowed path."""
    if _guard:
        _guard.check_path(file_path, "read")
    p = Path(file_path)
    if not p.exists():
        return f"File not found: {file_path}"
    if p.stat().st_size > 2 * 1024 * 1024:
        return "File too large to read inline (>2MB). Use RAG query instead."
    content = p.read_text(encoding="utf-8", errors="ignore")
    _audit("read_file", file_path, f"{len(content)} chars")
    return content


@tool
def write_file(file_path: str, content: str) -> str:
    """Write content to a file in an allowed path."""
    if _guard:
        _guard.check_path(file_path, "write")
        _guard.check_file_size(len(content.encode()))
    Path(file_path).parent.mkdir(parents=True, exist_ok=True)
    Path(file_path).write_text(content, encoding="utf-8")
    _audit("write_file", file_path, f"{len(content)} chars written")
    return f"Written {len(content)} chars to {file_path}"


@tool
def query_knowledge_base(question: str, top_k: int = 5) -> str:
    """Search the local RAG knowledge base for relevant context."""
    from src.rag.knowledge_base import LaptopKnowledgeBase
    kb = LaptopKnowledgeBase()
    hits = kb.query(question, top_k=top_k)
    if not hits:
        return "No relevant documents found."
    lines = []
    for h in hits:
        lines.append(f"[score={h['score']}] ({h['source']})\n{h['text'][:300]}")
    _audit("query_knowledge_base", question[:100], f"{len(hits)} hits")
    return "\n\n---\n\n".join(lines)


ALL_TOOLS = [
    get_system_status,
    list_gitrepos,
    run_git_status,
    list_running_processes,
    read_file,
    write_file,
    query_knowledge_base,
]
