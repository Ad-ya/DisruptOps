from __future__ import annotations

import logging

from langchain.agents.middleware import AgentMiddleware, AgentState, ModelCallLimitMiddleware
from langgraph.runtime import Runtime

from supply_chain_poc.models import AgentContext

logger = logging.getLogger(__name__)


class AuditMiddleware(AgentMiddleware):
    def __init__(self, role: str) -> None:
        self.role = role

    def before_agent(self, state: AgentState, runtime: Runtime[AgentContext]) -> None:
        logger.info('agent_started role=%s case_id=%s', self.role, runtime.context.case_id)

    def after_agent(self, state: AgentState, runtime: Runtime[AgentContext]) -> None:
        logger.info('agent_finished role=%s case_id=%s messages=%s',
                    self.role, runtime.context.case_id, len(state['messages']))


def build_middleware(names: tuple[str, ...], max_model_calls: int, role: str) -> list[AgentMiddleware]:
    factories = {
        'audit': lambda: AuditMiddleware(role),
        'model_call_limit': lambda: ModelCallLimitMiddleware(run_limit=max_model_calls, exit_behavior='error'),
    }
    return [factories[name]() for name in names]
