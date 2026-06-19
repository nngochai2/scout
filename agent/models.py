from enum import Enum
from datetime import datetime
from pydantic import BaseModel


class TriageVerdict(str, Enum):
    INVESTIGATE = "investigate"
    CLARIFY = "clarify"
    INSUFFICIENT_SIGNAL = "insufficient_signal"
    OUT_OF_SCOPE = "out_of_scope"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INSUFFICIENT = "insufficient"


class EvidenceType(str, Enum):
    DOC = "DOC"
    DB = "DB"
    CODE = "CODE"
    ADO = "ADO"


class InvestigationStage(str, Enum):
    TRIAGE = "triage"
    DOCS = "docs"
    DB = "db"
    CODE = "code"


class ReviewAction(str, Enum):
    APPROVE = "approve"
    DISMISS_INCORRECT = "dismiss_incorrect"
    DISMISS_WONT_ACT = "dismiss_wont_act"
    ACKNOWLEDGE = "acknowledge"  # for Clarify tickets


class Ticket(BaseModel):
    id: str
    title: str
    description: str | None = None
    status: str | None = None
    created_at: datetime | None = None
    resolution_notes: str | None = None
    source_system: str = "freshdesk"


class Evidence(BaseModel):
    source_type: EvidenceType
    reference: str   # e.g. "requirements.docx:p3", "T_ORDERS WHERE ORDER_ID=8821", "com/example/Foo.java:142"
    passage: str


class Diagnosis(BaseModel):
    ticket_id: str
    root_cause: str | None = None
    confidence: Confidence
    evidence: list[Evidence] = []
    triage_verdict: TriageVerdict


class StageCount(BaseModel):
    ticket_id: str
    stage: InvestigationStage
    input_tokens: int
    output_tokens: int


class TriageResult(BaseModel):
    ticket_id: str
    verdict: TriageVerdict
    summary: str
    clarifying_question: str | None = None  # populated when verdict is CLARIFY
