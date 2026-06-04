"""MCP server exposing LaptopAI tools via Model Context Protocol."""

import asyncio
import json
import sys
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server
from mcp.server.models import InitializationOptions

import psutil
from pathlib import Path
import subprocess

from src.security.audit import get_audit
from src.security.permissions import load_guard


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

    return [types.TextContent(type="text", text=f"Unknown tool: {name}")]


async def main() -> None:
    async with mcp.server.stdio.stdio_server() as (read_stream, write_stream):
        init_opts = InitializationOptions(
            server_name="laptop-ai-mcp",
            server_version="1.0.0",
            capabilities=app.get_capabilities(
                notification_options=None,
                experimental_capabilities={},
            ),
        )
        await app.run(read_stream, write_stream, init_opts)


if __name__ == "__main__":
    asyncio.run(main())
