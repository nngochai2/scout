"""Triage gate: batch-submit tickets to Haiku via the Batches API, return verdicts."""
import json
import os
import time
from collections import Counter

import anthropic
from dotenv import load_dotenv
from sqlalchemy.orm import Session

from agent.database import engine, TicketRow, TriageResultRow, StageCountRow
from agent.models import Confidence, Ticket, TriageResult, TriageVerdict

load_dotenv()

_MODEL = "claude-haiku-4-5-20251001"
_POLL_INTERVAL = 5  # seconds between status checks

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
    """Submit *tickets* to the Batches API, poll until done, persist + return TriageResults."""
    if not tickets:
        return []

    client = anthropic.Anthropic()

    batch = client.messages.batches.create(
        requests=[
            {
                "custom_id": t.id,
                "params": {
                    "model": _MODEL,
                    "max_tokens": 512,
                    "system": _SYSTEM,
                    "messages": [{"role": "user", "content": _user_message(t)}],
                },
            }
            for t in tickets
        ]
    )
    print(f"Batch {batch.id} submitted ({len(tickets)} tickets)")

    while True:
        batch = client.messages.batches.retrieve(batch.id)
        c = batch.request_counts
        print(
            f"  [{batch.processing_status}] "
            f"processing={c.processing} succeeded={c.succeeded} errored={c.errored}"
        )
        if batch.processing_status == "ended":
            break
        time.sleep(_POLL_INTERVAL)

    by_id = {t.id: t for t in tickets}
    results: list[TriageResult] = []

    with Session(engine) as session:
        for item in client.messages.batches.results(batch.id):
            tid = item.custom_id
            ticket = by_id.get(tid)
            if ticket is None:
                print(f"  [{tid}] unknown custom_id in batch result — skipping")
                continue

            # Upsert the ticket row so diagnosis/stage tables can FK against it
            if session.get(TicketRow, tid) is None:
                session.add(TicketRow(
                    id=tid,
                    title=ticket.title,
                    description=ticket.description,
                    status=ticket.status,
                    created_at=ticket.created_at,
                    resolution_notes=ticket.resolution_notes,
                    source_system=ticket.source_system,
                ))

            if item.result.type != "succeeded":
                print(f"  [{tid}] batch request failed: {item.result}")
                continue

            msg = item.result.message

            try:
                raw_text = msg.content[0].text.strip()
                if raw_text.startswith("```"):
                    raw_text = raw_text.split("```", 2)[1]
                    if raw_text.startswith("json"):
                        raw_text = raw_text[4:]
                    raw_text = raw_text.rsplit("```", 1)[0].strip()
                data = json.loads(raw_text)
                triage = TriageResult(
                    ticket_id=tid,
                    verdict=TriageVerdict(data["verdict"]),
                    summary=data.get("summary", ""),
                    clarifying_question=data.get("clarifying_question"),
                )
            except Exception as exc:
                raw = msg.content[0].text if msg.content else "(empty)"
                print(f"  [{tid}] parse error ({type(exc).__name__}: {exc}): {raw[:200]}")
                triage = TriageResult(
                    ticket_id=tid,
                    verdict=TriageVerdict.INSUFFICIENT_SIGNAL,
                    summary="(triage parse error)",
                )

            existing_triage = session.query(TriageResultRow).filter_by(ticket_id=tid).first()
            if existing_triage is None:
                session.add(TriageResultRow(
                    ticket_id=tid,
                    verdict=triage.verdict.value,
                    summary=triage.summary,
                    clarifying_question=triage.clarifying_question,
                ))
            existing_stage = session.query(StageCountRow).filter_by(ticket_id=tid, stage="triage").first()
            if existing_stage is None:
                session.add(StageCountRow(
                    ticket_id=tid,
                    stage="triage",
                    input_tokens=msg.usage.input_tokens,
                    output_tokens=msg.usage.output_tokens,
                ))
            results.append(triage)

        session.commit()

    counts = Counter(r.verdict.value for r in results)
    print("Triage summary: " + " | ".join(f"{v}={n}" for v, n in sorted(counts.items())))
    return results
