"""MCP server exposing LaptopAI tools via Model Context Protocol."""

import asyncio
import json
import os
import sys
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from mcp.server.lowlevel.server import NotificationOptions
from mcp.server.models import InitializationOptions

import psutil
from pathlib import Path
import subprocess

from src.security.audit import get_audit
from src.security.permissions import load_guard

AEGIS_EXE = Path(r"C:\Gitrepos\aegis-integrity\.venv\Scripts\aegis.exe")
AEGIS_INDEX_DIR = Path(r"C:\Gitrepos\aegis-integrity\aegis_index")
AEGIS_REPORT_DIR = Path(r"C:\Gitrepos\aegis-integrity\aegis_reports")

def _run_aegis_sync(args: list[str], timeout: int = 300) -> str:
    env = os.environ.copy()
    env.setdefault("AEGIS_CITATION_EMAIL", "sunil.gentyala@ieee.org")
    result = subprocess.run(
        [str(AEGIS_EXE)] + args,
        capture_output=True, text=True, timeout=timeout,
        encoding="utf-8", errors="replace", env=env,
        stdin=subprocess.DEVNULL,
    )
    out = result.stdout.strip()
    if result.returncode != 0 and result.stderr.strip():
        out += "\nSTDERR:\n" + result.stderr.strip()
    return out or "(no output)"


app = Server("laptop-ai-mcp")
guard = load_guard()


@app.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="system_status",
            description="Get CPU, memory, disk, battery status",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="list_gitrepos",
            description="List all git repos in C:\\Gitrepos",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="git_status",
            description="Run git status on a named repo",
            inputSchema={
                "type": "object",
                "properties": {"repo_name": {"type": "string"}},
                "required": ["repo_name"],
            },
        ),
        types.Tool(
            name="top_processes",
            description="List top 10 processes by CPU",
            inputSchema={"type": "object", "properties": {}, "required": []},
        ),
        types.Tool(
            name="rag_query",
            description="Query local knowledge base",
            inputSchema={
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        ),
        types.Tool(
            name="aegis_analyze_paper",
            description=(
                "Analyze an academic paper (PDF/DOCX/TEX) with AEGIS v2.0 for plagiarism, "
                "AI-generated content, citation hallucinations, and stylometric issues. "
                "Use before IEEE paper submission or when checking paper integrity."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the paper file"},
                    "skip_ai": {"type": "boolean", "default": False, "description": "Skip GPT-2 AI detection"},
                    "skip_citations": {"type": "boolean", "default": False, "description": "Skip Crossref lookup"},
                },
                "required": ["file_path"],
            },
        ),
        types.Tool(
            name="aegis_check_citations",
            description="Verify citation integrity only (fast): hallucinated DOIs, predatory journals, missing DOIs.",
            inputSchema={
                "type": "object",
                "properties": {
                    "file_path": {"type": "string", "description": "Absolute path to the paper file"},
                },
                "required": ["file_path"],
            },
        ),
        types.Tool(
            name="aegis_compare_papers",
            description="Compare two paper files for self-plagiarism or similarity (e.g., conference draft vs journal extension).",
            inputSchema={
                "type": "object",
                "properties": {
                    "file1": {"type": "string"},
                    "file2": {"type": "string"},
                },
                "required": ["file1", "file2"],
            },
        ),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    audit = get_audit()

    if name == "system_status":
        disk = psutil.disk_usage("C:\\")
        mem = psutil.virtual_memory()
        battery = psutil.sensors_battery()
        result = {
            "cpu_percent": psutil.cpu_percent(interval=1),
            "memory_percent": mem.percent,
            "disk_free_gb": round(disk.free / 1e9, 2),
            "battery": battery.percent if battery else None,
        }
        audit.log("MCP_TOOL", "mcp_client", "system_status", "", json.dumps(result)[:200])
        return [types.TextContent(type="text", text=json.dumps(result, indent=2))]

    elif name == "list_gitrepos":
        repos = []
        for d in Path("C:\\Gitrepos").iterdir():
            if d.is_dir() and (d / ".git").exists():
                r = subprocess.run(["git", "-C", str(d), "remote", "get-url", "origin"],
                                   capture_output=True, text=True, timeout=5)
                repos.append({"name": d.name, "remote": r.stdout.strip() or "(no remote)"})
        audit.log("MCP_TOOL", "mcp_client", "list_gitrepos", "C:\\Gitrepos", f"{len(repos)} repos")
        return [types.TextContent(type="text", text=json.dumps(repos, indent=2))]

    elif name == "git_status":
        repo = arguments.get("repo_name", "")
        guard.check_path(f"C:\\Gitrepos\\{repo}", "read")
        p = Path("C:\\Gitrepos") / repo
        if not p.exists():
            return [types.TextContent(type="text", text=f"Repo '{repo}' not found")]
        r = subprocess.run(["git", "-C", str(p), "status", "--short"],
                           capture_output=True, text=True, timeout=15)
        out = r.stdout.strip() or "Clean"
        audit.log("MCP_TOOL", "mcp_client", "git_status", repo, out[:100])
        return [types.TextContent(type="text", text=out)]

    elif name == "top_processes":
        procs = sorted(
            [p.info for p in psutil.process_iter(["pid", "name", "cpu_percent"])
             if not isinstance(p.info.get("cpu_percent"), type(None))],
            key=lambda x: x.get("cpu_percent", 0), reverse=True
        )[:10]
        audit.log("MCP_TOOL", "mcp_client", "top_processes", "", "ok")
        return [types.TextContent(type="text", text=json.dumps(procs, indent=2))]

    elif name == "rag_query":
        from src.rag.knowledge_base import LaptopKnowledgeBase
        kb = LaptopKnowledgeBase()
        hits = kb.query(arguments.get("question", ""), top_k=5)
        text = "\n\n---\n".join(
            f"[{h['score']}] {h['source']}\n{h['text'][:300]}" for h in hits
        ) or "No results"
        audit.log("MCP_TOOL", "mcp_client", "rag_query",
                  arguments.get("question", "")[:100], f"{len(hits)} hits")
        return [types.TextContent(type="text", text=text)]

    elif name == "aegis_analyze_paper":
        file_path = arguments["file_path"]
        stem = Path(file_path).stem
        AEGIS_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        json_out = str(AEGIS_REPORT_DIR / f"{stem}_report.json")
        html_out = str(AEGIS_REPORT_DIR / f"{stem}_report.html")
        args = ["analyze", file_path, "--output", json_out, "--html", html_out,
                "--index-dir", str(AEGIS_INDEX_DIR)]
        if arguments.get("skip_ai"):
            args.append("--no-ai")
        if arguments.get("skip_citations"):
            args.append("--no-citations")
        output = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_aegis_sync(args, timeout=300)
        )
        audit.log("MCP_TOOL", "mcp_client", "aegis_analyze", file_path[:100], output[:200])
        return [types.TextContent(type="text", text=output)]

    elif name == "aegis_check_citations":
        file_path = arguments["file_path"]
        stem = Path(file_path).stem
        AEGIS_REPORT_DIR.mkdir(parents=True, exist_ok=True)
        json_out = str(AEGIS_REPORT_DIR / f"{stem}_citations.json")
        args = ["analyze", file_path,
                "--no-ai", "--no-semantic", "--no-stylometric", "--no-self-plagiarism",
                "--output", json_out]
        output = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_aegis_sync(args, timeout=120)
        )
        audit.log("MCP_TOOL", "mcp_client", "aegis_citations", file_path[:100], output[:200])
        return [types.TextContent(type="text", text=output)]

    elif name == "aegis_compare_papers":
        args = ["compare", arguments["file1"], arguments["file2"]]
        output = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _run_aegis_sync(args, timeout=300)
        )
        audit.log("MCP_TOOL", "mcp_client", "aegis_compare",
                  f"{arguments['file1'][:50]} vs {arguments['file2'][:50]}", output[:200])
        return [types.TextContent(type="text", text=output)]

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        init_opts = InitializationOptions(
            server_name="laptop-ai-mcp",
            server_version="1.1.0",
            capabilities=app.get_capabilities(
                notification_options=NotificationOptions(),
                experimental_capabilities={},
            ),
        )
        await app.run(read_stream, write_stream, init_opts)


if __name__ == "__main__":
    asyncio.run(main())
