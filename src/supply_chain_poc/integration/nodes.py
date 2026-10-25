from dataclasses import asdict, replace
from datetime import datetime, timedelta, timezone

from langchain_core.runnables import RunnableConfig
from langgraph.types import interrupt

from supply_chain_poc.config import WorkflowSettings
from supply_chain_poc.integration.environment import public_error
from supply_chain_poc.models import AgentContext
from supply_chain_poc.schemas.decision import HumanDecision, validate_human_decision
from supply_chain_poc.schemas.findings import validate_finding
from supply_chain_poc.services.comparison import compact_comparison
from supply_chain_poc.services.finding_checks import check_finding_against_comparison

ASSESSMENT_ROLES = ('disruption', 'inventory')
ROLE_ORDER = (*ASSESSMENT_ROLES, 'procurement')
WORKFLOW_VERSION = 2


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class WorkflowNodes:
    def __init__(self, agents: dict, settings: WorkflowSettings, clock=utc_now) -> None:
        self.agents, self.settings, self.clock = agents, settings, clock

    def _event(self, state: dict, kind: str, **details) -> list[dict]:
        return [*state.get('events', []), {'at': self.clock().isoformat(), 'kind': kind, **details}]

    def _context(self, state: dict) -> AgentContext:
        value = state['context']
        return value if isinstance(value, AgentContext) else AgentContext(**value)

    def begin(self, state: dict, config: RunnableConfig) -> dict:
        return {'context': asdict(self._context(state)), 'results': {}, 'comparison': None,
                'workflow_version': WORKFLOW_VERSION, 'status': 'running', 'revision_count': 0,
                'comparison_version': 1, 'events': [], 'selection': None, 'decision': None,
                'thread_id': config['configurable']['thread_id'], 'reason': '', 'revision_feedback': {}}

    def assess(self, _state: dict) -> dict:
        # Reset each round before the two concurrent nodes start.
        return {'results': {}, 'comparison': None,
                'disruption_outcome': None, 'inventory_outcome': None}

    def _escalate(self, state: dict, reason: str) -> dict:
        return {'status': 'escalated', 'route': 'escalate', 'reason': reason,
                'events': self._event(state, 'escalated', reason=reason)}

    def _revise(self, state: dict, target: str, reason: str) -> dict:
        if state['revision_count'] >= self.settings.max_revisions:
            return {'results': state['results'], **self._escalate(state, f'Revision limit reached. {reason}')}
        return {'results': {} if target == 'assess' else {
                    name: finding for name, finding in state['results'].items() if name in ASSESSMENT_ROLES},
                'comparison': None if target == 'assess' else state.get('comparison'),
                'revision_count': state['revision_count'] + 1,
                'comparison_version': state['comparison_version'] + 1,
                'revision_feedback': {'target': target, 'issues': reason},
                'status': 'running', 'route': target, 'selection': None, 'decision': None,
                'approval_presented_at': None, 'approval_expires_at': None, 'reason': '',
                'events': self._event(state, 'revision_requested', target=target, reason=reason)}

    @staticmethod
    def _problem(finding: dict) -> str:
        return '; '.join(finding['unresolved_questions']) or finding['summary']

    def _run_agent(self, role: str, state: dict) -> dict:
        context = self._context(state)
        facts = dict(context.facts)
        if state.get('comparison'):
            facts['comparison'] = compact_comparison(state['comparison'])
        if state.get('revision_feedback'):
            facts['revision_feedback'] = state['revision_feedback']
        previous = {} if role in ASSESSMENT_ROLES else {**context.previous_results, **state['results']}
        context = replace(context, facts=facts, previous_results=previous)
        retryable = False
        try:
            finding = self.agents[role].run(state['task'], context).finding
            if role == 'procurement':
                check_finding_against_comparison(finding, state['comparison'])
        except Exception as error:
            retryable = isinstance(error, ValueError) or type(error).__name__ in {
                'StructuredOutputValidationError', 'MultipleStructuredOutputsError'}
            finding = validate_finding(role, {'status': 'failed', 'summary': public_error(error)})
        return {'finding': finding, 'retryable': retryable,
                'event': {'at': self.clock().isoformat(), 'kind': 'agent_finished',
                          'role': role, 'status': finding['status']}}

    def agent_node(self, role: str):
        def run(state: dict) -> dict:
            outcome = self._run_agent(role, state)
            if role in ASSESSMENT_ROLES:
                # Separate output channels avoid concurrent writes to shared state.
                return {f'{role}_outcome': outcome}
            finding = outcome['finding']
            updated = {**state, 'results': {**state['results'], role: finding},
                       'events': [*state['events'], outcome['event']]}
            if outcome['retryable']:
                return self._revise(updated, 'procurement', self._problem(finding))
            if finding['status'] != 'ok':
                return {'results': updated['results'], **self._escalate(updated, self._problem(finding))}
            return {'results': updated['results'], 'events': updated['events'], 'route': 'refresh_before_approval'}
        return run

    def _calculate(self, state: dict) -> dict:
        facts = self._context(state).facts
        return self.agents['procurement'].tools['compare_options'](
            facts['material_id'], facts['shipment_id'], facts['start_date'], facts.get('days', 5))

    def compare(self, state: dict) -> dict:
        outcomes = {role: state[f'{role}_outcome'] for role in ASSESSMENT_ROLES}
        updated = {**state, 'results': {role: item['finding'] for role, item in outcomes.items()},
                   'events': [*state['events'], *(item['event'] for item in outcomes.values())]}
        # One serial node owns shared results, events and revision accounting.
        for role, item in outcomes.items():
            if item['finding']['status'] != 'ok' and not item['retryable']:
                return {'results': updated['results'], **self._escalate(
                    updated, f"{role}: {self._problem(item['finding'])}")}
        problems = [f"{role}: {self._problem(item['finding'])}" for role, item in outcomes.items()
                    if item['finding']['status'] != 'ok']
        if problems:
            return self._revise(updated, 'assess', '; '.join(problems))
        try:
            comparison = self._calculate(updated)
        except Exception as error:
            return {'results': updated['results'], **self._escalate(
                updated, f'Comparison failed: {public_error(error)}')}
        updated['comparison'] = comparison
        for role in ASSESSMENT_ROLES:
            try:
                check_finding_against_comparison(updated['results'][role], comparison)
            except ValueError as error:
                return self._revise(updated, 'assess', public_error(error))
        return {'results': updated['results'], 'comparison': comparison, 'route': 'procurement',
                'events': self._event(updated, 'comparison_calculated', snapshot_id=comparison['snapshot_id'])}

    def refresh_before_approval(self, state: dict) -> dict:
        try:
            current = self._calculate(state)
        except Exception as error:
            return self._escalate(state, f'Cannot verify current inputs: {public_error(error)}')
        if current != state['comparison']:
            return self._revise(state, 'assess', 'Inputs changed; reassess the new comparison')
        return {'route': 'prepare_approval'}

    def prepare_approval(self, state: dict) -> dict:
        presented = self.clock()
        expires = presented + timedelta(minutes=self.settings.approval_ttl_minutes)
        return {'status': 'awaiting_approval', 'approval_presented_at': presented.isoformat(),
                'approval_expires_at': expires.isoformat(),
                'events': self._event(state, 'awaiting_approval', version=state['comparison_version'])}

    def human_approval(self, state: dict) -> dict:
        # No side effects before interrupt: this node restarts when resumed.
        answer = interrupt({
            'kind': 'human_decision', 'thread_id': state['thread_id'],
            'case_id': self._context(state).case_id, 'snapshot_id': state['comparison']['snapshot_id'],
            'comparison_version': state['comparison_version'],
            'comparison': compact_comparison(state['comparison']),
            'actions': ['approve', 'reject', 'request_changes'],
            'note': 'Review the consequences. This POC records a decision; it does not place orders.'},
            response_schema=HumanDecision)
        try:
            decision = validate_human_decision(answer.model_dump(mode='json'), state)
        except ValueError as error:
            return {'route': 'human_approval', 'reason': public_error(error)}
        selection = decision.model_dump(mode='json')
        updated = {**state, 'selection': selection,
                   'events': self._event(state, 'human_decision_received', action=decision.action,
                                         reviewer_id=decision.reviewer_id)}
        if decision.action == 'request_changes':
            return self._revise(updated, 'procurement', decision.comment)
        return {'selection': selection, 'events': updated['events'],
                'route': 'reject' if decision.action == 'reject' else 'final_validation'}

    def final_validation(self, state: dict) -> dict:
        try:
            current = self._calculate(state)
        except Exception as error:
            return self._escalate(state, f'Approval cannot be validated: {public_error(error)}')
        expired = self.clock() >= datetime.fromisoformat(state['approval_expires_at'])
        if expired or current != state['comparison']:
            reason = 'Approval expired' if expired else 'Inputs changed after presentation'
            updated = {**state, 'events': self._event(state, 'decision_invalidated', reason=reason)}
            return self._revise(updated, 'assess', f'{reason}; fresh assessment and human selection are required')
        option = next(row for row in current['options'] if row['option_id'] == state['selection']['option_id'])
        return {'status': 'approved', 'route': 'finish',
                'decision': {**state['selection'], 'recorded_at': self.clock().isoformat(),
                             'consequences': option, 'scope': 'Decision record only; no purchase order placed.'},
                'events': self._event(state, 'decision_recorded', option_id=option['option_id'])}

    def reject(self, state: dict) -> dict:
        return {'status': 'rejected', 'decision': {**state['selection'], 'recorded_at': self.clock().isoformat(),
                'scope': 'Case rejected; no order placed or cancelled.'},
                'events': self._event(state, 'case_rejected')}

    def escalate(self, state: dict) -> dict:
        return {'status': 'escalated', 'selection': None, 'decision': None}
