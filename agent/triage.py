"""Triage gate: call the configured LLM provider once per ticket, return verdicts."""
import json
import os
from collections import Counter

import litellm
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from agent.database import engine, TicketRow, TriageResultRow, StageCountRow
from agent.models import Ticket, TriageResult, TriageVerdict

load_dotenv()

_POLL_INTERVAL = 5  # kept for reference; no longer used

_SYSTEM = """\
You are Scout, a support triage agent for a legacy Java enterprise application
(JavaEE / WebSphere 7, Apache Struts, EJB, Oracle database).

Classify each support ticket and respond with ONLY a JSON object containing:
  "verdict"             – one of: "investigate" | "clarify" | "insufficient_signal" | "out_of_scope"
  "summary"             – 1–2 sentence summary of the ticket
  "clarifying_question" – (required when verdict is "clarify") a specific question to send back to the reporter

Verdict guide:
  investigate        → clear signal; Scout's tools (docs / DB / source code) can likely find the root cause
  clarify            → too vague to investigate; supply a targeted clarifying_question
  insufficient_signal → no useful information even with further questions
  out_of_scope       → clear signal but outside Scout's reach (infra, third-party, network, hardware)

Respond with valid JSON only. No markdown fences, no prose."""


def _user_message(ticket: Ticket) -> str:
    parts = [f"Subject: {ticket.title}"]
    if ticket.description:
        parts.append(f"Description:\n{ticket.description}")
    if ticket.resolution_notes:
        parts.append(f"Resolution notes:\n{ticket.resolution_notes}")
    return "\n\n".join(parts)


def triage_batch(tickets: list[Ticket]) -> list[TriageResult]:
    """Call the configured LLM provider once per ticket, persist + return TriageResults."""
    if not tickets:
        return []

    provider = os.getenv("LLM_PROVIDER")
    if not provider:
        raise EnvironmentError(
            "LLM_PROVIDER is not set. Open Settings in the dashboard to configure a provider."
        )

    model = os.getenv("LLM_MODEL", "")
    results: list[TriageResult] = []

    with Session(engine) as session:
        for ticket in tickets:
            # Upsert ticket row so downstream FK constraints are satisfied
            if session.get(TicketRow, ticket.id) is None:
                session.add(TicketRow(
                    id=ticket.id,
                    title=ticket.title,
                    description=ticket.description,
                    status=ticket.status,
                    created_at=ticket.created_at,
                    resolution_notes=ticket.resolution_notes,
                    source_system=ticket.source_system,
                ))

            try:
                extra = {}
                base_url = os.getenv("LLM_BASE_URL", "")
                if base_url:
                    extra["api_base"] = base_url
                    if "/" not in model:
                        model = f"openai/{model}"
                response = litellm.completion(
                    model=model,
                    max_tokens=512,
                    messages=[
                        {"role": "system", "content": _SYSTEM},
                        {"role": "user", "content": _user_message(ticket)},
                    ],
                    **extra,
                )
                raw_text = response.choices[0].message.content.strip()
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("```", 2)[1]
                    if raw_text.startswith("json"):
                        raw_text = raw_text[4:]
                    raw_text = raw_text.rsplit("```", 1)[0].strip()
                data = json.loads(raw_text)
                triage = TriageResult(
                    ticket_id=ticket.id,
                    verdict=TriageVerdict(data["verdict"]),
                    summary=data.get("summary", ""),
                    clarifying_question=data.get("clarifying_question"),
                )
                input_tokens = response.usage.prompt_tokens
                output_tokens = response.usage.completion_tokens
            except Exception as exc:
                print(f"  [{ticket.id}] triage error ({type(exc).__name__}: {exc})")
                triage = TriageResult(
                    ticket_id=ticket.id,
                    verdict=TriageVerdict.INSUFFICIENT_SIGNAL,
                    summary="(triage error)",
                )
                input_tokens = 0
                output_tokens = 0

            existing_triage = session.query(TriageResultRow).filter_by(ticket_id=ticket.id).first()
            if existing_triage is None:
                session.add(TriageResultRow(
                    ticket_id=ticket.id,
                    verdict=triage.verdict.value,
                    summary=triage.summary,
                    clarifying_question=triage.clarifying_question,
                ))
            existing_stage = session.query(StageCountRow).filter_by(
                ticket_id=ticket.id, stage="triage"
            ).first()
            if existing_stage is None:
                session.add(StageCountRow(
                    ticket_id=ticket.id,
                    stage="triage",
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                ))
            results.append(triage)

        session.commit()

    counts = Counter(r.verdict.value for r in results)
    print("Triage summary: " + " | ".join(f"{v}={n}" for v, n in sorted(counts.items())))
    return results
