# DevGraph 

A CLI tool that ingests GitHub Issues and Pull Requests, extracts named entities and relationships using a local AI model, and builds a queryable knowledge graph — all running free on your laptop.

Ask questions like:
- *"Which engineers have touched the auth service most?"*
- *"What bugs are linked to the payments module?"*
- *"Show me all services mentioned in the last 50 PRs"*

---

## What It Does

**Input:** A GitHub repo (issues + PRs via API)

**Output:**
- A local knowledge graph of extracted entities: engineers, services, bugs, modules, deployments, errors
- Typed relationships between them: `AUTHORED`, `FIXED`, `BROKE`, `DEPENDS_ON`, `CAUSED_BY`, and more
- A natural language query interface — ask plain English questions, get graph-traversal answers
- An interactive HTML visualization you can open in any browser

---

## Features

- **Structured entity extraction** — strict JSON schema enforced on all LLM output, making the pipeline reliable not just creative
- **Coreference resolution** — detects that "auth", "auth-service", and "authentication module" are the same entity and merges them
- **Relationship confidence scoring** — each extracted edge gets a 0–1 confidence score; low-confidence edges are visually dimmed
- **Natural language queries** — plain English → graph traversal → cited answer with source PR/issue links
- **Incremental ingestion** — only processes new issues/PRs since the last run using cursor-based checkpointing

---

## Tech Stack

| Layer | Tool |
|-------|------|
| Language | Python 3.11+ |
| CLI | Typer + Rich |
| Local AI | Ollama (llama3.2 / mistral / llama3.1) |
| Graph | NetworkX |
| Visualization | pyvis |
| Schema validation | Pydantic |
| GitHub ingestion | GitHub REST API |

**Cost: $0** — runs entirely on your laptop using Ollama.

---

## Quickstart

### 1. Install Ollama

Download from [ollama.com](https://ollama.com) and pull a model:

```bash
ollama pull llama3.2
```

### 2. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/devgraph.git
cd devgraph
python3 -m venv venv
source venv/bin/activate   # Windows: .\venv\Scripts\Activate.ps1
pip install -e .
```

### 3. Configure

```bash
cp .env.example .env
```

Open `.env` and add your GitHub token (optional but recommended — raises rate limit from 60 to 5,000 req/hr):

```
GITHUB_TOKEN=ghp_your_token_here
```

Get a token at [github.com/settings/tokens](https://github.com/settings/tokens) — no scopes needed for public repos.

### 4. Ingest a repo

```bash
devgraph ingest cli/cli --max 100
```

### 5. Open the graph

Double-click `devgraph.html` — opens in your browser as an interactive graph.

### 6. Ask questions

```bash
devgraph query
```

```
❓ Question: which engineers touched the auth service most?
❓ Question: what bugs are linked to the payments module?
❓ Question: show me all services
```

---

## All Commands

```bash
devgraph ingest <owner/repo> --max 200   # ingest a repo
devgraph ingest <owner/repo> --full      # force full re-fetch
devgraph query                           # interactive question mode
devgraph query "your question here"      # one-off question
devgraph stats                           # graph summary
devgraph export                          # re-export HTML visualization
devgraph reset <owner/repo>              # clear checkpoint
```

---

## Choosing a Model

Set `DEVGRAPH_MODEL` in your `.env` file:

| Model | Size | Speed | Accuracy |
|-------|------|-------|----------|
| `llama3.2:1b` | 1.3 GB | Very fast | Basic |
| `llama3.2` | 2 GB | Fast | Good |
| `llama3.1:8b` | 4.7 GB | Medium | Better |
| `mistral` | 4.1 GB | Medium | Better |

```
DEVGRAPH_MODEL=llama3.1:8b
```

---

## Project Structure

```
devgraph/
├── devgraph/
│   ├── cli.py          # Typer CLI entry point
│   ├── ingestion.py    # GitHub API fetcher
│   ├── extraction.py   # LLM entity/relationship extraction
│   ├── coreference.py  # Entity deduplication
│   ├── graph.py        # NetworkX graph builder & queries
│   ├── query.py        # Natural language query interface
│   ├── visualize.py    # pyvis HTML export
│   ├── models.py       # Pydantic schemas
│   └── checkpoint.py   # Incremental ingestion state
├── .env.example
├── requirements.txt
└── pyproject.toml
```
