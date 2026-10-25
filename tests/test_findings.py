"""Business contracts reject incomplete confidence and invented comparison references."""
import unittest

from pydantic import ValidationError

from supply_chain_poc.models import AgentResult
from supply_chain_poc.schemas.findings import validate_finding


class FindingTests(unittest.TestCase):
    def inventory(self, **changes):
        return {'role': 'inventory', 'status': 'ok', 'summary': 'Verified material exposure',
                'material_id': 'MAT-01', 'evidence_ids': ['PO-501'],
                'first_shortage_date': '2026-11-03', 'unfulfilled_at_horizon': 100,
                'days_below_safety_stock': 3, **changes}

    def test_structured_result_serializes_and_exposes_summary(self):
        result = AgentResult('inventory', 'CASE-1', self.inventory())
        self.assertEqual(result.finding['first_shortage_date'], '2026-11-03')
        self.assertEqual(result.text, 'Verified material exposure')

    def test_negative_boolean_extra_and_missing_evidence_are_rejected(self):
        for changes in [{'unfulfilled_at_horizon': -1}, {'unfulfilled_at_horizon': True},
                        {'invented_field': 1}, {'evidence_ids': []}, {'evidence_ids': [' ']}]:
            with self.assertRaises(ValidationError):
                validate_finding('inventory', self.inventory(**changes))

    def test_missing_information_is_explicit_and_can_use_nulls(self):
        result = validate_finding('inventory', {'status': 'needs_information', 'summary': 'Missing stock',
                                               'unresolved_questions': ['What is the current stock snapshot?']})
        self.assertIsNone(result['unfulfilled_at_horizon'])
        with self.assertRaises(ValidationError):
            validate_finding('inventory', {'status': 'needs_information', 'summary': 'Missing stock'})

    def test_confirmed_disruption_requires_details(self):
        with self.assertRaises(ValidationError):
            validate_finding('disruption', {'status': 'ok', 'summary': 'Delayed', 'evidence_ids': ['NOTICE-001']})

    def test_agent_identity_is_assigned_by_application_not_generated(self):
        from supply_chain_poc.schemas.findings import InventoryFinding

        self.assertNotIn('role', InventoryFinding.model_json_schema()['properties'])
        self.assertEqual(validate_finding('inventory', self.inventory())['role'], 'inventory')
        with self.assertRaises(ValueError):
            validate_finding('inventory', self.inventory(role='procurement'))

    def test_procurement_recommendation_must_be_listed(self):
        with self.assertRaises(ValidationError):
            validate_finding('procurement', {'status': 'ok', 'summary': 'Buy', 'evidence_ids': ['QUOTE-B'],
                'comparison_snapshot_id': 'snapshot', 'option_ids': ['wait'], 'recommended_option_id': 'invented'})

    def test_only_three_finding_schemas_are_registered(self):
        from supply_chain_poc.schemas.findings import FINDING_SCHEMAS
        self.assertEqual(set(FINDING_SCHEMAS), {'disruption', 'inventory', 'procurement'})

