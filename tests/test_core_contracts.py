"""The configurable shell can be exercised without concrete agents or frameworks."""
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from supply_chain_poc.config import RoleSettings, ShellSettings
from supply_chain_poc.core.agents.base_agent import BaseAgent
from supply_chain_poc.core.database.base_repository import BaseFactoryRepository
from supply_chain_poc.core.runtime.base_runtime import AgentRuntime
from supply_chain_poc.core.suppliers.base_supplier_client import BaseSupplierClient
from supply_chain_poc.models import AgentContext, AgentResult

ROOT = Path(__file__).resolve().parents[1]


class DemoAgent(BaseAgent):
    @property
    def role(self):
        return 'demo'


class CapturingRuntime(AgentRuntime):
    def invoke(self, request, tools):
        self.request, self.tools = request, tools
        return AgentResult(request.role, request.context.case_id, {
            'status': 'needs_information', 'summary': 'Shell-only test',
            'unresolved_questions': ['No business assessment was requested.']})


class CoreContractTests(unittest.TestCase):
    def setUp(self):
        settings = ShellSettings.load(ROOT / 'config/agents.toml')
        role = RoleSettings('Investigate the supplied case.', ('grounding',), ('probe',), ())
        self.settings = replace(settings, roles={'demo': role})

    def test_contracts_remain_abstract(self):
        for contract in (BaseAgent, BaseFactoryRepository, AgentRuntime, BaseSupplierClient):
            with self.assertRaises(TypeError):
                contract()

    def test_shell_prepares_configured_tools_and_keeps_facts_out_of_system_prompt(self):
        def probe():
            """Test-only callable."""
            return 1

        agent = DemoAgent(self.settings, tools={'probe': probe}, runtime=CapturingRuntime())
        request = agent.prepare('Investigate', AgentContext('CASE-SHELL', {'marker': 'PRIVATE-FACT'}))
        self.assertEqual(request.tool_names, ('probe',))
        self.assertIn('PRIVATE-FACT', request.user_message)
        self.assertNotIn('PRIVATE-FACT', request.system_prompt)
        self.assertIn('Investigate the supplied case.', request.system_prompt)

    def test_missing_tool_and_invalid_context_stop_before_execution(self):
        agent = DemoAgent(self.settings, tools={}, runtime=CapturingRuntime())
        with self.assertRaisesRegex(ValueError, 'Unregistered'):
            agent.prepare('Investigate', AgentContext('CASE-SHELL'))
        agent = DemoAgent(self.settings, tools={'probe': lambda: 1}, runtime=CapturingRuntime())
        with self.assertRaises(TypeError):
            agent.prepare('Investigate', AgentContext('CASE-SHELL', {'bad': object()}))

    def test_config_rejects_undefined_skill(self):
        source = (ROOT / 'config/agents.toml').read_text()
        source += '\n[agents.demo]\ninstructions="Demo"\nskills=["missing-skill"]\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'agents.toml'
            path.write_text(source)
            with self.assertRaisesRegex(ValueError, 'unknown skills'):
                ShellSettings.load(path)

    def test_config_changes_do_not_require_another_agent_class(self):
        changed = replace(self.settings, skills={'grounding': 'Use supplied record IDs.'})
        agent = DemoAgent(changed, tools={'probe': lambda: 1}, runtime=CapturingRuntime())
        self.assertIn('Use supplied record IDs.', agent.prepare('Investigate', AgentContext('CASE')).system_prompt)
