# Scout — Local Run Runbook

This document describes the correct startup sequence for a full local run of Scout with all NAA MCP servers active.

## Prerequisites

- Python 3.11+ with Scout dependencies installed (`pip install -r requirements.txt`)
- Node.js 18+ with dashboard dependencies installed (`cd dashboard && npm install`)
- Neo4j 5.x running locally (default bolt port 7687) — used by Knowledge Graph and Code Graph MCPs
- NAA project cloned and its own dependencies installed
- A `.env` file at the Scout repo root (copy from `.env.example` and fill in values)

## Environment variables (`.env`)

| Variable | Description | Default |
|---|---|---|
| `ANTHROPIC_API_KEY` | Anthropic API key | required |
| `FRESHDESK_DOMAIN` | Freshdesk subdomain | required (unless `--mock`) |
| `FRESHDESK_API_KEY` | Freshdesk API key | required (unless `--mock`) |
| `KNOWLEDGE_GRAPH_URL` | Knowledge Graph MCP SSE URL | `http://127.0.0.1:8100/sse` |
| `CODE_GRAPH_URL` | Code Graph MCP SSE URL | `http://127.0.0.1:8101/sse` |
| `ORACLE_URL` | Oracle MCP SSE URL | `http://127.0.0.1:8102/sse` |
| `AZURE_DEVOPS_URL` | Azure DevOps MCP SSE URL | `http://127.0.0.1:8103/sse` |

## Startup sequence

Start each service in order. Each must be ready before the next step.

### 1. Neo4j

Start Neo4j (e.g. via Neo4j Desktop or `neo4j start`). Confirm it accepts connections on bolt://localhost:7687 before continuing.

### 2. NAA MCP servers

From the NAA repository, start each MCP server. They all use SSE transport. Ports must match `KNOWLEDGE_GRAPH_URL` etc. in `.env`.

```bash
# Knowledge Graph MCP (Obsidian vault → Neo4j)
python -m mcp.server.knowledge_graph --port 8100

# Code Graph MCP (jQAssistant Java source → Neo4j)
python -m mcp.server.code_graph --port 8101

# Oracle MCP
python -m mcp.server.oracle --port 8102

# Azure DevOps MCP
python -m mcp.server.azure_devops --port 8103
```

Check that each server's `/sse` endpoint responds (e.g. `curl http://127.0.0.1:8100/sse`).

### 3. Scout FastAPI server

```bash
uvicorn api.main:app --reload --port 8000
```

The dashboard connects to `http://localhost:8000`.

### 4. Scout dashboard

```bash
cd dashboard && npm run dev
```

Open `http://localhost:5173` in a browser. Switch to the **Flow Editor** tab and configure the investigation flow before running the batch.

### 5. Run the batch

With mock tickets (no Freshdesk credential needed):

```bash
python scripts/run_batch.py --mock
```

With real Freshdesk tickets:

```bash
python scripts/run_batch.py --limit 20
```

Add `--triage-only` to skip investigation and just see triage verdicts.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `ConnectionError: Cannot connect to MCP server at http://127.0.0.1:8100/sse` | Knowledge Graph MCP not started or wrong port |
| `FileNotFoundError: Flow file not found: data/flow.json` | Open the Flow Editor, compose a flow, and click Save before running the batch |
| `ModuleNotFoundError: No module named 'anthropic'` | Run `pip install -r requirements.txt` |
| Triage returns all `insufficient_signal` | Check `ANTHROPIC_API_KEY` is set correctly |
