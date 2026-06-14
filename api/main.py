from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session

from agent.database import init_db, engine, TicketRow, TriageResultRow, DiagnosisRow, EvidenceItemRow, StageCountRow, ReviewActionRow
from agent.models import TriageVerdict, ReviewAction


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


@app.post("/tickets/{ticket_id}/review")
def submit_review(ticket_id: str, action: ReviewAction):
    with Session(engine) as session:
        row = ReviewActionRow(ticket_id=ticket_id, action=action.value)
        session.add(row)
        session.commit()
    return {"ok": True}
