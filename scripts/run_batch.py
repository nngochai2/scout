"""CLI: run the Scout daily batch — fetch → triage → investigate → persist.

Usage:
    python scripts/run_batch.py [--limit N] [--triage-only] [--mock]
"""
import argparse
import sys
import os
from collections import Counter

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv
load_dotenv()

from sqlalchemy.orm import Session

from agent.database import init_db, engine, TicketRow, DiagnosisRow, EvidenceItemRow, StageCountRow
from agent.flow import load_flow, DEFAULT_FLOW_PATH
from agent.triage import triage_batch
from agent.workflow_engine import WorkflowEngine
from agent.models import TriageVerdict
from agent.mcp_clients.knowledge_graph import KnowledgeGraphClient
from agent.mcp_clients.code_graph import CodeGraphClient
from agent.mcp_clients.oracle import OracleClient
from agent.mcp_clients.azure_devops import AzureDevOpsClient
from ingestion.freshdesk import FreshdeskAdapter
from ingestion.mock import MockAdapter, DEFAULT_FIXTURE_PATH

import json
import os
from pathlib import Path

# MCP URLs: mcp_config.json (written by the dashboard) overrides env vars, which override defaults.
_MCP_CONFIG_PATH = Path(__file__).parent.parent / "mcp_config.json"
_mcp_cfg: dict = {}
if _MCP_CONFIG_PATH.exists():
    try:
        _mcp_cfg = json.loads(_MCP_CONFIG_PATH.read_text())
    except Exception:
        pass

def _mcp_url(key: str, env_var: str, default: str) -> str:
    return _mcp_cfg.get(key) or os.getenv(env_var, default)

_KG_URL  = _mcp_url("knowledge_graph", "KNOWLEDGE_GRAPH_URL", "http://127.0.0.1:8100/sse")
_CG_URL  = _mcp_url("code_graph",      "CODE_GRAPH_URL",      "http://127.0.0.1:8101/sse")
_ORA_URL = _mcp_url("oracle",          "ORACLE_URL",           "http://127.0.0.1:8102/sse")
_ADO_URL = _mcp_url("azure_devops",    "AZURE_DEVOPS_URL",     "http://127.0.0.1:8103/sse")


def main() -> None:
    parser = argparse.ArgumentParser(description="Scout daily triage batch")
    parser.add_argument("--limit", type=int, default=20, help="Max tickets to fetch (default 20)")
    parser.add_argument("--triage-only", action="store_true", help="Run triage only; skip investigation")
    parser.add_argument("--mock", action="store_true", help=f"Use mock ticket fixture ({DEFAULT_FIXTURE_PATH}) instead of Freshdesk")
    args = parser.parse_args()

    init_db()

    # --- Ticket source ---
    if args.mock:
        try:
            adapter = MockAdapter()
        except FileNotFoundError as e:
            print(f"Error: {e}")
            print(f"Create the fixture at {DEFAULT_FIXTURE_PATH}.")
            sys.exit(1)
        print(f"Using mock fixture: {DEFAULT_FIXTURE_PATH}")
    else:
        try:
            adapter = FreshdeskAdapter()
        except EnvironmentError as e:
            print(f"Error: {e}")
            print("Copy .env.example to .env and fill in FRESHDESK_DOMAIN and FRESHDESK_API_KEY.")
            sys.exit(1)

    print(f"Fetching up to {args.limit} closed tickets...")
    tickets = adapter.fetch_closed(limit=args.limit)
    if not tickets:
        print("No tickets found.")
        return
    print(f"Fetched {len(tickets)} ticket(s).\n")

    # --- Persist fetched tickets ---
    with Session(engine) as session:
        for t in tickets:
            if session.query(TicketRow).filter_by(id=t.id).first() is None:
                session.add(TicketRow(
                    id=t.id, title=t.title, description=t.description,
                    status=t.status, resolution_notes=t.resolution_notes,
                    source_system=t.source_system,
                ))
        session.commit()

    # --- Triage gate ---
    print("--- Triage gate ---")
    triage_results = triage_batch(tickets)

    counts = Counter(r.verdict.value for r in triage_results)
    print(f"\nTriage complete ({len(triage_results)} results):")
    for verdict, n in sorted(counts.items()):
        print(f"  {verdict}: {n}")

    if args.triage_only:
        print("\n--triage-only: skipping investigation.")
        return

    to_investigate = [r for r in triage_results if r.verdict == TriageVerdict.INVESTIGATE]
    if not to_investigate:
        print("\nNo tickets escalated to investigation.")
        return

    # --- Load flow ---
    try:
        flow = load_flow(DEFAULT_FLOW_PATH)
    except FileNotFoundError:
        print(f"No flow found at {DEFAULT_FLOW_PATH}. Run the Flow Editor to configure one.")
        sys.exit(1)

    # --- Connect SSE MCP clients declared in the flow ---
    mcp_needed = {n.config.mcp for n in flow.nodes if n.type == "tool"}
    _URL_MAP = {
        "knowledge_graph": _KG_URL,
        "code_graph": _CG_URL,
        "oracle": _ORA_URL,
        "azure_devops": _ADO_URL,
    }
    _CLIENT_CLS = {
        "knowledge_graph": KnowledgeGraphClient,
        "code_graph": CodeGraphClient,
        "oracle": OracleClient,
        "azure_devops": AzureDevOpsClient,
    }
    clients = {}
    for mcp_name in mcp_needed:
        url = _URL_MAP[mcp_name]
        client = _CLIENT_CLS[mcp_name](url=url)
        try:
            client.connect()
            print(f"  {mcp_name} connected ({url})")
            clients[mcp_name] = client
        except ConnectionError as exc:
            print(f"Error: {exc}")
            print("Start all required NAA MCP servers before running the batch.")
            sys.exit(1)

    # Build mcp_fns: each fn passes ticket context to the MCP and returns its text result
    def make_mcp_fn(client):
        def _fn(ticket_context: str) -> str:
            # Use a generic search query built from the ticket context
            return client.call_tool(
                _default_tool_for(client),
                {"query": ticket_context[:500]},
            )
        return _fn

    def _default_tool_for(client) -> str:
        """Pick a sensible default read tool for each MCP type."""
        from agent.mcp_clients.knowledge_graph import KnowledgeGraphClient as KG
        from agent.mcp_clients.code_graph import CodeGraphClient as CG
        from agent.mcp_clients.oracle import OracleClient as ORA
        from agent.mcp_clients.azure_devops import AzureDevOpsClient as ADO
        if isinstance(client, KG):
            return "search_notes"
        if isinstance(client, CG):
            return "search_code"
        if isinstance(client, ORA):
            return "query"
        if isinstance(client, ADO):
            return "search_work_items"
        return list(client._allowed)[0]

    mcp_fns = {name: make_mcp_fn(c) for name, c in clients.items()}

    # --- Run Workflow Engine per INVESTIGATE ticket ---
    ticket_map = {t.id: t for t in tickets}
    engine_obj = WorkflowEngine(flow=flow, mcp_fns=mcp_fns)

    print(f"\n--- Investigation ({len(to_investigate)} ticket(s)) ---")
    try:
        for triage in to_investigate:
            ticket = ticket_map.get(triage.ticket_id)
            if ticket is None:
                print(f"  [{triage.ticket_id}] not found in fetch — skipping")
                continue

            print(f"  [{ticket.id}] {ticket.title[:70]}")
            try:
                diagnosis, stage_records = engine_obj.investigate(ticket, triage)
                cause = diagnosis.root_cause or "(insufficient evidence)"
                print(f"    confidence={diagnosis.confidence.value}  cause={cause[:100]}")

                # Persist diagnosis + stage costs
                with Session(engine) as session:
                    if session.query(DiagnosisRow).filter_by(ticket_id=ticket.id).first() is None:
                        diag_row = DiagnosisRow(
                            ticket_id=ticket.id,
                            root_cause=diagnosis.root_cause,
                            confidence=diagnosis.confidence.value,
                        )
                        session.add(diag_row)
                        session.flush()
                        for ev in diagnosis.evidence:
                            session.add(EvidenceItemRow(
                                diagnosis_id=diag_row.id,
                                source_type=ev.source_type.value,
                                reference=ev.reference,
                                passage=ev.passage,
                            ))
                        for sr in stage_records:
                            if session.query(StageCountRow).filter_by(
                                ticket_id=ticket.id, stage=sr.stage
                            ).first() is None:
                                session.add(StageCountRow(
                                    ticket_id=ticket.id,
                                    stage=sr.stage,
                                    input_tokens=sr.input_tokens,
                                    output_tokens=sr.output_tokens,
                                ))
                        session.commit()
            except Exception as exc:
                print(f"    ERROR: {exc!r}")
    finally:
        for c in clients.values():
            c.close()

    print("\nBatch complete.")


if __name__ == "__main__":
    main()
