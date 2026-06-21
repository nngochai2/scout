# Scout

Daily support triage and investigation agent for legacy Java enterprise applications. Scout fetches closed support tickets, classifies them with a triage gate, investigates escalated tickets by walking a configurable flow of NAA MCP tools, and presents findings in a reviewer dashboard.

---

## Architecture

```
Freshdesk / mock fixture
        │
        ▼
   Triage Gate (Batches API, claude-haiku)
        │  verdict: investigate / clarify / insufficient / out_of_scope
        ▼
  Workflow Engine  ←── data/flow.json (configured via Flow Editor)
        │
        ├── Knowledge Graph MCP  (Obsidian vault → Neo4j)
        ├── Code Graph MCP       (Java source → Neo4j via jQAssistant)
        ├── Oracle MCP           (read-only SQL)
        └── Azure DevOps MCP     (work items, PRs, builds)
        │
        ▼
   Diagnosis (confidence, root cause, evidence)
        │
        ▼
  FastAPI  ──►  React dashboard  (Tickets tab + Flow Editor tab)
```

Each MCP server is an NAA SSE server. Scout connects as a read-only client — write tools are blocked by an allowlist guard.

---

## Repository layout

```
agent/
  flow.py              # InvestigationFlow data model + load/save
  workflow_engine.py   # Deterministic graph executor (replaces multi-turn loop)
  triage.py            # Batches API triage gate
  models.py            # Shared Pydantic models
  database.py          # SQLAlchemy ORM (SQLite)
  mcp_clients/
    sse_client.py      # Generic sync SSE MCP client
    knowledge_graph.py
    code_graph.py
    oracle.py
    azure_devops.py

api/
  main.py              # FastAPI: /tickets, /flow, /flow/status

ingestion/
  base.py              # TicketSource ABC
  freshdesk.py         # Live Freshdesk adapter
  mock.py              # Local fixture adapter (--mock flag)

dashboard/
  src/
    App.tsx            # Tickets tab (triage + diagnosis + review actions)
    FlowEditor.tsx     # Flow Editor tab (React Flow canvas)

scripts/
  run_batch.py         # CLI entry point

data/
  flow.json            # Saved investigation flow (edit via Flow Editor)
  mock_tickets.json    # Fixture for --mock runs
  mock_ticket_generation_prompt.md

docs/
  runbook.md           # Full startup sequence
  prd-flow-editor-and-workflow-engine.md
  issues/              # Issue files (01–08)
  adr/                 # Architecture Decision Records (0001–0009)
```

---

## Quick start

### 1. Install Python dependencies

```bash
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Fill in ANTHROPIC_API_KEY (required)
# Fill in FRESHDESK_DOMAIN + FRESHDESK_API_KEY (optional — use --mock without them)
# Set KNOWLEDGE_GRAPH_URL, CODE_GRAPH_URL, ORACLE_URL, AZURE_DEVOPS_URL if non-default
```

### 3. Install dashboard dependencies

```bash
cd dashboard && npm install
```

### 4. Start services

See `docs/runbook.md` for the full sequence (Neo4j → NAA MCP servers → FastAPI → dashboard → batch).

**Minimal local run without NAA servers (mock mode, triage only):**

```bash
# Terminal 1 — API server
uvicorn api.main:app --reload --port 8000

# Terminal 2 — dashboard
cd dashboard && npm run dev

# Terminal 3 — batch (triage only, no MCP servers needed)
python scripts/run_batch.py --mock --triage-only
```

Open `http://localhost:5173`. The Tickets tab shows triage results.

**Full investigation run (requires NAA MCP servers and a saved flow):**

1. Open the Flow Editor tab in the dashboard, compose an investigation flow, and click Save.
2. Start the NAA MCP servers (see `docs/runbook.md`).
3. Run the batch:

```bash
python scripts/run_batch.py --mock
```

---

## Flow Editor

The Flow Editor tab lets you compose the investigation flow visually:

- **Drag** Tool nodes (Knowledge Graph, Code Graph, Oracle, Azure DevOps), Branch nodes, and a Conclude node onto the canvas
- **Connect** nodes by dragging from a node handle to another node
- **Inspect** a Branch node by clicking it — set the Confidence condition on each outgoing edge (≥ High, ≥ Medium, = Low, = Insufficient, Always)
- **Save** writes the flow to `data/flow.json`; the batch reads it on next run
- **Status dots** in the sidebar show which MCP servers are currently reachable (green) or offline (red)

---

## Running tests

```bash
python -m pytest tests/ -q
```

25 tests covering the mock adapter, flow data model, API endpoints, SSE client allowlist and connection behaviour, and the workflow engine routing logic.

---