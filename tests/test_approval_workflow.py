"""Conditional graph and SQLite pause/resume tests, using real local supplier HTTP."""
import json
import os
import subprocess
import sys
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from supply_chain_poc.config import ShellSettings
from supply_chain_poc.integration.assembly import assemble_agents
from supply_chain_poc.integration.runner import WorkflowRunner
from supply_chain_poc.models import AgentContext
from test_business_integration import ROOT, SupplierDatabaseFixture
from workflow_fixtures import EvidenceRuntime


class ApprovalWorkflowTests(SupplierDatabaseFixture):
    def setUp(self):
        super().setUp()
        self.settings = replace(ShellSettings.load(ROOT / 'config/agents.toml'),
                                database_path=self.database, checkpoint_path=self.directory / 'cases.sqlite')
        self.context = AgentContext('CASE-LOCAL', {'material_id': 'MAT-01', 'shipment_id': 'PO-501',
                                                 'start_date': '2026-11-01', 'days': 5})
        self.runtime = EvidenceRuntime()

    def runner(self, runtime=None, clock=None):
        agents = assemble_agents(self.settings, repository=self.repository, supplier_client=self.client,
                                 runtime=runtime or self.runtime)
        return WorkflowRunner(self.settings, agents, **({'clock': clock} if clock else {}))

    def start(self, runner=None, thread='test-case'):
        return (runner or self.runner()).start(thread, 'Assess the disruption', self.context)

    def test_pause_survives_reopen_and_approval_does_not_rerun_agents(self):
        pending = self.start()
        self.assertEqual(pending['status'], 'awaiting_approval')
        self.assertEqual(self.runner().status('test-case')['comparison']['snapshot_id'], pending['comparison']['snapshot_id'])
        before = list(self.runtime.calls)
        decision = {**pending['decision_template'], 'reviewer_id': 'local-tester'}
        approved = self.runner().resume('test-case', decision)
        self.assertEqual(approved['status'], 'approved')
        self.assertEqual(approved['decision']['reviewer_id'], 'local-tester')
        self.assertEqual(self.runtime.calls, before)
        self.assertEqual(self.repository.get_material_context('MAT-01')['inventory']['usable_quantity'], 100)
        with self.assertRaises(ValueError):
            self.runner().resume('test-case', decision)
        with self.assertRaises(ValueError):
            self.start()

    def test_summary_displays_the_human_selected_plan_and_execution_scope(self):
        from supply_chain_poc.integration.comparison_view import render_case

        choices = [
            ('bridge:QUOTE-B:100', '100 units from SUP-B', 'USD $1,250.00'),
            ('protect_buffer:QUOTE-B:120', '120 units from SUP-B', 'USD $1,490.00'),
            ('wait', 'no replacement purchase selected', None),
        ]
        for index, (option_id, expected_plan, expected_cost) in enumerate(choices):
            with self.subTest(option_id=option_id):
                thread_id = f'selected-plan-{index}'
                runner = self.runner()
                pending = self.start(runner, thread=thread_id)
                approved = runner.resume(thread_id, {**pending['decision_template'], 'option_id': option_id})
                summary = render_case(approved).split('Case material:', 1)[0]
                self.assertEqual(approved['status'], 'approved')
                self.assertIn(f'[{option_id}]', summary)
                self.assertIn(expected_plan, summary)
                self.assertIn('Execution scope: Decision record only; no purchase order placed.', summary)
                if expected_cost:
                    self.assertIn(expected_cost, summary)
                else:
                    self.assertNotIn('Approved purchase plan:', summary)

    def test_wrong_thread_snapshot_version_option_or_ack_cannot_consume_approval(self):
        pending = self.start()
        for changes in [{'thread_id': 'other'}, {'case_id': 'other'}, {'snapshot_id': 'old'},
                        {'comparison_version': 0}, {'option_id': 'invented'}, {'acknowledge_consequences': False}]:
            with self.assertRaises(ValueError):
                self.runner().resume('test-case', {**pending['decision_template'], **changes})
            self.assertEqual(self.runner().status('test-case')['status'], 'awaiting_approval')

    def test_rejection_needs_no_supplier_or_model_call(self):
        pending = self.start()
        decision = {**pending['decision_template'], 'action': 'reject', 'option_id': None,
                    'acknowledge_consequences': False}
        runner = self.runner()
        with patch.object(self.client, 'get_supplier_update', side_effect=RuntimeError('offline')):
            result = runner.resume('test-case', decision)
        self.assertEqual(result['status'], 'rejected')

    def test_human_requested_changes_require_new_version_and_approval(self):
        pending = self.start()
        request = {**pending['decision_template'], 'action': 'request_changes', 'option_id': None,
                   'acknowledge_consequences': False, 'comment': 'Explain the buffer-preserving choice.'}
        again = self.runner().resume('test-case', request)
        self.assertEqual((again['status'], again['revision_count'], again['comparison_version']), ('awaiting_approval', 1, 2))
        self.assertTrue(any(context.facts.get('revision_feedback') for context in self.runtime.contexts))
        with self.assertRaises(ValueError):
            self.runner().resume('test-case', pending['decision_template'])

    def test_changed_inputs_invalidate_selection_and_require_fresh_review(self):
        pending = self.start()
        self.edit_fixture(lambda fixture: fixture['offers'][0].update(unit_price_cents=1300))
        again = self.runner().resume('test-case', pending['decision_template'])
        self.assertEqual((again['status'], again['comparison_version']), ('awaiting_approval', 2))
        self.assertIsNone(again['decision'])
        self.assertNotEqual(pending['comparison']['snapshot_id'], again['comparison']['snapshot_id'])
        self.assertIn('decision_invalidated', [event['kind'] for event in again['events']])
        approved = self.runner().resume('test-case', again['decision_template'])
        self.assertEqual(approved['decision']['consequences']['purchase']['total_cents'], 135000)

    def test_expired_approval_is_represented_for_a_fresh_human_decision(self):
        now = [datetime.now(timezone.utc)]
        runner = self.runner(clock=lambda: now[0])
        pending = self.start(runner)
        now[0] += timedelta(minutes=61)
        self.assertTrue(runner.status('test-case')['approval_is_expired'])
        self.settings = replace(self.settings, workflow=replace(self.settings.workflow, approval_ttl_minutes=120))
        self.assertTrue(self.runner(clock=lambda: now[0]).status('test-case')['approval_is_expired'])
        again = runner.resume('test-case', pending['decision_template'])
        self.assertEqual((again['status'], again['comparison_version']), ('awaiting_approval', 2))
        self.assertIsNone(again['decision'])

    def test_procurement_correction_is_bounded(self):
        once = self.start(self.runner(EvidenceRuntime(invalid_recommendations=1)), thread='one-revision')
        self.assertEqual((once['status'], once['revision_count']), ('awaiting_approval', 1))
        repeated = self.start(self.runner(EvidenceRuntime(invalid_recommendations=5)), thread='too-many')
        self.assertEqual(repeated['status'], 'escalated')
        self.assertIn('Revision limit', repeated['reason'])

    def test_missing_evidence_and_execution_failure_escalate_without_approval(self):
        for role, runtime in [('disruption', EvidenceRuntime(missing_role='disruption')),
                              ('inventory', EvidenceRuntime(broken_role='inventory'))]:
            result = self.start(self.runner(runtime), thread=f'failed-{role}')
            self.assertEqual(result['status'], 'escalated')
            self.assertIsNone(result['decision'])
            self.assertNotIn('decision_template', result)

    def test_final_validation_api_failure_cannot_record_approval(self):
        pending = self.start()
        runner = self.runner()
        with patch.object(self.client, 'get_supplier_update', side_effect=RuntimeError('offline')):
            result = runner.resume('test-case', pending['decision_template'])
        self.assertEqual(result['status'], 'escalated')
        self.assertIsNone(result['decision'])

    def test_status_can_be_read_from_a_separate_process_without_gemini(self):
        self.start()
        source = (ROOT / 'config/agents.toml').read_text()
        source = source.replace('../sqlite_supplier_poc/factory.sqlite', str(self.database))
        source = source.replace('../data/workflow.sqlite', str(self.settings.checkpoint_path))
        source = source.replace('http://127.0.0.1:8000', self.client.base_url)
        config = self.directory / 'config.toml'
        config.write_text(source)
        environment = {**os.environ, 'PYTHONPATH': str(ROOT / 'src')}
        output = subprocess.check_output([sys.executable, '-m', 'supply_chain_poc.integration',
                  '--config', str(config), '--status', '--thread-id', 'test-case'], env=environment, text=True)
        pending = json.loads(output)
        self.assertEqual(pending['status'], 'awaiting_approval')
        decision_file = self.directory / 'decision.json'
        decision_file.write_text(json.dumps(pending['decision_template']))
        output = subprocess.check_output([sys.executable, '-m', 'supply_chain_poc.integration',
                  '--config', str(config), '--decision-file', str(decision_file), '--thread-id', 'test-case'],
                  env=environment, text=True)
        self.assertEqual(json.loads(output)['status'], 'approved')

    def test_invalid_inventory_claim_gets_one_correction_attempt(self):
        class WrongOnce(EvidenceRuntime):
            wrong = True

            def invoke(self, request, tools):
                result = super().invoke(request, tools)
                if request.role == 'inventory' and self.wrong:
                    self.wrong = False
                    result.finding['unfulfilled_at_horizon'] = 0
                return result

        result = self.start(self.runner(WrongOnce()))
        self.assertEqual((result['status'], result['revision_count']), ('awaiting_approval', 1))

    def test_stale_selection_escalates_when_reassessment_budget_is_zero(self):
        self.settings = replace(self.settings, workflow=replace(self.settings.workflow, max_revisions=0))
        pending = self.start()
        self.edit_fixture(lambda fixture: fixture['offers'][0].update(unit_price_cents=1300))
        result = self.runner().resume('test-case', pending['decision_template'])
        self.assertEqual(result['status'], 'escalated')
        self.assertIsNone(result['decision'])

    def test_changed_consequences_cannot_hide_behind_same_input_hash(self):
        from copy import deepcopy

        self.settings = replace(self.settings, workflow=replace(self.settings.workflow, max_revisions=0))
        pending = self.start()
        changed = deepcopy(pending['comparison'])
        changed['options'][1]['scenarios']['expected']['additional_spend_cents'] += 100
        with patch('supply_chain_poc.integration.nodes.WorkflowNodes._calculate', return_value=changed):
            result = self.runner().resume('test-case', pending['decision_template'])
        self.assertEqual(result['status'], 'escalated')
        self.assertIsNone(result['decision'])
