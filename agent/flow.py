import json
from typing import Literal
from pydantic import BaseModel, model_validator

DEFAULT_FLOW_PATH = "data/flow.json"


class ToolNodeConfig(BaseModel):
    mcp: Literal["knowledge_graph", "code_graph", "oracle", "azure_devops"]
    label: str


class BranchEdge(BaseModel):
    target_node_id: str
    condition: Literal["gte_high", "gte_medium", "eq_low", "eq_insufficient", "always"]


class FlowNode(BaseModel):
    id: str
    type: Literal["tool", "branch", "conclude"]
    config: ToolNodeConfig | None = None
    edges: list[BranchEdge] = []


class InvestigationFlow(BaseModel):
    nodes: list[FlowNode]
    entry_node_id: str

    @model_validator(mode="after")
    def _validate_graph(self) -> "InvestigationFlow":
        node_ids = {n.id for n in self.nodes}
        conclude_ids = {n.id for n in self.nodes if n.type == "conclude"}

        if not conclude_ids:
            raise ValueError("Flow must contain at least one Conclude node")

        # BFS reachability check: every reachable node must eventually reach a Conclude
        reachable: set[str] = set()
        queue = [self.entry_node_id]
        while queue:
            current = queue.pop()
            if current in reachable:
                continue
            reachable.add(current)
            node = next((n for n in self.nodes if n.id == current), None)
            if node is None:
                raise ValueError(f"Node '{current}' referenced but not defined")
            for edge in node.edges:
                queue.append(edge.target_node_id)

        # Every non-conclude reachable node must have at least one edge
        for node in self.nodes:
            if node.id not in reachable:
                continue
            if node.type != "conclude" and not node.edges:
                raise ValueError(f"Node '{node.id}' is a dead end — no outgoing edges reach a Conclude node")

        return self


def load_flow(path: str = DEFAULT_FLOW_PATH) -> InvestigationFlow:
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        raise FileNotFoundError(f"Flow file not found: {path}")
    return InvestigationFlow(**data)


def save_flow(flow: InvestigationFlow, path: str = DEFAULT_FLOW_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(flow.model_dump(), f, indent=2)
