"""Deterministic runtime for routing/approval tests; never used by the application."""
from supply_chain_poc.core.runtime.base_runtime import AgentRuntime
from supply_chain_poc.models import AgentResult


class EvidenceRuntime(AgentRuntime):
    def __init__(self, *, missing_role=None, broken_role=None, invalid_recommendations=0) -> None:
        self.missing_role, self.broken_role, self.invalid_recommendations = missing_role, broken_role, invalid_recommendations
        self.calls, self.contexts = [], []

    def invoke(self, request, tools):
        role = request.role
        self.calls.append(role)
        self.contexts.append(request.context)
        if role == self.broken_role:
            raise RuntimeError('Synthetic execution failure')
        finding = {'role': role, 'status': 'ok', 'summary': 'Verified synthetic fixture records',
                   'evidence_ids': ['PO-501']}
        if role == self.missing_role:
            finding.update(status='needs_information', unresolved_questions=['Required evidence is missing'])
            return AgentResult(role, request.context.case_id, finding)
        available = {tool.__name__: tool for tool in tools}
        facts = request.context.facts
        if role == 'disruption':
            record = available['get_supplier_update'](facts['shipment_id'])['records'][0]
            finding.update({key: record[key] for key in ('shipment_id', 'material_id', 'quantity', 'revised_usable_date')})
        elif role == 'inventory':
            impact = available['project_stock'](facts['material_id'], facts['start_date'], facts['days'])
            finding.update({key: impact[key] for key in ('material_id', 'first_shortage_date',
                                                         'unfulfilled_at_horizon', 'days_below_safety_stock')})
        else:
            comparison = facts['comparison']
            ids = [row['option_id'] for row in comparison['options']]
            finding['comparison_snapshot_id'] = comparison['snapshot_id']
            finding.update(option_ids=ids, recommended_option_id=comparison['recommended_option_id'])
            if self.invalid_recommendations:
                self.invalid_recommendations -= 1
                finding['comparison_snapshot_id'] = 'stale-snapshot'
        return AgentResult(role, request.context.case_id, finding)
