"""Offline contract tests: no Gemini key and no network calls."""
import json
import unittest
from dataclasses import replace
from pathlib import Path

from supply_chain_poc.agents import AGENT_CLASSES, InventoryAgent
from supply_chain_poc.core.agents.base_agent import BaseAgent
from supply_chain_poc.config import ShellSettings
from supply_chain_poc.models import AgentContext, AgentRequest, AgentResult, Tool
from supply_chain_poc.core.runtime.base_runtime import AgentRuntime
from supply_chain_poc.tools import ToolRegistry, calculate_material_requirement, calculate_purchase_cost

ROOT = Path(__file__).resolve().parents[1]


class RecordingRuntime(AgentRuntime):
    def __init__(self) -> None:
        self.calls = []

    def invoke(self, request: AgentRequest, tools: list[Tool]) -> AgentResult:
        self.calls.append((request, tools))
        finding = {'role': request.role, 'status': 'needs_information', 'summary': 'Offline test response',
                   'unresolved_questions': ['Scripted runtime has not assessed business evidence.']}
        return AgentResult(request.role, request.context.case_id, finding)


class ShellTests(unittest.TestCase):
    def setUp(self) -> None:
        self.settings = ShellSettings.load(ROOT / 'config/agents.toml')
        registry = ToolRegistry()
        for name in {tool for role in self.settings.roles.values() for tool in role.tools}:
            def stub_tool():
                """Named test tool; no external side effects."""
            stub_tool.__name__ = name
            registry.register(stub_tool)
        self.agents = {name: cls(self.settings, tools=registry, runtime=RecordingRuntime())
                       for name, cls in AGENT_CLASSES.items()}

    def make_agent(self, settings=None, runtime=None, tools=None):
        return InventoryAgent(settings or self.settings,
                              tools=tools if tools is not None else self.agents['inventory'].tools,
                              runtime=runtime if runtime is not None else RecordingRuntime())

    def test_abstract_contracts_cannot_be_instantiated(self) -> None:
        with self.assertRaises(TypeError):
            BaseAgent(self.settings)
        with self.assertRaises(TypeError):
            AgentRuntime()

    def test_all_three_roles_have_distinct_configuration(self) -> None:
        prompts = []
        for role, cls in AGENT_CLASSES.items():
            request = self.agents[role].prepare('Investigate', AgentContext('CASE-1'))
            self.assertEqual(request.role, role)
            prompts.append(request.system_prompt)
        self.assertEqual(len(set(prompts)), 3)

    def test_config_changes_skill_without_changing_agent_class(self) -> None:
        settings = replace(self.settings, skills={**self.settings.skills, 'grounding': 'NEW GROUNDING RULE'})
        request = self.make_agent(settings=settings).prepare('Investigate', AgentContext('CASE-1'))
        self.assertIn('NEW GROUNDING RULE', request.system_prompt)

    def test_context_does_not_leak_between_cases_or_enter_system_prompt(self) -> None:
        runtime = RecordingRuntime()
        agent = self.make_agent(runtime=runtime)
        agent.run('Inspect', AgentContext('CASE-1', {'marker': 'PRIVATE_CASE_ONE'}))
        result = agent.run('Inspect', AgentContext('CASE-2', {'marker': 'CASE_TWO'}))
        self.assertEqual(result.case_id, 'CASE-2')
        self.assertNotIn('PRIVATE_CASE_ONE', runtime.calls[1][0].user_message)
        self.assertNotIn('PRIVATE_CASE_ONE', runtime.calls[0][0].system_prompt)
        self.assertEqual([tool.__name__ for tool in runtime.calls[0][1]], list(self.settings.roles['inventory'].tools))

    def test_unknown_tool_fails_before_runtime(self) -> None:
        runtime = RecordingRuntime()
        agent = self.make_agent(tools=ToolRegistry(), runtime=runtime)
        with self.assertRaisesRegex(ValueError, 'Unregistered'):
            agent.run('Inspect', AgentContext('CASE-1'))
        self.assertEqual(runtime.calls, [])

    def test_calculators_use_remaining_work_and_integer_cents(self) -> None:
        self.assertEqual(calculate_material_requirement(10, 3, 2), 14)
        self.assertEqual(calculate_purchase_cost(100, 1200, 5000)['total_cents'], 125000)
        for args in [(10, 11, 2), (-1, 0, 1), (True, 0, 1)]:
            with self.assertRaises(ValueError):
                calculate_material_requirement(*args)
        with self.assertRaises(ValueError):
            calculate_purchase_cost(100, -1)

    def test_context_must_be_json_serializable(self) -> None:
        with self.assertRaises(TypeError):
            self.make_agent().prepare('Inspect', AgentContext('CASE-1', {'bad': object()}))
        with self.assertRaises(ValueError):
            self.make_agent().prepare('Inspect', AgentContext('CASE-1', {'bad': float('nan')}))

    def test_empty_task_rejected(self) -> None:
        with self.assertRaises(ValueError):
            self.make_agent().prepare(' ', AgentContext('CASE-1'))

    def test_example_context_loads(self) -> None:
        context = AgentContext(**json.loads((ROOT / 'examples/case_context.json').read_text()))
        self.assertEqual(context.case_id, 'CASE-SHELL-001')


if __name__ == '__main__':
    unittest.main()
