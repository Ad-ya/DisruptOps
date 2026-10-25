import hashlib
import json
from collections import Counter
from dataclasses import asdict
from datetime import date, timedelta

from supply_chain_poc.config import ComparisonSettings
from supply_chain_poc.core.database.base_repository import BaseFactoryRepository
from supply_chain_poc.core.suppliers.base_supplier_client import BaseSupplierClient
from supply_chain_poc.tools.planning import shipment_receipts, simulate_stock, validate_offer


class ComparisonService:
    def __init__(self, repository: BaseFactoryRepository, client: BaseSupplierClient,
                 settings: ComparisonSettings) -> None:
        self.repository, self.client, self.settings = repository, client, settings

    def compare_options(self, material_id: str, shipment_id: str, start_date: str, days: int = 5) -> dict:
        """Compare waiting and available single-supplier bridge/buffer purchases.

        Uses one captured set of orders, stock, notices and offers for all options.
        Includes expected demand, configured high demand, replacement lateness, and matched
        past incident observations. The ranking is a rule, not a global optimizer or approval.
        """
        context = self.repository.get_material_context(material_id)
        requirements = self.repository.get_requirements(material_id, start_date, days)
        if context['inventory']['as_of'] != start_date:
            raise ValueError('Comparison must begin on the opening inventory snapshot date')
        affected = next((row for row in context['shipments'] if row['id'] == shipment_id), None)
        if affected is None:
            raise ValueError('Affected shipment must be a pending receipt for this material')
        notices = {row['id']: self.client.get_supplier_update(row['id'])['records'][0]
                   for row in context['shipments']}
        receipts = shipment_receipts(context['shipments'], notices, start_date)
        offers = self.client.get_alternative_offers(material_id)['records']
        suppliers, supplier_histories = {}, {}
        for supplier_id in {affected['supplier_id'], *(row.get('supplier_id') for row in offers)}:
            try:
                suppliers[supplier_id] = self.repository.get_supplier(supplier_id)
                supplier_histories[supplier_id] = self.repository.supplier_history(supplier_id, material_id)
            except ValueError:
                continue  # Such offers will be explicitly excluded below.
        average_demand = sum(requirements['daily'].values()) / days
        delay = max(0, (date.fromisoformat(notices[shipment_id]['revised_usable_date'])
                        - date.fromisoformat(affected['promised_date'])).days)
        history = self.repository.find_past_incidents(
            material_id, affected['supplier_id'], delay,
            context['inventory']['usable_quantity'] / average_demand if average_demand else 0,
            start_date, days) if average_demand else {'records': [], 'sample_count': 0,
                'matching_rules': 'No consumption: no stock-coverage match was attempted.'}
        snapshot = {'context': context, 'requirements': requirements, 'notices': notices,
                    'offers': offers, 'suppliers': suppliers, 'supplier_history': supplier_histories,
                    'incidents': history, 'receipts': receipts, 'affected': affected, 'scenario_settings': asdict(self.settings)}
        snapshot_id = hashlib.sha256(json.dumps(snapshot, sort_keys=True).encode()).hexdigest()[:16]
        evidence = [material_id, shipment_id, *(r['order_id'] for r in requirements['supporting_orders'])]
        evidence += [notice['source_record_id'] for notice in notices.values() if notice.get('source_record_id')]
        end = next(reversed(requirements['daily']))
        plans, excluded = self._candidate_plans(snapshot, start_date)
        plans = [self._evaluate_plan(plan, snapshot, evidence) for plan in plans]
        def rank(plan):
            result = plan['scenarios']['expected']
            return (result['missed_due_date_units'], result['unfulfilled_at_horizon'],
                    result['additional_spend_cents'], result['days_below_safety_stock'], plan['option_id'])
        return {'snapshot_id': snapshot_id, 'material_id': material_id, 'shipment_id': shipment_id,
                'confirmed_disruption': notices[shipment_id],
                'opening_stock': context['inventory']['usable_quantity'],
                'safety_stock': context['material']['safety_stock'], 'unit': context['material']['unit'],
                'start_date': start_date, 'end_date': end, 'currency': 'USD', 'options': plans,
                'excluded_offers': excluded, 'recommended_option_id': min(plans, key=rank)['option_id'],
                'ranking_basis': 'Expected scenario: minimize units missing their due date, then ending backlog, then extra spending, then buffer-breach days. Stress results remain separate.',
                'assumptions': ['Single-supplier replacement candidates; partial quantities are shown if capacity is limited.',
                    'Original order remains scheduled; replacement arrivals are usable before daily consumption.',
                    'Backlogged material requirements are allocated first without a production-recovery capacity limit.',
                    'High-demand and late-replacement scenarios are configured assumptions, not probabilities.',
                    'Inputs are captured once for this comparison; no distributed transaction with suppliers is implied.'],
                'unknowns': ['Factory downtime and lost revenue are not inferred from material shortage.',
                    'Holding costs, cancellation charges and future post-horizon demand are not modeled.',
                    'Detailed scheduling feasibility, split-supplier plans and budget limits are not modeled.']}

    def _candidate_plans(self, inputs: dict, start_date: str) -> tuple[list[dict], list[dict]]:
        """Generate wait, bridge and buffer candidates; record why offers were excluded."""
        context, requirements = inputs['context'], inputs['requirements']
        receipts, offers, suppliers = inputs['receipts'], inputs['offers'], inputs['suppliers']
        end = next(reversed(requirements['daily']))
        excluded = []
        net, signed_stock = {}, context['inventory']['usable_quantity']
        for day, required in requirements['daily'].items():
            signed_stock += receipts.get(day, 0) - required
            net[day] = signed_stock
        plans = [{'option_id': 'wait', 'label': 'Wait for original delivery', 'action': 'wait', 'purchase': None}]
        counts = Counter(row.get('offer_id') for row in offers)
        for offer in offers:
            try:
                if counts[offer.get('offer_id')] != 1:
                    raise ValueError('Ambiguous offer ID')
                supplier = suppliers.get(offer.get('supplier_id'))
                if supplier is None:
                    raise ValueError('Supplier is absent from the factory registry')
                validate_offer(context['material'], supplier, offer, offer['minimum_quantity'], start_date)
                if offer['usable_arrival_date'] > end:
                    raise ValueError('Replacement cannot arrive within the planning horizon')
                minimum_net = min(value for day, value in net.items() if day >= offer['usable_arrival_date'])
                quantities = [('bridge', max(0, -minimum_net)),
                              ('protect_buffer', max(0, context['material']['safety_stock'] - minimum_net))]
                seen = set()
                for action, required in quantities:
                    if required == 0:
                        continue
                    quantity = min(max(required, offer['minimum_quantity']), offer['available_quantity'])
                    if quantity in seen:
                        continue
                    seen.add(quantity)
                    purchase = validate_offer(context['material'], supplier, offer, quantity, start_date)
                    plans.append({'option_id': f'{action}:{offer["offer_id"]}:{quantity}',
                                  'label': f'Buy {quantity} units ({action.replace("_", " ")})',
                                  'action': action, 'purchase': purchase})
            except (ValueError, KeyError, TypeError) as error:
                excluded.append({'offer_id': offer.get('offer_id'), 'reason': str(error)})
        return plans, excluded

    def _evaluate_plan(self, plan: dict, inputs: dict, evidence: list[str]) -> dict:
        """Evaluate the same three scenarios and attach observational evidence."""
        context, requirements, receipts = inputs['context'], inputs['requirements'], inputs['receipts']
        history, supplier_histories, affected = inputs['incidents'], inputs['supplier_history'], inputs['affected']
        purchase = plan['purchase']
        plan['scenarios'] = {}
        for name, demand, additional_delay in (
                ('expected', 100, 0), ('high_demand', self.settings.stress_demand_percent, 0),
                ('late_replacement', 100, self.settings.replacement_delay_days)):
            scenario_receipts = dict(receipts)
            if purchase:
                arrival = (date.fromisoformat(purchase['usable_date']) + timedelta(days=additional_delay)).isoformat()
                scenario_receipts[arrival] = scenario_receipts.get(arrival, 0) + purchase['quantity']
            impact = simulate_stock(context, requirements, scenario_receipts, [purchase] if purchase else [], demand)
            impact['replacement_delay_days'] = additional_delay if purchase else 0
            impact['safety_buffer_drawdown'] = max(0, context['material']['safety_stock'] - impact['minimum_closing_stock'])
            plan['scenarios'][name] = impact
        matched = [row for row in history['records'] if row['action'] == plan['action']]
        plan['historical_evidence'] = {
            'sample_count': len(matched), 'incidents_with_unfulfilled_demand': sum(r['observed_unfulfilled_units'] > 0 for r in matched),
            'records': matched, 'matching_rules': history['matching_rules'],
            'limitation': 'Observed actions under varying conditions; not a causal effect or future probability.'}
        supplier_id = purchase['supplier_id'] if purchase else affected['supplier_id']
        plan['supplier_delivery_history'] = supplier_histories[supplier_id]
        plan['evidence_ids'] = list(dict.fromkeys(evidence + ([purchase['offer_id']] if purchase else [])
                                  + [r['id'] for r in matched]
                                  + [r['id'] for r in supplier_histories[supplier_id]['records']]))
        return plan


def compact_comparison(comparison: dict) -> dict:
    """Keep the authoritative metrics/evidence in agent context; omit repeated daily timelines."""
    compact = {key: value for key, value in comparison.items() if key != 'options'}
    compact['options'] = []
    for option in comparison['options']:
        row = {key: value for key, value in option.items() if key != 'scenarios'}
        row['scenarios'] = {name: {key: value for key, value in impact.items()
                                  if key not in {'timeline', 'demand_provenance', 'validated_purchases'}}
                            for name, impact in option['scenarios'].items()}
        compact['options'].append(row)
    return compact
