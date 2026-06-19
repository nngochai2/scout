from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy.orm import Session
import httpx
import json
import os
from pathlib import Path

from agent.database import init_db, engine, TicketRow, TriageResultRow, DiagnosisRow, EvidenceItemRow, StageCountRow, ReviewActionRow
from agent.models import TriageVerdict, ReviewAction
import agent.flow as flow_module
from agent.flow import InvestigationFlow, FlowNode


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Scout", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─── MCP config ───────────────────────────────────────────────────────────────

_MCP_CONFIG_PATH = Path(__file__).parent.parent / "mcp_config.json"

_MCP_DEFAULTS: dict[str, str] = {
    "knowledge_graph": os.getenv("KNOWLEDGE_GRAPH_URL", "http://127.0.0.1:8100/sse"),
    "code_graph":      os.getenv("CODE_GRAPH_URL",      "http://127.0.0.1:8101/sse"),
    "oracle":          os.getenv("ORACLE_URL",           "http://127.0.0.1:8102/sse"),
    "azure_devops":    os.getenv("AZURE_DEVOPS_URL",     "http://127.0.0.1:8103/sse"),
}


def _load_mcp_config() -> dict[str, str]:
    """Return current URLs: file overrides take precedence over env/defaults."""
    urls = dict(_MCP_DEFAULTS)
    if _MCP_CONFIG_PATH.exists():
        try:
            overrides = json.loads(_MCP_CONFIG_PATH.read_text())
            for key in _MCP_DEFAULTS:
                if key in overrides and isinstance(overrides[key], str):
                    urls[key] = overrides[key]
        except Exception:
            pass
    return urls


def _save_mcp_config(urls: dict[str, str]) -> None:
    _MCP_CONFIG_PATH.write_text(json.dumps(urls, indent=2))


def _probe_url(url: str) -> bool:
    try:
        with httpx.Client(timeout=2.0) as http:
            resp = http.get(url)
            return resp.status_code < 500
    except Exception:
        return False


@app.get("/mcp/config")
def get_mcp_config():
    return _load_mcp_config()


@app.put("/mcp/config")
def put_mcp_config(body: dict):
    current = _load_mcp_config()
    for key in _MCP_DEFAULTS:
        if key in body and isinstance(body[key], str) and body[key].strip():
            current[key] = body[key].strip()
    _save_mcp_config(current)
    return current


# ─── Tickets ──────────────────────────────────────────────────────────────────

@app.get("/tickets")
def list_tickets():
    with Session(engine) as session:
        rows = session.query(TicketRow).all()
        result = []
        for t in rows:
            triage = t.triage_result
            diagnosis = t.diagnosis
            stage_counts = {sc.stage: {"input": sc.input_tokens, "output": sc.output_tokens} for sc in t.stage_counts}
            review = t.review_action

            result.append({
                "id": t.id,
                "title": t.title,
                "description": t.description,
                "status": t.status,
                "source_system": t.source_system,
                "triage": {
                    "verdict": triage.verdict if triage else None,
                    "summary": triage.summary if triage else None,
                    "clarifying_question": triage.clarifying_question if triage else None,
                } if triage else None,
                "diagnosis": {
                    "root_cause": diagnosis.root_cause if diagnosis else None,
                    "confidence": diagnosis.confidence if diagnosis else None,
                    "evidence": [
                        {"source_type": e.source_type, "reference": e.reference, "passage": e.passage}
                        for e in diagnosis.evidence_items
                    ] if diagnosis else [],
                } if diagnosis else None,
                "stage_costs": stage_counts,
                "review": {"action": review.action} if review else None,
            })
        return result


# ─── Flow status ──────────────────────────────────────────────────────────────

@app.get("/flow/status")
def get_flow_status():
    urls = _load_mcp_config()
    return {
        name: {"url": url, "reachable": _probe_url(url)}
        for name, url in urls.items()
    }


# ─── Flow CRUD ────────────────────────────────────────────────────────────────

_DEFAULT_FLOW = InvestigationFlow(
    entry_node_id="conclude",
    nodes=[FlowNode(id="conclude", type="conclude")],
)


@app.get("/flow")
def get_flow():
    try:
        return flow_module.load_flow(flow_module.DEFAULT_FLOW_PATH).model_dump()
    except FileNotFoundError:
        return _DEFAULT_FLOW.model_dump()


@app.put("/flow")
def put_flow(body: dict):
    try:
        flow = InvestigationFlow(**body)
    except (ValidationError, ValueError) as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    flow_module.save_flow(flow, flow_module.DEFAULT_FLOW_PATH)
    return {"ok": True}


# ─── Reviews ──────────────────────────────────────────────────────────────────

@app.post("/tickets/{ticket_id}/review")
def submit_review(ticket_id: str, action: ReviewAction):
    with Session(engine) as session:
        row = ReviewActionRow(ticket_id=ticket_id, action=action.value)
        session.add(row)
        session.commit()
    return {"ok": True}
