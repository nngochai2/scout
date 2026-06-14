"""Investigation chain: multi-turn tool_use loop with stop-on-sufficient logic."""
import os
from typing import Callable

import anthropic
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from agent.database import engine, DiagnosisRow, EvidenceItemRow, StageCountRow
from agent.models import (
    Confidence,
    Diagnosis,
    Evidence,
    EvidenceType,
    InvestigationStage,
    Ticket,
    TriageResult,
    TriageVerdict,
)

load_dotenv()

_MODEL = "claude-sonnet-4-6"

# Each tool callable accepts the tool's input dict and returns a plain-text result string.
# The actual implementations (MCP clients) are injected by the caller.
ToolCallable = Callable[[dict], str]

_TOOLS: list[dict] = [
    {
        "name": "search_docs",
        "description": (
            "Search the project documentation corpus for information relevant to this ticket. "
            "Returns ranked passages with their source locations."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Natural-language search query"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "query_db",
        "description": (
            "Run a read-only SQL SELECT against the project Oracle database. "
            "Returns result rows as text. Never use UPDATE, INSERT, DELETE, or DDL."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {"type": "string", "description": "Read-only SQL query (SELECT only)"},
            },
            "required": ["sql"],
        },
    },
    {
        "name": "search_code",
        "description": (
            "Search the Java source code repository using ripgrep. "
            "Returns matching lines with file paths and line numbers."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for"},
                "file_pattern": {
                    "type": "string",
                    "description": "Optional glob to restrict which files are searched (e.g. '*.java')",
                },
            },
            "required": ["pattern"],
        },
    },
    {
        "name": "conclude",
        "description": (
            "State your final diagnosis and end the investigation. "
            "Call this as soon as you have high or medium confidence, or when all tools are exhausted."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "root_cause": {
                    "type": "string",
                    "description": "The likely root cause, or null if evidence is insufficient",
                },
                "confidence": {
                    "type": "string",
                    "enum": ["high", "medium", "low", "insufficient"],
                },
                "evidence": {
                    "type": "array",
                    "description": "Every claim must be backed by a specific artifact",
                    "items": {
                        "type": "object",
                        "properties": {
                            "source_type": {"type": "string", "enum": ["DOC", "DB", "CODE"]},
                            "reference": {
                                "type": "string",
                                "description": "e.g. 'requirements.docx:p3', 'ORDERS WHERE ID=99', 'OrderBean.java:142'",
                            },
                            "passage": {"type": "string", "description": "Verbatim excerpt that supports the claim"},
                        },
                        "required": ["source_type", "reference", "passage"],
                    },
                },
            },
            "required": ["confidence", "evidence"],
        },
    },
]

_SYSTEM = """\
You are Scout, an investigation agent for a legacy Java enterprise application
(JavaEE / WebSphere 7, Apache Struts, EJB, Oracle database).

A ticket has been escalated to you because the triage gate judged it worth investigating.
Use the tools to find the root cause:
  1. search_docs  — search project documentation
  2. query_db     — run read-only SQL queries
  3. search_code  — search Java source code with ripgrep

Rules:
  • Work through the chain: docs → DB → code, but skip a layer if it is clearly irrelevant.
  • Stop as soon as you reach high or medium confidence — call conclude() immediately.
  • If you exhaust all tools without sufficient grounding, call conclude() with confidence="insufficient".
  • Every claim in evidence must cite a specific tool result (file+line, table+key, doc+section).
  • Never attempt to write to the database — SELECT only.
  • You may call each tool multiple times with different queries."""


def _not_configured(name: str) -> ToolCallable:
    def _stub(inputs: dict) -> str:
        return f"[Tool '{name}' is not connected. No MCP server configured for this environment.]"
    return _stub


def investigate(
    ticket: Ticket,
    triage: TriageResult,
    *,
    search_docs: ToolCallable | None = None,
    query_db: ToolCallable | None = None,
    search_code: ToolCallable | None = None,
) -> Diagnosis:
    """Run the investigation chain for a single ticket. Persists and returns a Diagnosis."""
    client = anthropic.Anthropic()

    user_content = f"Subject: {ticket.title}"
    if ticket.description:
        user_content += f"\n\nDescription:\n{ticket.description}"
    user_content += f"\n\nTriage summary: {triage.summary}"

    messages: list[dict] = [{"role": "user", "content": user_content}]

    dispatch: dict[str, ToolCallable] = {
        "search_docs": search_docs or _not_configured("search_docs"),
        "query_db": query_db or _not_configured("query_db"),
        "search_code": search_code or _not_configured("search_code"),
    }

    stage_tokens: dict[str, dict[str, int]] = {}
    diagnosis: Diagnosis | None = None
    MAX_TURNS = 12
    turns = 0

    while diagnosis is None and turns < MAX_TURNS:
        turns += 1
        response = client.messages.create(
            model=_MODEL,
            max_tokens=4096,
            system=_SYSTEM,
            tools=_TOOLS,
            messages=messages,
        )

        # Stage is inferred from tools used in prior turns, so the first turn
        # (no tools used yet) is attributed to "triage" — intentional.
        stage = _current_stage(messages)
        u = response.usage
        acc = stage_tokens.setdefault(stage, {"input": 0, "output": 0})
        acc["input"] += u.input_tokens
        acc["output"] += u.output_tokens

        tool_results = []
        for block in response.content:
            if block.type != "tool_use":
                continue
            if block.name == "conclude":
                diagnosis = _build_diagnosis(ticket.id, triage.verdict, block.input)
                break
            fn = dispatch.get(block.name, _not_configured(block.name))
            result_text = fn(block.input)
            tool_results.append({
                "type": "tool_result",
                "tool_use_id": block.id,
                "content": result_text,
            })

        if diagnosis is not None:
            break

        messages.append({"role": "assistant", "content": response.content})

        if tool_results:
            messages.append({"role": "user", "content": tool_results})
        else:
            # Model returned end_turn without calling conclude — treat as insufficient
            diagnosis = Diagnosis(
                ticket_id=ticket.id,
                root_cause=None,
                confidence=Confidence.INSUFFICIENT,
                evidence=[],
                triage_verdict=triage.verdict,
            )

    if diagnosis is None:
        # MAX_TURNS reached without conclude — treat as insufficient evidence
        diagnosis = Diagnosis(
            ticket_id=ticket.id,
            root_cause=None,
            confidence=Confidence.INSUFFICIENT,
            evidence=[],
            triage_verdict=triage.verdict,
        )

    _persist(ticket.id, diagnosis, stage_tokens)
    return diagnosis


def _current_stage(messages: list[dict]) -> str:
    """Infer the investigation stage from which tools have been called so far."""
    used: set[str] = set()
    for msg in messages:
        if msg["role"] != "assistant":
            continue
        for block in msg["content"]:
            if hasattr(block, "name"):
                used.add(block.name)
    if "search_code" in used:
        return InvestigationStage.CODE.value
    if "query_db" in used:
        return InvestigationStage.DB.value
    if "search_docs" in used:
        return InvestigationStage.DOCS.value
    return InvestigationStage.TRIAGE.value


def _build_diagnosis(ticket_id: str, verdict: TriageVerdict, inputs: dict) -> Diagnosis:
    evidence = [
        Evidence(
            source_type=EvidenceType(e["source_type"]),
            reference=e["reference"],
            passage=e["passage"],
        )
        for e in inputs.get("evidence", [])
    ]
    return Diagnosis(
        ticket_id=ticket_id,
        root_cause=inputs.get("root_cause"),
        confidence=Confidence(inputs["confidence"]),
        evidence=evidence,
        triage_verdict=verdict,
    )


def _persist(ticket_id: str, diagnosis: Diagnosis, stage_tokens: dict[str, dict[str, int]]) -> None:
    with Session(engine) as session:
        existing_diag = session.query(DiagnosisRow).filter_by(ticket_id=ticket_id).first()
        if existing_diag is not None:
            return  # already persisted; skip to avoid duplicates

        diag_row = DiagnosisRow(
            ticket_id=ticket_id,
            root_cause=diagnosis.root_cause,
            confidence=diagnosis.confidence.value,
        )
        session.add(diag_row)
        session.flush()  # get diag_row.id before adding evidence

        for ev in diagnosis.evidence:
            session.add(EvidenceItemRow(
                diagnosis_id=diag_row.id,
                source_type=ev.source_type.value,
                reference=ev.reference,
                passage=ev.passage,
            ))

        for stage, counts in stage_tokens.items():
            if session.query(StageCountRow).filter_by(ticket_id=ticket_id, stage=stage).first() is None:
                session.add(StageCountRow(
                    ticket_id=ticket_id,
                    stage=stage,
                    input_tokens=counts["input"],
                    output_tokens=counts["output"],
                ))

        session.commit()
