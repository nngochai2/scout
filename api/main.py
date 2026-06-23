from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import ValidationError
from sqlalchemy.orm import Session
from sqlalchemy import inspect, text
import httpx
import json
import os
from pathlib import Path

from dotenv import set_key

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


# ─── LLM config ───────────────────────────────────────────────────────────────

_ENV_PATH = str(Path(__file__).parent.parent / ".env")

_PROVIDER_KEY_MAP = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
    "deepseek": "DEEPSEEK_API_KEY",
    "moonshot": "MOONSHOT_API_KEY",
}


@app.get("/llm/config")
def get_llm_config():
    import litellm
    provider = os.getenv("LLM_PROVIDER")
    model = os.getenv("LLM_MODEL")
    key_present = bool(os.getenv(_PROVIDER_KEY_MAP.get(provider or "", ""), "")) if provider else False
    pricing = litellm.model_cost.get(model or "", {})
    pricing_available = bool(pricing)
    return {
        "provider": provider,
        "model": model,
        "api_key_set": key_present,
        "pricing_available": pricing_available,
        "input_cost_per_token": pricing.get("input_cost_per_token", 0.00000025),
        "output_cost_per_token": pricing.get("output_cost_per_token", 0.00000125),
    }


@app.put("/llm/config")
def put_llm_config(body: dict):
    provider = body.get("provider", "").strip()
    model = body.get("model", "").strip()
    api_key = body.get("api_key", "").strip()

    if not provider:
        raise HTTPException(status_code=422, detail="provider is required")

    set_key(_ENV_PATH, "LLM_PROVIDER", provider)
    os.environ["LLM_PROVIDER"] = provider

    if model:
        set_key(_ENV_PATH, "LLM_MODEL", model)
        os.environ["LLM_MODEL"] = model

    if api_key and provider in _PROVIDER_KEY_MAP:
        env_key = _PROVIDER_KEY_MAP[provider]
        set_key(_ENV_PATH, env_key, api_key)
        os.environ[env_key] = api_key

    return get_llm_config()


@app.get("/servicedesk/config")
def get_servicedesk_config():
    provider = os.getenv("SERVICEDESK_PROVIDER")
    domain = os.getenv("FRESHDESK_DOMAIN") if provider == "freshdesk" else None
    api_key_set = bool(os.getenv("FRESHDESK_API_KEY")) if provider == "freshdesk" else False
    return {"provider": provider, "domain": domain, "api_key_set": api_key_set}


@app.put("/servicedesk/config")
def put_servicedesk_config(body: dict):
    provider = body.get("provider", "").strip()
    if not provider:
        raise HTTPException(status_code=422, detail="provider is required")

    set_key(_ENV_PATH, "SERVICEDESK_PROVIDER", provider)
    os.environ["SERVICEDESK_PROVIDER"] = provider

    if provider == "freshdesk":
        domain = body.get("domain", "").strip()
        api_key = body.get("api_key", "").strip()
        if domain:
            set_key(_ENV_PATH, "FRESHDESK_DOMAIN", domain)
            os.environ["FRESHDESK_DOMAIN"] = domain
        if api_key:
            set_key(_ENV_PATH, "FRESHDESK_API_KEY", api_key)
            os.environ["FRESHDESK_API_KEY"] = api_key

    return get_servicedesk_config()


@app.get("/llm/models")
def get_llm_models(provider: str):
    import litellm
    if provider == "anthropic":
        models = sorted(litellm.models_by_provider.get("anthropic", []))
        return {"provider": provider, "models": models}

    # OpenAI-compatible providers: fetch live from /v1/models
    base_urls = {"openai": "https://api.openai.com", "deepseek": "https://api.deepseek.com", "moonshot": "https://api.moonshot.ai/v1"}
    key_names = {"openai": "OPENAI_API_KEY", "deepseek": "DEEPSEEK_API_KEY", "moonshot": "MOONSHOT_API_KEY"}
    base_url = base_urls.get(provider)
    api_key = os.getenv(key_names.get(provider, ""))
    if not base_url or not api_key:
        raise HTTPException(status_code=400, detail=f"Unknown provider or missing API key: {provider}")

    try:
        with httpx.Client(timeout=10.0) as http:
            resp = http.get(f"{base_url}/v1/models", headers={"Authorization": f"Bearer {api_key}"})
            resp.raise_for_status()
            data = resp.json()
            models = sorted(m["id"] for m in data.get("data", []))
            return {"provider": provider, "models": models}
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not fetch models: {exc}")


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


# ─── Database browser ─────────────────────────────────────────────────────────

_ALLOWED_TABLES = {
    "tickets", "triage_results", "diagnoses",
    "evidence_items", "stage_counts", "review_actions",
}


@app.get("/db/{table}")
def browse_table(table: str, limit: int = 200, offset: int = 0):
    if table not in _ALLOWED_TABLES:
        raise HTTPException(status_code=404, detail=f"Unknown table '{table}'")
    inspector = inspect(engine)
    columns = [col["name"] for col in inspector.get_columns(table)]
    with engine.connect() as conn:
        total = conn.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
        rows = conn.execute(
            text(f"SELECT * FROM {table} LIMIT :lim OFFSET :off"),
            {"lim": limit, "off": offset},
        ).fetchall()
    return {
        "table": table,
        "columns": columns,
        "rows": [dict(zip(columns, row)) for row in rows],
        "total": int(total),
        "limit": limit,
        "offset": offset,
    }
