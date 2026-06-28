"""Tests for WorkflowEngine — behaviors 1-5."""
import json

import pytest
from pydantic import ValidationError

from agent.flow import InvestigationFlow, FlowNode, BranchEdge, ToolNodeConfig
from agent.models import Confidence, Evidence, EvidenceType, Ticket, TriageResult, TriageVerdict
from agent.workflow_engine import WorkflowEngine, EvaluateResult, StageRecord


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ticket(tid="T1") -> Ticket:
    return Ticket(id=tid, title="Login fails", description="Cannot log in after reset.")


def _triage(tid="T1") -> TriageResult:
    return TriageResult(ticket_id=tid, verdict=TriageVerdict.INVESTIGATE, summary="Likely auth bug.")


def _evidence() -> Evidence:
    return Evidence(source_type=EvidenceType.DOC, reference="auth.md:p3", passage="Token expires on reset.")


def _eval_high(root_cause="Token cache race condition") -> EvaluateResult:
    return EvaluateResult(
        confidence=Confidence.HIGH,
        root_cause=root_cause,
        evidence=[_evidence()],
        input_tokens=100,
        output_tokens=50,
    )


def _eval_insufficient() -> EvaluateResult:
    return EvaluateResult(
        confidence=Confidence.INSUFFICIENT,
        root_cause=None,
        evidence=[],
        input_tokens=80,
        output_tokens=20,
    )


def _simple_flow(mcp="knowledge_graph", label="Search docs") -> InvestigationFlow:
    """Tool Node → Conclude (single step, always edge)."""
    return InvestigationFlow(
        entry_node_id="n1",
        nodes=[
            FlowNode(
                id="n1", type="tool",
                config=ToolNodeConfig(mcp=mcp, label=label),
                edges=[BranchEdge(target_node_id="conclude", condition="always")],
            ),
            FlowNode(id="conclude", type="conclude"),
        ],
    )


# ---------------------------------------------------------------------------
# Behavior 1: single-tool flow with injected callables → correct Diagnosis
# ---------------------------------------------------------------------------

def test_single_tool_flow_produces_correct_diagnosis():
    flow = _simple_flow()
    engine = WorkflowEngine(
        flow=flow,
        mcp_fns={"knowledge_graph": lambda ctx: "doc passage about auth"},
        evaluate_fn=lambda ctx, label, result: _eval_high(),
    )
    diagnosis, stage_records = engine.investigate(_ticket(), _triage())

    assert diagnosis.confidence == Confidence.HIGH
    assert diagnosis.root_cause == "Token cache race condition"
    assert len(diagnosis.evidence) == 1
    assert len(stage_records) == 1
    assert stage_records[0].stage == "Search docs"
    assert stage_records[0].input_tokens == 100
    assert stage_records[0].output_tokens == 50


# ---------------------------------------------------------------------------
# Behavior 2: stop-on-sufficient — HIGH routes to Conclude, n2 never visited
# ---------------------------------------------------------------------------

def test_high_confidence_routes_to_conclude_skipping_remaining_nodes():
    flow = InvestigationFlow(
        entry_node_id="n1",
        nodes=[
            FlowNode(
                id="n1", type="tool",
                config=ToolNodeConfig(mcp="knowledge_graph", label="KG search"),
                edges=[
                    BranchEdge(target_node_id="conclude", condition="gte_high"),
                    BranchEdge(target_node_id="n2", condition="always"),
                ],
            ),
            FlowNode(
                id="n2", type="tool",
                config=ToolNodeConfig(mcp="code_graph", label="Code search"),
                edges=[BranchEdge(target_node_id="conclude", condition="always")],
            ),
            FlowNode(id="conclude", type="conclude"),
        ],
    )

    n2_called = []

    def mcp_code(ctx):
        n2_called.append(True)
        return "code result"

    engine = WorkflowEngine(
        flow=flow,
        mcp_fns={
            "knowledge_graph": lambda ctx: "kg result",
            "code_graph": mcp_code,
        },
        evaluate_fn=lambda ctx, label, result: _eval_high(),
    )
    diagnosis, stage_records = engine.investigate(_ticket(), _triage())

    assert diagnosis.confidence == Confidence.HIGH
    assert len(stage_records) == 1          # only n1 visited
    assert stage_records[0].stage == "KG search"
    assert n2_called == []                  # n2 was never reached


# ---------------------------------------------------------------------------
# Behavior 3: all Tool Nodes return INSUFFICIENT → Diagnosis confidence=INSUFFICIENT
# ---------------------------------------------------------------------------

def test_all_insufficient_produces_insufficient_diagnosis():
    flow = InvestigationFlow(
        entry_node_id="n1",
        nodes=[
            FlowNode(
                id="n1", type="tool",
                config=ToolNodeConfig(mcp="knowledge_graph", label="KG search"),
                edges=[BranchEdge(target_node_id="n2", condition="always")],
            ),
            FlowNode(
                id="n2", type="tool",
                config=ToolNodeConfig(mcp="code_graph", label="Code search"),
                edges=[BranchEdge(target_node_id="conclude", condition="always")],
            ),
            FlowNode(id="conclude", type="conclude"),
        ],
    )
    engine = WorkflowEngine(
        flow=flow,
        mcp_fns={
            "knowledge_graph": lambda ctx: "nothing useful",
            "code_graph": lambda ctx: "nothing useful",
        },
        evaluate_fn=lambda ctx, label, result: _eval_insufficient(),
    )
    diagnosis, stage_records = engine.investigate(_ticket(), _triage())

    assert diagnosis.confidence == Confidence.INSUFFICIENT
    assert diagnosis.root_cause is None
    assert len(stage_records) == 2


# ---------------------------------------------------------------------------
# Behavior 4: cyclic flow hits MAX_NODE_VISITS → INSUFFICIENT, no infinite loop
# ---------------------------------------------------------------------------

def test_cyclic_flow_terminates_at_max_node_visits():
    # Build a self-cycling flow bypassing validation — simulates a misconfigured graph
    cyclic_node = FlowNode.model_construct(
        id="n1", type="tool",
        config=ToolNodeConfig(mcp="knowledge_graph", label="Loop node"),
        edges=[BranchEdge(target_node_id="n1", condition="always")],  # loops to itself
    )
    conclude = FlowNode.model_construct(id="conclude", type="conclude", config=None, edges=[])
    flow = InvestigationFlow.model_construct(
        entry_node_id="n1",
        nodes=[cyclic_node, conclude],
    )

    visits = []

    def counting_mcp(ctx):
        visits.append(1)
        return "result"

    engine = WorkflowEngine(
        flow=flow,
        mcp_fns={"knowledge_graph": counting_mcp},
        evaluate_fn=lambda ctx, label, result: _eval_insufficient(),
    )
    diagnosis, stage_records = engine.investigate(_ticket(), _triage())

    assert diagnosis.confidence == Confidence.INSUFFICIENT
    assert stage_records == []              # guard path returns empty records
    assert len(visits) == 20               # ran exactly MAX_NODE_VISITS times


# ---------------------------------------------------------------------------
# Behavior 5: two Tool Nodes → two StageRecords with correct names and token counts
# ---------------------------------------------------------------------------

def test_stage_records_per_tool_node_with_correct_names_and_tokens():
    flow = InvestigationFlow(
        entry_node_id="n1",
        nodes=[
            FlowNode(
                id="n1", type="tool",
                config=ToolNodeConfig(mcp="knowledge_graph", label="KG search"),
                edges=[BranchEdge(target_node_id="n2", condition="always")],
            ),
            FlowNode(
                id="n2", type="tool",
                config=ToolNodeConfig(mcp="oracle", label="DB query"),
                edges=[BranchEdge(target_node_id="conclude", condition="always")],
            ),
            FlowNode(id="conclude", type="conclude"),
        ],
    )

    def fake_evaluate(ctx, label, result):
        return EvaluateResult(
            confidence=Confidence.MEDIUM,
            root_cause="something",
            evidence=[],
            input_tokens={"KG search": 10, "DB query": 20}[label],
            output_tokens={"KG search": 5, "DB query": 8}[label],
        )

    engine = WorkflowEngine(
        flow=flow,
        mcp_fns={
            "knowledge_graph": lambda ctx: "kg result",
            "oracle": lambda ctx: "db result",
        },
        evaluate_fn=fake_evaluate,
    )
    _, stage_records = engine.investigate(_ticket(), _triage())

    assert len(stage_records) == 2
    kg, db = stage_records
    assert kg.stage == "KG search"
    assert kg.input_tokens == 10
    assert kg.output_tokens == 5
    assert db.stage == "DB query"
    assert db.input_tokens == 20
    assert db.output_tokens == 8
