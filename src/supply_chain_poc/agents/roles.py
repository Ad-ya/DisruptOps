from supply_chain_poc.core.agents.base_agent import BaseAgent


class DisruptionAgent(BaseAgent):
    @property
    def role(self) -> str:
        return 'disruption'


class InventoryAgent(BaseAgent):
    @property
    def role(self) -> str:
        return 'inventory'


class ProcurementAgent(BaseAgent):
    @property
    def role(self) -> str:
        return 'procurement'
