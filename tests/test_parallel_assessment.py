"""Concurrency and joined-state invariants, with local data and no cloud calls."""
from collections import Counter
from dataclasses import replace
from threading import Barrier, Event, Lock

from langgraph.checkpoint.sqlite import SqliteSaver

from supply_chain_poc.agents import AGENT_CLASSES
from supply_chain_poc.config import ShellSettings
from supply_chain_poc.integration.assembly import assemble_agents
from supply_chain_poc.integration.runner import WorkflowRunner
from supply_chain_poc.integration.workflow import build_workflow
from supply_chain_poc.models import AgentContext
from supply_chain_poc.schemas.decision import validate_human_decision
from test_business_integration import ROOT, SupplierDatabaseFixture
from workflow_fixtures import EvidenceRuntime


class ParallelAssessmentTests(SupplierDatabaseFixture):
    def setUp(self):
        super().setUp()
        self.settings = replace(ShellSettings.load(ROOT / 'config/agents.toml'),
            database_path=self.database, checkpoint_path=self.directory / 'parallel.sqlite')
        self.context = AgentContext('CASE-PARALLEL', {'material_id': 'MAT-01', 'shipment_id': 'PO-501',
                                                     'start_date': '2026-11-01', 'days': 5})

    def runner(self, runtime):
        return WorkflowRunner(self.settings, assemble_agents(self.settings, runtime=runtime,
            repository=self.repository, supplier_client=self.client))

    def test_real_overlap_and_join_handoff_without_cross_branch_context(self):
        barrier, lock = Barrier(2, timeout=5), Lock()
        completed = set()
        contexts = {}

        class ConcurrentRuntime(EvidenceRuntime):
            def invoke(inner, request, tools):
                role = request.role
                if role in {'disruption', 'inventory'}:
                    # This times out if the graph accidentally runs the roles serially.
                    barrier.wait()
                    self.assertEqual(request.context.previous_results, {})
                    result = super(ConcurrentRuntime, inner).invoke(request, tools)
                    with lock:
                        completed.add(role)
                    return result
                with lock:
                    self.assertEqual(completed, {'disruption', 'inventory'})
                contexts[role] = request.context
                return super(ConcurrentRuntime, inner).invoke(request, tools)

        runtime = ConcurrentRuntime()
        runner = self.runner(runtime)
        pending = runner.start('parallel-success', 'Assess', self.context)
        self.assertEqual(pending['status'], 'awaiting_approval')
        self.assertEqual(Counter(runtime.calls), Counter({'disruption': 1, 'inventory': 1, 'procurement': 1}))
        self.assertEqual(set(contexts['procurement'].previous_results), {'disruption', 'inventory'})
        roles = [row['role'] for row in pending['events'] if row['kind'] == 'agent_finished']
        self.assertEqual(Counter(roles), Counter(runtime.calls))
        self.assertEqual(runner.resume('parallel-success', pending['decision_template'])['status'], 'approved')

    def test_failed_branch_still_joins_and_never_calls_procurement(self):
        for failed in ('disruption', 'inventory'):
            runtime = EvidenceRuntime(broken_role=failed)
            output = self.runner(runtime).start('failed-' + failed, 'Assess', self.context)
            self.assertEqual(output['status'], 'escalated')
            self.assertEqual(set(output['findings']), {'disruption', 'inventory'})
            self.assertEqual(Counter(runtime.calls), Counter({'disruption': 1, 'inventory': 1}))
            self.assertIsNone(output['decision'])

    def test_two_correctable_branch_errors_consume_one_shared_revision(self):
        class BothWrongOnce(EvidenceRuntime):
            def __init__(inner):
                super().__init__()
                inner.counts, inner.lock = Counter(), Lock()

            def invoke(inner, request, tools):
                with inner.lock:
                    inner.counts[request.role] += 1
                    count = inner.counts[request.role]
                if request.role in {'disruption', 'inventory'} and count == 1:
                    raise ValueError('Synthetic invalid structured output')
                return super(BothWrongOnce, inner).invoke(request, tools)

        runtime = BothWrongOnce()
        output = self.runner(runtime).start('two-errors', 'Assess', self.context)
        self.assertEqual((output['status'], output['revision_count']), ('awaiting_approval', 1))
        self.assertEqual(runtime.counts, Counter({'disruption': 2, 'inventory': 2, 'procurement': 1}))
        self.assertEqual(sum(row['kind'] == 'revision_requested' for row in output['events']), 1)

    def test_permanent_branch_error_exhausts_budget_without_deadlock(self):
        class AlwaysInvalid(EvidenceRuntime):
            def invoke(inner, request, tools):
                if request.role == 'inventory':
                    raise ValueError('Synthetic invalid output')
                return super(AlwaysInvalid, inner).invoke(request, tools)

        output = self.runner(AlwaysInvalid()).start('always-invalid', 'Assess', self.context)
        self.assertEqual((output['status'], output['revision_count']), ('escalated', 1))
        self.assertIn('Revision limit', output['reason'])
        self.assertIsNone(output['decision'])

    def test_refresh_restarts_both_branches_and_clears_old_recommendation(self):
        changed = Event()

        class ChangeOnce(EvidenceRuntime):
            def invoke(inner, request, tools):
                result = super(ChangeOnce, inner).invoke(request, tools)
                if request.role == 'procurement' and not changed.is_set():
                    changed.set()
                    self.edit_fixture(lambda fixture: fixture['offers'][0].update(unit_price_cents=1300))
                return result

        runtime = ChangeOnce()
        output = self.runner(runtime).start('changed-during-run', 'Assess', self.context)
        self.assertEqual((output['status'], output['comparison_version']), ('awaiting_approval', 2))
        self.assertEqual(Counter(runtime.calls), Counter({'disruption': 2, 'inventory': 2, 'procurement': 2}))
        self.assertEqual(output['comparison']['options'][1]['purchase']['total_cents'], 135000)
        for context in runtime.contexts:
            if not context.previous_results:
                self.assertNotIn('comparison', context.facts)

    def test_human_changes_rerun_procurement_without_rerunning_assessment(self):
        runtime = EvidenceRuntime()
        runner = self.runner(runtime)
        pending = runner.start('human-changes', 'Assess', self.context)
        again = runner.resume('human-changes', {**pending['decision_template'], 'action': 'request_changes',
            'option_id': None, 'acknowledge_consequences': False, 'comment': 'Explain high-demand exposure.'})
        self.assertEqual((again['status'], again['comparison_version']), ('awaiting_approval', 2))
        self.assertEqual(Counter(runtime.calls), Counter({'disruption': 1, 'inventory': 1, 'procurement': 2}))

    def test_approval_requires_all_three_successful_consistent_findings(self):
        from copy import deepcopy
        runtime = EvidenceRuntime()
        runner = self.runner(runtime)
        pending = runner.start('approval-guard', 'Assess', self.context)
        state = {'status': pending['status'], 'context': {'case_id': self.context.case_id},
            'thread_id': pending['thread_id'], 'comparison': pending['comparison'],
            'comparison_version': pending['comparison_version'], 'results': pending['findings']}
        for role in AGENT_CLASSES:
            invalid = deepcopy(state)
            del invalid['results'][role]
            with self.assertRaises(ValueError):
                validate_human_decision(pending['decision_template'], invalid)
        invalid = deepcopy(state)
        invalid['results']['inventory']['unfulfilled_at_horizon'] = 0
        with self.assertRaises(ValueError):
            validate_human_decision(pending['decision_template'], invalid)

    def test_existing_workflow_version_can_be_read_but_not_resumed(self):
        runtime = EvidenceRuntime()
        runner = self.runner(runtime)
        pending = runner.start('old-version', 'Assess', self.context)
        with SqliteSaver.from_conn_string(str(self.settings.checkpoint_path)) as saver:
            graph = build_workflow(assemble_agents(self.settings, runtime=runtime,
                repository=self.repository, supplier_client=self.client), checkpointer=saver)
            graph.update_state({'configurable': {'thread_id': 'old-version'}}, {'workflow_version': 1})
        self.assertEqual(runner.status('old-version')['workflow_version'], 1)
        with self.assertRaisesRegex(ValueError, 'older workflow'):
            runner.resume('old-version', pending['decision_template'])

    def test_each_live_role_gets_its_own_lazy_runtime(self):
        agents = assemble_agents(self.settings, repository=self.repository, supplier_client=self.client)
        self.assertEqual(set(agents), {'disruption', 'inventory', 'procurement'})
        self.assertEqual(len({id(agent.runtime) for agent in agents.values()}), 3)
