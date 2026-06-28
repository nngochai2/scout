"""Tests for triage_batch — multi-provider LLM behavior."""
import json
import types

import litellm
import pytest
from sqlalchemy import create_engine

import agent.triage as triage_module
from agent.database import Base
from agent.models import Ticket, TriageVerdict
from agent.triage import triage_batch


def _ticket(tid="T1"):
    return Ticket(id=tid, title="Login fails", description="Cannot log in after reset.")


def _fake_completion(verdict="investigate", summary="Auth issue."):
    payload = json.dumps({"verdict": verdict, "summary": summary})
    msg = types.SimpleNamespace(content=payload)
    choice = types.SimpleNamespace(message=msg)
    usage = types.SimpleNamespace(prompt_tokens=100, completion_tokens=50)
    return types.SimpleNamespace(choices=[choice], usage=usage)


@pytest.fixture
def mem_db(monkeypatch):
    mem_engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(mem_engine)
    monkeypatch.setattr(triage_module, "engine", mem_engine)
    return mem_engine


def test_triage_batch_raises_when_provider_not_configured(monkeypatch):
    monkeypatch.delenv("LLM_PROVIDER", raising=False)
    with pytest.raises(EnvironmentError, match="LLM_PROVIDER"):
        triage_batch([_ticket()])


def test_triage_batch_returns_results_for_each_ticket(monkeypatch, mem_db):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("LLM_MODEL", "claude-haiku-4-5-20251001")
    monkeypatch.setattr(litellm, "completion", lambda **kw: _fake_completion())

    results = triage_batch([_ticket("T1"), _ticket("T2")])

    assert len(results) == 2
    assert all(r.verdict == TriageVerdict.INVESTIGATE for r in results)
    assert all(r.summary == "Auth issue." for r in results)
