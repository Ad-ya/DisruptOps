from supply_chain_poc.agents import AGENT_CLASSES
from supply_chain_poc.config import ShellSettings
from supply_chain_poc.core.agents.base_agent import BaseAgent
from supply_chain_poc.core.database.base_repository import BaseFactoryRepository
from supply_chain_poc.core.runtime.base_runtime import AgentRuntime
from supply_chain_poc.core.suppliers.base_supplier_client import BaseSupplierClient
from supply_chain_poc.database.sqlite_repository import SQLiteFactoryRepository
from supply_chain_poc.runtimes.gemini_runtime import GeminiRuntime
from supply_chain_poc.suppliers.http_supplier_client import HttpSupplierClient
from supply_chain_poc.tools import default_tool_registry
from supply_chain_poc.tools.business import BusinessTools
from supply_chain_poc.services.comparison import ComparisonService


def assemble_agents(settings: ShellSettings, *, runtime: AgentRuntime | None = None,
                    repository: BaseFactoryRepository | None = None,
                    supplier_client: BaseSupplierClient | None = None) -> dict[str, BaseAgent]:
    repository = repository if repository is not None else SQLiteFactoryRepository(settings.database_path)
    supplier_client = supplier_client if supplier_client is not None else HttpSupplierClient(
        settings.supplier_api_url, settings.supplier_api_timeout)
    business = BusinessTools(repository, supplier_client)
    comparison = ComparisonService(repository, supplier_client, settings.comparison)
    registry = default_tool_registry()
    for tool in (repository.get_material_context, repository.get_shipment, repository.get_requirements,
                 repository.supplier_history, supplier_client.get_supplier_update,
                 supplier_client.get_alternative_offers, business.price_purchase, business.project_stock,
                 repository.find_past_incidents, comparison.compare_options):
        registry.register(tool)
    agents = {name: cls(settings, tools=registry,
                        runtime=runtime if runtime is not None else GeminiRuntime(settings.model))
              for name, cls in AGENT_CLASSES.items()}
    for agent in agents.values():
        registry.resolve(settings.roles[agent.role].tools)
    return agents
