<div align="center">

# 🤖 LaptopAI-Agent

### Personal Agentic AI for Laptop Management — Private, Secure, Offline-First

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://www.python.org/)
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-FF6B35?style=for-the-badge&logo=langchain&logoColor=white)](https://github.com/langchain-ai/langgraph)
[![ChromaDB](https://img.shields.io/badge/ChromaDB-0.5+-FF4785?style=for-the-badge)](https://www.trychroma.com/)
[![Ollama](https://img.shields.io/badge/Ollama-Local_LLM-000000?style=for-the-badge)](https://ollama.ai/)
[![MCP](https://img.shields.io/badge/MCP-1.0+-6366F1?style=for-the-badge)](https://modelcontextprotocol.io/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache_2.0-green?style=for-the-badge)](LICENSE)

**Zero API keys. Zero cloud calls. Full system control — with a cryptographic audit trail.**

*Built by [Sunil Gentyala](https://github.com/sunilgentyala) · IEEE Senior Member · HCL America Inc.*

</div>

---

## 🧠 What Is This?

LaptopAI-Agent is a **fully local, privacy-first autonomous AI agent** that manages and reasons about your laptop. It combines:

- A **LangGraph reasoning loop** — multi-step planning with tool use, up to 10 agentic iterations per query
- A **local LLM via Ollama** — default `qwen2.5-coder:7b` for high tool-calling accuracy, no internet required
- A **ChromaDB RAG layer** — ingest your git repos, configs, logs, and docs; retrieve relevant context at inference time
- An **MCP server** — expose all tools to Claude Desktop / Claude Code over stdio
- A **SHA-256 chained audit log** — append-only, tamper-evident JSONL record of every agent action

Ask it: *"Which of my repos have uncommitted changes?"* or *"My disk is 87% full — what's taking space in C:\Gitrepos?"* and it will reason, call tools, and respond — entirely on your machine.

---

## ⚡ Quick Start

```bash
# 1. Pull the recommended local model
ollama pull qwen2.5-coder:7b

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Start chatting
python main.py chat

# 4. Check system health dashboard
python main.py status

# 5. List all git repos + remote URLs + branch
python main.py repos

# 6. Ingest documents into local RAG
python main.py ingest C:\Gitrepos\LaptopAI-Agent\docs

# 7. Start MCP server (for Claude Desktop / Claude Code)
python main.py mcp

# 8. Verify audit log chain integrity
python main.py verify-audit
```

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                        User / MCP Client                            │
│                    (CLI chat or Claude Desktop)                     │
└───────────────────────────────┬─────────────────────────────────────┘
                                │ query
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    LangGraph Agent Loop                             │
│                                                                     │
│   ┌──────────┐   tool_calls?   ┌──────────────┐                    │
│   │  agent   │ ──────────────► │  ToolNode    │                    │
│   │  (LLM)   │ ◄────────────── │ (LangChain)  │                    │
│   └──────────┘   tool results  └──────────────┘                    │
│        │                              │                             │
│   max 10 iterations            Permission Guard                     │
│        │                       + Audit Log                          │
│        ▼                                                            │
│   Final response                                                    │
└───────────────────────────────┬─────────────────────────────────────┘
                                │
          ┌─────────────────────┼────────────────────────┐
          ▼                     ▼                        ▼
┌──────────────────┐  ┌─────────────────────┐  ┌────────────────────┐
│   Ollama (LLM)   │  │  ChromaDB (RAG)     │  │  System Tools      │
│                  │  │                     │  │                    │
│ qwen2.5-coder:7b │  │ all-MiniLM-L6-v2   │  │ psutil, git,       │
│ localhost:11434  │  │ cosine similarity   │  │ pathlib, subprocess│
│ temperature=0.1  │  │ 512-token chunks    │  │                    │
│ NO API KEY       │  │ 64-token overlap    │  │ Permission Guard   │
└──────────────────┘  └─────────────────────┘  └────────────────────┘
```

---

## 🛠️ Available Tools

Every tool call is intercepted by the **Permission Guard** and written to the **chained audit log**.

| Tool | Description | Permission |
|---|---|---|
| `get_system_status` | CPU %, memory %, disk free GB, battery %, boot time, platform | Read |
| `list_gitrepos` | All repos under `C:\Gitrepos` with remote URL and current branch | Read |
| `run_git_status` | `git status --short` for a named repo | Read (path check) |
| `list_running_processes` | Top N processes ranked by CPU usage via psutil | Read |
| `read_file` | Read any text file ≤ 2 MB from an allowed path | Read (allowlist) |
| `write_file` | Write content to a file in an allowed path | Write (allowlist) |
| `query_knowledge_base` | Semantic search over ingested documents (top-k cosine hits) | Read |

### MCP Tools (exposed to Claude Desktop / Claude Code)

| MCP Tool | Description |
|---|---|
| `system_status` | CPU, memory, disk, battery snapshot |
| `list_gitrepos` | All repos with remote URLs |
| `git_status` | Status for a named repo |
| `top_processes` | Top 10 processes by CPU |
| `rag_query` | Semantic search over ingested knowledge base |

---

## 🔐 Security Model

LaptopAI-Agent is built on the assumption that a local agent with file-write access is a high-privilege process. Three controls enforce safe operation:

### 1. 🛡️ Permission Guard

Every tool call passes through `PermissionGuard` before execution:

```
Allowed write paths:   C:\Gitrepos, C:\Users\Sunil\Documents, C:\Users\Sunil\Desktop
Blocked paths:         C:\Windows\System32, C:\Program Files
Allowed commands:      git, python, pip, npm, node, powershell, Get-ChildItem, ...
Manual approval for:   rm, Remove-Item, Format-*, reg delete
Max file write:        100 MB
Max execution time:    30 seconds
```

Any violation raises `PermissionError` and the tool call is blocked — the LLM never sees the result.

### 2. 🔗 SHA-256 Chained Audit Log

Every agent action writes to `logs/audit.jsonl` as a **hash chain** — each entry commits the hash of the previous entry, making any historical modification detectable:

```jsonc
{
  "timestamp": "2026-06-05T00:00:00+00:00",
  "event_type": "TOOL_CALL",
  "actor": "LaptopAI-Agent",
  "action": "read_file",
  "target": "C:\\Gitrepos\\ZKP-RA\\paper.tex",
  "result": "32650 chars",
  "prev_hash": "a3f1cc...",
  "hash": "9d2c44..."   // SHA-256(this entry + prev_hash)
}
```

Verify the full chain integrity at any time:

```bash
python main.py verify-audit
# Chain valid (847 entries)
```

### 3. 🔒 Zero External Calls

| Component | Runs Where |
|---|---|
| LLM inference | Locally via Ollama (`localhost:11434`) |
| Embeddings | Locally via `sentence-transformers` |
| Vector store | Locally via ChromaDB (`./data/chroma_db/`) |
| Audit log | Locally (`./logs/audit.jsonl`) |

No tokens, queries, files, or embeddings ever leave your machine.

---

## 🧩 Claude Desktop / Claude Code Integration

Add to `claude_desktop_config.json`:
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Mac:** `~/Library/Application Support/Claude/claude_desktop_config.json`

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

Once connected, Claude can call `system_status`, `list_gitrepos`, `git_status`, `top_processes`, and `rag_query` directly from any conversation — with every call logged to the audit trail.

---

## 📚 RAG Knowledge Base

The RAG layer ingests `.txt`, `.md`, `.log`, `.py`, `.yaml`, and `.json` files using a sliding-window chunker with upsert deduplication:

| Parameter | Value |
|---|---|
| Vector DB | ChromaDB (persistent local) |
| Embedding model | `all-MiniLM-L6-v2` (sentence-transformers, runs locally) |
| Similarity metric | Cosine |
| Chunk size | 512 tokens |
| Chunk overlap | 64 tokens |
| Deduplication | MD5 hash per `(file_path, chunk_index)` — upsert-safe re-ingestion |
| Default top-k | 5 results |

```bash
# Ingest an entire directory recursively
python main.py ingest C:\Gitrepos

# Ask the agent a RAG-grounded question
python main.py chat
> What does the ZKP-RA circuit enforce at the policy layer?
```

---

## ⚙️ Configuration

All behaviour is controlled by `config.yaml` — no code changes needed:

```yaml
llm:
  model: "qwen2.5-coder:7b"   # swap to llama3.2, mistral, deepseek-r1, etc.
  temperature: 0.1             # low = more deterministic tool calls

rag:
  chunk_size: 512
  chunk_overlap: 64
  top_k: 5

security:
  max_file_size_mb: 100
  allowed_paths:
    - "C:\\Gitrepos"
    - "C:\\Users\\Sunil\\Documents"
  blocked_paths:
    - "C:\\Windows\\System32"
  require_approval_for:
    - "rm"
    - "Remove-Item"

monitoring:
  alert_cpu_percent: 90
  alert_memory_percent: 85
  alert_disk_percent: 80
```

---

## 📁 Project Structure

```
LaptopAI-Agent/
├── main.py                        # CLI entry point
├── config.yaml                    # All runtime configuration
├── requirements.txt
├── src/
│   ├── agent/
│   │   ├── graph.py               # LangGraph StateGraph — agent ↔ ToolNode loop (max 10 iters)
│   │   └── tools.py               # LangChain @tool definitions + PermissionGuard hooks
│   ├── mcp/
│   │   └── server.py              # MCP stdio server — 5 tools exposed to Claude
│   ├── rag/
│   │   └── knowledge_base.py      # ChromaDB ingestion + cosine semantic query
│   └── security/
│       ├── audit.py               # SHA-256 chained append-only audit logger
│       └── permissions.py         # PermissionGuard — path, command, size enforcement
├── data/
│   └── chroma_db/                 # Local vector store (gitignored)
└── logs/
    └── audit.jsonl                # Tamper-evident audit trail (gitignored)
```

---

## 🔬 Recommended Local Models

| Model | Size | Strength |
|---|---|---|
| `qwen2.5-coder:7b` ⭐ | ~4.7 GB | Tool calling, code reasoning — **default** |
| `llama3.2:3b` | ~2.0 GB | Lightweight, fast responses |
| `mistral:7b` | ~4.1 GB | General reasoning, instruction following |
| `deepseek-r1:7b` | ~4.7 GB | Multi-step planning, math |

```bash
ollama pull qwen2.5-coder:7b   # recommended
ollama pull llama3.2:3b        # lightweight alternative
```

---

## 📦 Key Dependencies

| Package | Version | Purpose |
|---|---|---|
| `langgraph` | ≥0.2 | Agentic state machine (agent ↔ tools loop) |
| `langchain-ollama` | ≥0.2 | Ollama LLM binding with native tool-calling |
| `mcp` | ≥1.0 | Model Context Protocol server (stdio transport) |
| `chromadb` | ≥0.5 | Local persistent vector database |
| `sentence-transformers` | ≥3.0 | Local embeddings (`all-MiniLM-L6-v2`) |
| `psutil` | ≥6.0 | CPU, memory, disk, battery, process inspection |
| `rich` | ≥13.0 | Terminal output formatting |
| `typer` | ≥0.12 | CLI command routing |

---

## 📖 Research & References

| Project | Link |
|---|---|
| LangGraph | [github.com/langchain-ai/langgraph](https://github.com/langchain-ai/langgraph) |
| Model Context Protocol | [modelcontextprotocol.io](https://modelcontextprotocol.io) |
| RAGFlow | [github.com/infiniflow/ragflow](https://github.com/infiniflow/ragflow) |
| Agent-S | [github.com/simular-ai/Agent-S](https://github.com/simular-ai/Agent-S) |
| AIOS | [github.com/agiresearch/AIOS](https://github.com/agiresearch/AIOS) |
| SoK: AI Agents for Blockchain | [arXiv:2509.07131](https://arxiv.org/abs/2509.07131) |

---

## 👤 Author

**Sunil Gentyala**
Lead Cybersecurity and AI Security Consultant — HCL America Inc., Dallas TX
IEEE Senior Member No. 101760715 · CISM No. 263076408 · BCS Fellow

[![GitHub](https://img.shields.io/badge/GitHub-sunilgentyala-181717?style=flat-square&logo=github)](https://github.com/sunilgentyala)
[![LinkedIn](https://img.shields.io/badge/LinkedIn-sunilgentyala-0A66C2?style=flat-square&logo=linkedin)](https://www.linkedin.com/in/sunilgentyala/)
[![Portfolio](https://img.shields.io/badge/Portfolio-sunilgentyala.github.io-FF6B35?style=flat-square)](https://sunilgentyala.github.io)
[![IEEE Email](https://img.shields.io/badge/IEEE-sunil.gentyala%40ieee.org-00629B?style=flat-square&logo=ieee)](mailto:sunil.gentyala@ieee.org)

---

## 📄 License

Apache 2.0 — See [LICENSE](LICENSE) for details.

---

<div align="center">
<sub>Built for privacy, security, and full local control. No API keys. No cloud. Just your machine.</sub>
</div>
