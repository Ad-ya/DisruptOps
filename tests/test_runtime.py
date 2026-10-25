"""Exercise the real LangGraph tool loop with scripted model responses, never Gemini."""
import importlib.util
import unittest
from dataclasses import replace
from pathlib import Path

from supply_chain_poc.agents import InventoryAgent
from supply_chain_poc.config import ShellSettings
from supply_chain_poc.models import AgentContext
from supply_chain_poc.runtimes.gemini_runtime import GeminiRuntime
from supply_chain_poc.tools import ToolRegistry, default_tool_registry, calculate_material_requirement as real_requirement

ROOT = Path(__file__).resolve().parents[1]


def scripted_model(responses):
    from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel

    class ToolCallingModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    return ToolCallingModel(responses=responses)


def structured_message(role, **values):
    from langchain_core.messages import AIMessage
    from supply_chain_poc.schemas.findings import FINDING_SCHEMAS
    finding = {'status': 'needs_information', 'summary': 'Scripted finding',
               'unresolved_questions': ['Full case evidence is not evaluated by this test.'], **values}
    return AIMessage(content='', tool_calls=[{'id': 'finding-1', 'name': FINDING_SCHEMAS[role].__name__,
                                              'args': finding, 'type': 'tool_call'}])


@unittest.skipUnless(importlib.util.find_spec('langchain'), 'Install the gemini extra for runtime tests')
class RuntimeTests(unittest.TestCase):
    def setUp(self) -> None:
        settings = ShellSettings.load(ROOT / 'config/agents.toml')
        role = replace(settings.roles['inventory'], tools=('calculate_material_requirement',))
        self.settings = replace(settings, roles={**settings.roles, 'inventory': role})

    def test_real_tool_loop_and_audit_middleware_without_network(self) -> None:
        from langchain_core.messages import AIMessage

        observed_results = []

        def calculate_material_requirement(scheduled_quantity: int, completed_quantity: int,
                                           quantity_per_product: int) -> int:
            """Calculate remaining material units and observe execution in this test."""
            value = real_requirement(scheduled_quantity, completed_quantity, quantity_per_product)
            observed_results.append(value)
            return value

        model = scripted_model([
            AIMessage(content='', tool_calls=[{
                'name': 'calculate_material_requirement',
                'args': {'scheduled_quantity': 10, 'completed_quantity': 3, 'quantity_per_product': 2},
                'id': 'call-1', 'type': 'tool_call',
            }]),
            structured_message('inventory', summary='14 material units remain.'),
        ])
        runtime = GeminiRuntime(self.settings.model, model=model)
        agent = InventoryAgent(self.settings, runtime=runtime,
                               tools=ToolRegistry([calculate_material_requirement]))
        with self.assertLogs('supply_chain_poc.middleware', level='INFO') as logs:
            result = agent.run('Calculate remaining demand', AgentContext('CASE-TEST'))
        self.assertEqual(result.text, '14 material units remain.')
        self.assertEqual(observed_results, [14])
        self.assertIn('role=inventory case_id=CASE-TEST', logs.output[0])
        self.assertEqual(model.i, 0)  # Two responses consumed; fake model wraps its response index.

    def test_model_budget_stops_a_repeated_tool_call(self) -> None:
        from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
        from langchain_core.messages import AIMessage

        settings = replace(self.settings, max_model_calls=1)
        model = scripted_model([AIMessage(content='', tool_calls=[{
            'name': 'calculate_material_requirement',
            'args': {'scheduled_quantity': 1, 'completed_quantity': 0, 'quantity_per_product': 1},
            'id': 'call-repeat', 'type': 'tool_call',
        }])])
        agent = InventoryAgent(settings, tools=default_tool_registry(), runtime=GeminiRuntime(settings.model, model=model))
        with self.assertRaises(ModelCallLimitExceededError):
            agent.run('Repeat calculations', AgentContext('CASE-LIMIT'))

    def test_google_adapter_constructs_with_configured_options(self) -> None:
        import os
        from unittest.mock import patch

        with patch.dict(os.environ, {'GOOGLE_API_KEY': 'test-key-not-a-real-secret'}):
            model = GeminiRuntime(self.settings.model).model
        self.assertEqual(model.model.removeprefix('models/'), self.settings.model.name)

    def test_invalid_structured_output_is_not_accepted_as_free_text(self) -> None:
        from langchain.agents.structured_output import StructuredOutputValidationError

        model = scripted_model([structured_message('inventory', unfulfilled_at_horizon=-1)])
        agent = InventoryAgent(self.settings, tools=default_tool_registry(),
                               runtime=GeminiRuntime(self.settings.model, model=model))
        with self.assertRaises(StructuredOutputValidationError):
            agent.run('Assess', AgentContext('CASE-INVALID'))
