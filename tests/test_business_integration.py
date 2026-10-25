"""Real SQLite and local HTTP integration; no Gemini calls or real supplier data."""
import importlib.util
import json
import io
from contextlib import redirect_stdout
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from http.server import ThreadingHTTPServer
from pathlib import Path

from supply_chain_poc.database.incident_migration import setup_incidents
from supply_chain_poc.core.database.base_repository import BaseFactoryRepository
from supply_chain_poc.core.suppliers.base_supplier_client import BaseSupplierClient
from supply_chain_poc.database.sqlite_repository import SQLiteFactoryRepository
from supply_chain_poc.suppliers.http_supplier_client import HttpSupplierClient
from supply_chain_poc.tools.business import BusinessTools

ROOT = Path(__file__).resolve().parents[1]


class SupplierDatabaseFixture(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.database = self.directory / 'factory.sqlite'
        self.fixture = self.directory / 'supplier_fixture.json'
        seed_spec = importlib.util.spec_from_file_location('test_seed', ROOT / 'sqlite_supplier_poc/seed.py')
        seed_module = importlib.util.module_from_spec(seed_spec)
        seed_spec.loader.exec_module(seed_module)
        with redirect_stdout(io.StringIO()):
            seed_module.seed(self.directory)
        setup_incidents(self.database, ROOT / 'data/past_incidents.json')
        spec = importlib.util.spec_from_file_location('test_supplier_server', ROOT / 'sqlite_supplier_poc/supplier_api.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        module.FIXTURE = self.fixture
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), module.Handler)
        self.thread = threading.Thread(target=lambda: self.server.serve_forever(poll_interval=0.01), daemon=True)
        self.thread.start()
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.repository = SQLiteFactoryRepository(self.database)
        self.client = HttpSupplierClient(f'http://127.0.0.1:{self.server.server_port}')
        self.tools = BusinessTools(self.repository, self.client)

    def edit_fixture(self, edit) -> None:
        fixture = json.loads(self.fixture.read_text())
        edit(fixture)
        self.fixture.write_text(json.dumps(fixture))


class BusinessIntegrationTests(SupplierDatabaseFixture):
    def test_abstract_data_contracts_cannot_be_instantiated(self) -> None:
        for contract in (BaseFactoryRepository, BaseSupplierClient):
            with self.assertRaises(TypeError):
                contract()

    def test_requirements_derive_from_active_remaining_orders_and_bom(self) -> None:
        result = self.repository.get_requirements('MAT-01', '2026-11-01')
        self.assertEqual(list(result['daily'].values()), [40] * 5)
        self.assertEqual({row['order_id'] for row in result['supporting_orders']}, {'WO-A', 'WO-B'})
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute("UPDATE production_schedule SET completed_quantity=5 WHERE order_id='WO-B' AND day='2026-11-01'")
        self.assertEqual(self.repository.get_requirements('MAT-01', '2026-11-01')['daily']['2026-11-01'], 35)
        with self.assertRaises(ValueError):
            self.repository.get_requirements('UNKNOWN', '2026-11-01')

    def test_repository_is_read_only_and_queries_are_parameterized(self) -> None:
        with self.assertRaises(sqlite3.OperationalError):
            self.repository._rows('DELETE FROM inventory')
        with self.assertRaises(ValueError):
            self.repository.get_shipment("PO-501' OR 1=1 --")
        self.assertEqual(self.repository.get_material_context('MAT-01')['inventory']['usable_quantity'], 100)

    def test_supplier_api_and_history(self) -> None:
        self.assertEqual(self.client.get_supplier_update('PO-501')['records'][0]['revised_usable_date'], '2026-11-06')
        self.assertEqual(len(self.client.get_alternative_offers('MAT-01')['records']), 2)
        history = self.repository.supplier_history('SUP-B', 'MAT-01')
        self.assertEqual((history['sample_count'], history['full_and_on_time']), (3, 2))
        with self.assertRaises(ValueError):
            self.client.get_supplier_update('MISSING')

    def test_wait_bridge_and_buffer_projections(self) -> None:
        for quantity, expected in [(0, (100, 3, 0)), (100, (0, 1, 125000)), (120, (0, 0, 149000))]:
            purchases = [{'offer_id': 'QUOTE-B', 'quantity': quantity}] if quantity else []
            result = self.tools.project_stock('MAT-01', '2026-11-01', purchases=purchases)
            self.assertEqual((result['unfulfilled_at_horizon'], result['days_below_safety_stock'],
                              result['additional_spend_cents']), expected)
            self.assertEqual(result['later_receipts'], {'2026-11-06': 200})
        self.assertEqual(self.tools.project_stock('MAT-01', '2026-11-01', demand_percent=120)['unfulfilled_at_horizon'], 140)
        self.assertEqual(self.tools.project_stock('MAT-01', '2026-11-01', days=6)['unfulfilled_at_horizon'], 0)

    def test_latest_notice_used_and_conflicting_quantity_rejected(self) -> None:
        self.edit_fixture(lambda f: f['shipments'][0].update(revised_usable_date='2026-11-02'))
        self.assertEqual(self.tools.project_stock('MAT-01', '2026-11-01')['unfulfilled_at_horizon'], 0)
        self.edit_fixture(lambda f: f['shipments'][0].update(quantity=999))
        with self.assertRaisesRegex(ValueError, 'conflicts'):
            self.tools.project_stock('MAT-01', '2026-11-01')

    def test_invalid_quotes_and_repeated_capacity_are_rejected(self) -> None:
        for offer, quantity, decision in [('QUOTE-C', 100, '2026-11-01'), ('QUOTE-B', 151, '2026-11-01'),
                                           ('QUOTE-B', 10, '2026-11-01'), ('QUOTE-B', 100, '2026-11-03')]:
            with self.assertRaises(ValueError):
                self.tools.price_purchase('MAT-01', offer, quantity, decision)
        with self.assertRaises(ValueError):
            self.tools.project_stock('MAT-01', '2026-11-01', purchases=[
                {'offer_id': 'QUOTE-B', 'quantity': 100}, {'offer_id': 'QUOTE-B', 'quantity': 100}])

    def test_api_failure_does_not_fall_back_to_cached_dates(self) -> None:
        self.edit_fixture(lambda f: f.update(records='invalid', shipments=[]))
        with self.assertRaises(ValueError):
            self.tools.project_stock('MAT-01', '2026-11-01')

    def test_network_error_is_explicit(self) -> None:
        from unittest.mock import patch
        from urllib.error import URLError

        with patch('supply_chain_poc.suppliers.http_supplier_client.urlopen', side_effect=URLError('offline')):
            with self.assertRaisesRegex(RuntimeError, 'Supplier API unavailable'):
                self.tools.project_stock('MAT-01', '2026-11-01')

