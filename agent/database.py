import os
from sqlalchemy import (
    create_engine, Column, String, Integer, Text, DateTime, ForeignKey, func
)
from sqlalchemy.orm import DeclarativeBase, relationship, Session

DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/scout.db")
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})


class Base(DeclarativeBase):
    pass


class TicketRow(Base):
    __tablename__ = "tickets"

    id = Column(String, primary_key=True)
    title = Column(Text, nullable=False)
    description = Column(Text)
    status = Column(String)
    created_at = Column(DateTime)
    resolution_notes = Column(Text)
    source_system = Column(String, default="freshdesk")

    triage_result = relationship("TriageResultRow", back_populates="ticket", uselist=False)
    diagnosis = relationship("DiagnosisRow", back_populates="ticket", uselist=False)
    stage_counts = relationship("StageCountRow", back_populates="ticket")
    review_action = relationship("ReviewActionRow", back_populates="ticket", uselist=False)


class TriageResultRow(Base):
    __tablename__ = "triage_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False)
    verdict = Column(String, nullable=False)
    summary = Column(Text)
    clarifying_question = Column(Text)
    created_at = Column(DateTime, server_default=func.now())

    ticket = relationship("TicketRow", back_populates="triage_result")


class DiagnosisRow(Base):
    __tablename__ = "diagnoses"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False)
    root_cause = Column(Text)
    confidence = Column(String, nullable=False)
    created_at = Column(DateTime, server_default=func.now())

    ticket = relationship("TicketRow", back_populates="diagnosis")
    evidence_items = relationship("EvidenceItemRow", back_populates="diagnosis")


class EvidenceItemRow(Base):
    __tablename__ = "evidence_items"

    id = Column(Integer, primary_key=True, autoincrement=True)
    diagnosis_id = Column(Integer, ForeignKey("diagnoses.id"), nullable=False)
    source_type = Column(String, nullable=False)  # DOC, DB, CODE
    reference = Column(Text, nullable=False)
    passage = Column(Text)

    diagnosis = relationship("DiagnosisRow", back_populates="evidence_items")


class StageCountRow(Base):
    __tablename__ = "stage_counts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False)
    stage = Column(String, nullable=False)  # triage, docs, db, code
    input_tokens = Column(Integer, nullable=False)
    output_tokens = Column(Integer, nullable=False)

    ticket = relationship("TicketRow", back_populates="stage_counts")


class ReviewActionRow(Base):
    __tablename__ = "review_actions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    ticket_id = Column(String, ForeignKey("tickets.id"), nullable=False)
    action = Column(String, nullable=False)  # approve, dismiss_incorrect, dismiss_wont_act, acknowledge
    created_at = Column(DateTime, server_default=func.now())

    ticket = relationship("TicketRow", back_populates="review_action")


def init_db() -> None:
    os.makedirs("data", exist_ok=True)
    Base.metadata.create_all(engine)


def get_session() -> Session:
    return Session(engine)
