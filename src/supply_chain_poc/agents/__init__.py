from supply_chain_poc.agents.roles import DisruptionAgent, InventoryAgent, ProcurementAgent

AGENT_CLASSES = {
    'disruption': DisruptionAgent,
    'inventory': InventoryAgent,
    'procurement': ProcurementAgent,
}
