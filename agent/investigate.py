"""Investigation — superseded by WorkflowEngine (agent/workflow_engine.py).

The multi-turn tool_use loop that lived here has been replaced by the
deterministic Workflow Engine introduced in ADR 0003.  See:
  - agent/workflow_engine.py  — graph executor
  - agent/flow.py             — flow data model
  - docs/adr/0003-*.md        — decision record
"""


def investigate(*args, **kwargs):
    raise NotImplementedError(
        "investigate() was replaced by WorkflowEngine. "
        "Use agent.workflow_engine.WorkflowEngine instead."
    )
