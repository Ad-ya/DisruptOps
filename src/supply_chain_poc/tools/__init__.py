from supply_chain_poc.tools.registry import ToolRegistry
from supply_chain_poc.tools.calculations import calculate_material_requirement, calculate_purchase_cost


def default_tool_registry() -> ToolRegistry:
    return ToolRegistry([calculate_material_requirement, calculate_purchase_cost])
