# Claude Code MCP Integration

How LaptopAI-Agent's tools are wired into Claude Code, how to operate the
connection day to day, and what was fixed to make it work.

## What's registered

Server name: `laptop-ai`, scope: **user** (available in every Claude Code
project on this machine). Config lives in `C:\Users\Sunil\.claude.json` under
`mcpServers.laptop-ai`:

```json
{
  "type": "stdio",
  "command": "python",
  "args": [
    "-c",
    "import sys; sys.path.insert(0, r'C:\\Gitrepos\\LaptopAI-Agent'); from src.mcp.server import main; import asyncio; asyncio.run(main())"
  ]
}
```

It imports `src.mcp.server` directly rather than going through `main.py mcp`,
which skips loading `typer`/`rich` at import time — those are only needed for
the interactive CLI, not the MCP tool surface.

## Tools exposed to Claude Code

| Tool | Description |
|---|---|
| `system_status` | CPU, memory, disk, battery snapshot |
| `list_gitrepos` | All repos in `C:\Gitrepos` with remote URLs |
| `git_status` | `git status --short` for a named repo |
| `top_processes` | Top 10 processes by CPU |
| `rag_query` | Semantic search over the ingested knowledge base |
| `aegis_analyze_paper` | Full AEGIS integrity check (plagiarism, AI detection, citations) on a paper file |
| `aegis_check_citations` | Fast citation-only check (hallucinated DOIs, predatory journals) |
| `aegis_compare_papers` | Self-plagiarism / similarity check between two paper files |

Every call still passes through `PermissionGuard` and writes to the SHA-256
chained audit log (`logs/audit.jsonl`), same as the LangGraph CLI agent.

## Operating it

```bash
# Check connection status
claude mcp get laptop-ai

# List every registered MCP server
claude mcp list

# Remove it
claude mcp remove laptop-ai -s user

# Re-add it (see JSON block above for the exact command)
claude mcp add laptop-ai -s user -- python -c "..."
```

Claude Code spawns the server as a subprocess and keeps it alive for the
session. **Code changes to `src/mcp/server.py` or its imports require a new
Claude Code session** (or removing/re-adding the server) to take effect —
the running subprocess won't hot-reload.

### Manual smoke test (no Claude Code needed)

```python
import asyncio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

async def run():
    params = StdioServerParameters(
        command="python",
        args=["-c", "import sys; sys.path.insert(0, r'C:\\Gitrepos\\LaptopAI-Agent'); "
                     "from src.mcp.server import main; import asyncio; asyncio.run(main())"],
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            print([t.name for t in (await session.list_tools()).tools])
            print((await session.call_tool("system_status", {})).content[0].text)

asyncio.run(run())
```

## Bugs fixed to make this work (2026-07-02)

1. **Relative-path assumptions broke outside the repo root.**
   `permissions.py::load_guard()` defaulted to `"config.yaml"` and
   `audit.py::AuditLogger`/`get_audit()` defaulted to `"./logs/audit.jsonl"`
   — both relative to the process's *current working directory*. That's
   fine for `python main.py mcp` run from inside the repo, but Claude Code
   launches the subprocess with its own cwd, so both lookups silently
   pointed at the wrong place. Fixed by anchoring both defaults to
   `Path(__file__).resolve().parent.parent.parent` (the repo root), so the
   server behaves the same no matter who launches it or from where.

2. **`get_capabilities()` crashed on startup.** `server.py` called
   `app.get_capabilities(notification_options=None, ...)`, but the installed
   `mcp` SDK (1.27.2) unconditionally reads `notification_options.tools_changed`
   — `None` doesn't have that attribute, so every connection attempt failed
   immediately with `AttributeError`. Fixed by passing a real
   `NotificationOptions()` instance (imported from
   `mcp.server.lowlevel.server`).

## Adding a new MCP tool

1. Add a `types.Tool(...)` entry to `list_tools()` in `src/mcp/server.py`
   with its `inputSchema`.
2. Add a matching `elif name == "...":` branch in `call_tool()` that does the
   work, logs to `audit.log(...)`, and returns `[types.TextContent(...)]`.
3. If the tool writes anywhere, call `guard.check_path(path, "write")` first
   so it respects `config.yaml`'s `allowed_paths`/`blocked_paths`.
4. Remove and re-add the `laptop-ai` server (or restart Claude Code) to pick
   up the change.
