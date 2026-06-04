# LaptopAI-Agent

Personal Agentic AI for Laptop Management — built by Sunil Gentyala (sunil.gentyala@ieee.org, HCLTech).

## Architecture

```
LangGraph Agent (reasoning + planning)
    ↓
MCP Server (tool orchestration + permission enforcement)
    ↓
ChromaDB RAG (local knowledge base — system logs, configs, docs)
    ↓
Ollama / Local LLM (privacy-first, no API keys required)
    ↓
System Tools (git repos, file I/O, process monitor, disk status)
```

## Security Model

- **Permission Guard** — path allowlist/blocklist, blocked commands require manual approval
- **Audit Log** — SHA-256 chained, append-only JSONL at `logs/audit.jsonl`
- **Tamper Detection** — `python main.py verify-audit` verifies full chain integrity
- **Zero external calls** — all LLM inference runs locally via Ollama

## Quick Start

```bash
# 1. Install Ollama and pull the agent model
ollama pull qwen2.5-coder:7b

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Interactive chat
python main.py chat

# 4. System status dashboard
python main.py status

# 5. List all git repos
python main.py repos

# 6. Ingest documents into RAG
python main.py ingest C:\Gitrepos\LaptopAI-Agent\docs

# 7. Start MCP server (for Claude Desktop / Claude Code)
python main.py mcp

# 8. Verify audit log integrity
python main.py verify-audit
```

## Claude Desktop / Claude Code Integration (MCP)

Add to `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "laptop-ai": {
      "command": "python",
      "args": ["C:\\Gitrepos\\LaptopAI-Agent\\main.py", "mcp"],
      "cwd": "C:\\Gitrepos\\LaptopAI-Agent"
    }
  }
}
```

## Tools Available to Agent

| Tool | Description |
|------|-------------|
| `get_system_status` | CPU, memory, disk, battery |
| `list_gitrepos` | All repos in C:\Gitrepos |
| `run_git_status` | git status for a named repo |
| `list_running_processes` | Top N by CPU usage |
| `read_file` | Read file from allowed path |
| `write_file` | Write file to allowed path |
| `query_knowledge_base` | RAG query over ingested docs |

## Project Structure

```
LaptopAI-Agent/
├── main.py              # CLI entry point
├── config.yaml          # All configuration
├── requirements.txt
├── src/
│   ├── agent/
│   │   ├── graph.py     # LangGraph workflow
│   │   └── tools.py     # LangChain tools
│   ├── mcp/
│   │   └── server.py    # MCP server (stdio)
│   ├── rag/
│   │   └── knowledge_base.py  # ChromaDB RAG
│   └── security/
│       ├── audit.py     # Chained audit log
│       └── permissions.py     # Permission guard
├── data/chroma_db/      # Local vector store (gitignored)
└── logs/audit.jsonl     # Audit trail (gitignored)
```

## Referenced Research

- LangGraph: github.com/langchain-ai/langgraph
- MCP Servers: github.com/modelcontextprotocol/servers
- RAGFlow: github.com/infiniflow/ragflow
- Agent-S: github.com/simular-ai/Agent-S
- AIOS: github.com/agiresearch/AIOS

## License

Apache-2.0 — Sunil Gentyala, 2026
