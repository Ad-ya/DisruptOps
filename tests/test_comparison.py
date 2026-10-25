"""Comparison, history matching and additive setup against a real local API."""
import sqlite3
from contextlib import closing
from unittest.mock import Mock

from supply_chain_poc.config import ShellSettings
from supply_chain_poc.database.incident_migration import setup_incidents
from supply_chain_poc.services.comparison import ComparisonService, compact_comparison
from test_business_integration import SupplierDatabaseFixture, ROOT


class ComparisonTests(SupplierDatabaseFixture):
    def setUp(self):
        super().setUp()
        settings = ShellSettings.load(ROOT / 'config/agents.toml')
        self.service = ComparisonService(self.repository, self.client, settings.comparison)

    def compare(self):
        return self.service.compare_options('MAT-01', 'PO-501', '2026-11-01')

    def test_expected_choices_costs_and_observed_incidents(self):
        result = self.compare()
        expected = [(100, 3, 0, 2), (0, 1, 125000, 2), (0, 0, 149000, 1)]
        self.assertEqual(len(result['options']), 3)
        for option, values in zip(result['options'], expected):
            impact = option['scenarios']['expected']
            self.assertEqual((impact['unfulfilled_at_horizon'], impact['days_below_safety_stock'],
                              impact['additional_spend_cents'], option['historical_evidence']['sample_count']), values)
        self.assertEqual(result['recommended_option_id'], 'bridge:QUOTE-B:100')
        self.assertEqual(result['excluded_offers'][0]['offer_id'], 'QUOTE-C')

    def test_temporary_shortage_is_not_hidden_by_zero_ending_backlog(self):
        bridge = self.compare()['options'][1]
        late = bridge['scenarios']['late_replacement']
        self.assertEqual((late['unfulfilled_at_horizon'], late['missed_due_date_units'], late['days_with_backlog']), (0, 20, 1))
        self.assertEqual(late['first_shortage_date'], '2026-11-03')
        self.assertEqual(bridge['scenarios']['high_demand']['unfulfilled_at_horizon'], 40)

    def test_capture_is_shared_for_all_options_and_snapshot_changes_with_data(self):
        client = Mock(wraps=self.client)
        service = ComparisonService(self.repository, client, self.service.settings)
        first = service.compare_options('MAT-01', 'PO-501', '2026-11-01')
        self.assertEqual(client.get_supplier_update.call_count, 1)
        self.assertEqual(client.get_alternative_offers.call_count, 1)
        self.assertEqual(first['snapshot_id'], self.compare()['snapshot_id'])
        self.edit_fixture(lambda fixture: fixture['offers'][0].update(unit_price_cents=1300))
        self.assertNotEqual(first['snapshot_id'], self.compare()['snapshot_id'])

    def test_partial_capacity_is_shown_and_infeasible_offers_are_excluded(self):
        self.edit_fixture(lambda fixture: fixture['offers'][0].update(available_quantity=60))
        result = self.compare()
        self.assertEqual(len(result['options']), 2)
        self.assertEqual(result['options'][1]['purchase']['quantity'], 60)
        self.assertEqual(result['options'][1]['scenarios']['expected']['unfulfilled_at_horizon'], 40)
        self.edit_fixture(lambda fixture: fixture['offers'][0].update(valid_until='2026-10-01'))
        self.assertEqual(len(self.compare()['options']), 1)

    def test_setup_is_idempotent_and_preserves_factory_rows(self):
        with closing(sqlite3.connect(self.database)) as db:
            before = db.execute('SELECT * FROM inventory').fetchall()
        result = setup_incidents(self.database, ROOT / 'data/past_incidents.json')
        self.assertEqual(result['inserted'], 0)
        with closing(sqlite3.connect(self.database)) as db:
            self.assertEqual(db.execute('SELECT * FROM inventory').fetchall(), before)
            self.assertEqual(db.execute('SELECT COUNT(*) FROM past_incidents').fetchone()[0], 5)

    def test_history_excludes_future_and_incomparable_incidents(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE past_incidents SET occurred_on='2027-01-01' WHERE id='INC-001'")
            db.execute("UPDATE past_incidents SET stock_cover_days=20 WHERE id='INC-002'")
            db.execute("UPDATE past_incidents SET planning_days=10 WHERE id='INC-003'")
        history = self.repository.find_past_incidents('MAT-01', 'SUP-A', 3, 2.5, '2026-11-01')
        self.assertEqual({row['id'] for row in history['records']}, {'INC-004', 'INC-005'})

    def test_compact_context_preserves_metrics_without_duplicate_timelines(self):
        result = self.compare()
        compact = compact_comparison(result)
        self.assertEqual(compact['snapshot_id'], result['snapshot_id'])
        self.assertNotIn('timeline', compact['options'][0]['scenarios']['expected'])
        self.assertIn('timeline', result['options'][0]['scenarios']['expected'])



