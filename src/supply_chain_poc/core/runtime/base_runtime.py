from abc import ABC, abstractmethod

from supply_chain_poc.models import AgentRequest, AgentResult, Tool


class AgentRuntime(ABC):
    @abstractmethod
    def invoke(self, request: AgentRequest, tools: list[Tool]) -> AgentResult:
        """Execute a prepared request and return the role's response."""


