"""Parallel assessment, a barrier join, then recommendation and human approval."""
from typing import NotRequired, TypedDict

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from supply_chain_poc.config import WorkflowSettings
from supply_chain_poc.core.agents.base_agent import BaseAgent
from supply_chain_poc.integration.nodes import ROLE_ORDER, WorkflowNodes, utc_now


class WorkflowState(TypedDict):
    task: str
    context: dict
    results: dict[str, dict]
    workflow_version: NotRequired[int]
    disruption_outcome: NotRequired[dict | None]
    inventory_outcome: NotRequired[dict | None]
    comparison: NotRequired[dict | None]
    thread_id: NotRequired[str]
    status: NotRequired[str]
    route: NotRequired[str]
    revision_count: NotRequired[int]
    comparison_version: NotRequired[int]
    revision_feedback: NotRequired[dict]
    approval_presented_at: NotRequired[str | None]
    approval_expires_at: NotRequired[str | None]
    selection: NotRequired[dict | None]
    decision: NotRequired[dict | None]
    reason: NotRequired[str]
    events: NotRequired[list[dict]]


def build_workflow(agents: dict[str, BaseAgent], *, settings: WorkflowSettings | None = None,
                   checkpointer=None, clock=utc_now):
    nodes = WorkflowNodes(agents, settings or WorkflowSettings(), clock)
    builder = StateGraph(WorkflowState)
    builder.add_node('begin', nodes.begin)
    builder.add_node('assess', nodes.assess)
    for name in ROLE_ORDER:
        builder.add_node(name, nodes.agent_node(name))
    for name, function in {
        'compare_options': nodes.compare,
        'refresh_before_approval': nodes.refresh_before_approval,
        'prepare_approval': nodes.prepare_approval,
        'human_approval': nodes.human_approval,
        'final_validation': nodes.final_validation,
        'reject': nodes.reject, 'escalate': nodes.escalate,
    }.items():
        builder.add_node(name, function)
    builder.add_edge(START, 'begin')
    builder.add_edge('begin', 'assess')
    # Both branches run in the same superstep and write different state keys.
    builder.add_edge('assess', 'disruption')
    builder.add_edge('assess', 'inventory')
    # A list creates a barrier: compare only after BOTH branches complete.
    builder.add_edge(['disruption', 'inventory'], 'compare_options')
    routes = {
        'compare_options': ('procurement', 'assess', 'escalate'),
        'procurement': ('refresh_before_approval', 'procurement', 'escalate'),
        'refresh_before_approval': ('prepare_approval', 'assess', 'escalate'),
        'human_approval': ('human_approval', 'procurement', 'reject', 'final_validation', 'escalate'),
        'final_validation': ('finish', 'assess', 'escalate'),
    }
    for name, destinations in routes.items():
        builder.add_conditional_edges(name, lambda state: state['route'],
                                      {target: END if target == 'finish' else target for target in destinations})
    builder.add_edge('prepare_approval', 'human_approval')
    builder.add_edge('reject', END)
    builder.add_edge('escalate', END)
    return builder.compile(checkpointer=checkpointer if checkpointer is not None else InMemorySaver())
