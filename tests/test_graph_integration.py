"""Parent graph and CLI integration, using temporary SQLite and local HTTP."""
import importlib.util
import json
import unittest
from dataclasses import replace

from supply_chain_poc.config import ShellSettings
from supply_chain_poc.models import AgentContext
from test_business_integration import ROOT, SupplierDatabaseFixture


class GraphIntegrationTests(SupplierDatabaseFixture):
    @unittest.skipUnless(importlib.util.find_spec('langgraph'), 'Install gemini dependencies for graph tests')
    def test_parent_graph_handoffs_and_bound_database_tool(self) -> None:
        from supply_chain_poc.integration.assembly import assemble_agents
        from test_agent_shell import RecordingRuntime
        from supply_chain_poc.integration.workflow import build_workflow
        from supply_chain_poc.runtimes.gemini_runtime import GeminiRuntime
        from langchain_core.messages import AIMessage
        from test_runtime import scripted_model, structured_message

        settings = replace(ShellSettings.load(ROOT / 'config/agents.toml'), database_path=self.database)
        runtime = RecordingRuntime()
        agents = assemble_agents(settings, repository=self.repository, supplier_client=self.client, runtime=runtime)
        result = build_workflow(agents).invoke({'task': 'Assess', 'context': {
            'case_id': 'CASE-GRAPH', 'facts': {'material_id': 'MAT-01', 'shipment_id': 'PO-501',
                'start_date': '2026-11-01', 'days': 5}}, 'results': {}},
            {'configurable': {'thread_id': 'case-missing'}})
        self.assertEqual(set(result['results']), {'disruption', 'inventory'})
        self.assertEqual(result['status'], 'escalated')
        self.assertEqual(list(runtime.calls[-1][0].context.previous_results), [])
        self.assertTrue(all(tools for request, tools in runtime.calls))
        model = scripted_model([
            AIMessage(content='', tool_calls=[{'id': 'sql-1', 'name': 'get_requirements',
                'args': {'material_id': 'MAT-01', 'start_date': '2026-11-01'}, 'type': 'tool_call'}]),
            structured_message('inventory', summary='Computed from active orders.'),
        ])
        live_runtime = GeminiRuntime(settings.model, model=model)
        agents = assemble_agents(settings, repository=self.repository, supplier_client=self.client, runtime=live_runtime)
        agent = agents['inventory']
        request = agent.prepare('Derive demand', AgentContext('CASE-SQL'))
        state = live_runtime.build(request, [agent.tools[name] for name in request.tool_names]).invoke(
            {'messages': [{'role': 'user', 'content': request.user_message}]}, context=request.context)
        tool_result = json.loads(next(message.content for message in state['messages']
                                     if message.type == 'tool' and message.name == 'get_requirements'))
        self.assertEqual(list(tool_result['daily'].values()), [40] * 5)

    def test_successful_structured_workflow_compares_all_real_options(self):
        from supply_chain_poc.core.runtime.base_runtime import AgentRuntime
        from supply_chain_poc.models import AgentResult
        from supply_chain_poc.integration.assembly import assemble_agents
        from supply_chain_poc.integration.workflow import build_workflow

        class EvidenceRuntime(AgentRuntime):
            def invoke(self, request, tools):
                finding = {'role': request.role, 'status': 'ok', 'summary': 'Verified fixture evidence',
                           'evidence_ids': ['PO-501']}
                if request.role == 'disruption':
                    finding.update(shipment_id='PO-501', material_id='MAT-01', quantity=200,
                                   revised_usable_date='2026-11-06')
                elif request.role == 'inventory':
                    finding.update(material_id='MAT-01', first_shortage_date='2026-11-03',
                                   unfulfilled_at_horizon=100, days_below_safety_stock=3)
                else:
                    comparison = request.context.facts['comparison']
                    finding['comparison_snapshot_id'] = comparison['snapshot_id']
                    ids = [row['option_id'] for row in comparison['options']]
                    finding.update(option_ids=ids, recommended_option_id=comparison['recommended_option_id'])
                return AgentResult(request.role, request.context.case_id, finding)

        settings = ShellSettings.load(ROOT / 'config/agents.toml')
        agents = assemble_agents(settings, repository=self.repository, supplier_client=self.client,
                                 runtime=EvidenceRuntime())
        state = build_workflow(agents).invoke({'task': 'Assess fixture', 'results': {}, 'context': {
            'case_id': 'CASE-SUCCESS', 'facts': {'material_id': 'MAT-01', 'shipment_id': 'PO-501',
                'start_date': '2026-11-01', 'days': 5}}}, {'configurable': {'thread_id': 'case-success'}})
        self.assertEqual(set(state['results']), {'disruption', 'inventory', 'procurement'})
        self.assertEqual(len(state['results']['procurement']['option_ids']), 3)
        self.assertEqual(state['status'], 'awaiting_approval')

    def test_integration_entry_point_renders_consequences_without_an_llm(self):
        import io
        import sys
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from supply_chain_poc.integration.__main__ import main

        config = (ROOT / 'config/agents.toml').read_text()
        config = config.replace('../sqlite_supplier_poc/factory.sqlite', str(self.database))
        config = config.replace('http://127.0.0.1:8000', self.client.base_url)
        filename = self.directory / 'test_config.toml'
        filename.write_text(config)
        output = io.StringIO()
        with patch.object(sys, 'argv', ['poc', '--config', str(filename), '--context',
                str(ROOT / 'examples/case_context.json'), '--compare', '--format', 'table']), redirect_stdout(output):
            main()
        self.assertIn('$1,250.00', output.getvalue())
        self.assertIn('late_replacement', output.getvalue())
        self.assertIn('INC-001 [synthetic]', output.getvalue())

