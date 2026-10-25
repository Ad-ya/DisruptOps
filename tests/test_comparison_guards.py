"""Deterministic checks reject altered metrics and nonexistent options."""
import unittest
from supply_chain_poc.services.finding_checks import check_finding_against_comparison
from supply_chain_poc.schemas.findings import validate_finding


class ComparisonGuardTests(unittest.TestCase):
    def inventory(self, **changes):
        return {'role': 'inventory', 'status': 'ok', 'summary': 'Verified material exposure',
                'material_id': 'MAT-01', 'evidence_ids': ['PO-501'],
                'first_shortage_date': '2026-11-03', 'unfulfilled_at_horizon': 100,
                'days_below_safety_stock': 3, **changes}

    def test_comparison_guard_rejects_changed_metrics_stale_snapshots_and_skipped_options(self):
        expected = {'material_id': 'MAT-01', 'first_shortage_date': '2026-11-03',
                    'unfulfilled_at_horizon': 100, 'days_below_safety_stock': 3}
        comparison = {'snapshot_id': 'snapshot', 'options': [
            {'option_id': 'wait', 'evidence_ids': ['PO-501'], 'scenarios': {'expected': expected}},
            {'option_id': 'bridge', 'evidence_ids': ['QUOTE-B'], 'scenarios': {}}]}
        with self.assertRaises(ValueError):
            check_finding_against_comparison(validate_finding('inventory', self.inventory(unfulfilled_at_horizon=0)), comparison)
        finding = {'role': 'procurement', 'status': 'ok', 'summary': 'Checked', 'evidence_ids': ['snapshot'],
                   'comparison_snapshot_id': 'snapshot', 'option_ids': ['wait'], 'recommended_option_id': 'wait'}
        with self.assertRaises(ValueError):
            check_finding_against_comparison(validate_finding('procurement', finding), comparison)
        finding.update(option_ids=['wait', 'bridge'], comparison_snapshot_id='old')
        with self.assertRaises(ValueError):
            check_finding_against_comparison(validate_finding('procurement', finding), comparison)

