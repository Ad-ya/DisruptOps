"""Synthetic data and typed decision contracts can be checked without an LLM."""
import importlib.util
import io
import json
import sqlite3
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from pathlib import Path

from pydantic import ValidationError
from supply_chain_poc.schemas.decision import HumanDecision
from supply_chain_poc.schemas.incidents import PastIncident

ROOT = Path(__file__).resolve().parents[1]


def seed_into(directory):
    spec = importlib.util.spec_from_file_location('data_seed', ROOT / 'sqlite_supplier_poc/seed.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    with redirect_stdout(io.StringIO()):
        module.seed(Path(directory))


class DataGenerationTests(unittest.TestCase):
    def test_fresh_generation_has_consistent_factory_and_supplier_records(self):
        with tempfile.TemporaryDirectory() as directory:
            seed_into(directory)
            root = Path(directory)
            with closing(sqlite3.connect(root / 'factory.sqlite')) as db:
                self.assertEqual(db.execute('SELECT COUNT(*) FROM materials').fetchone()[0], 2)
                self.assertEqual(db.execute('SELECT COUNT(*) FROM production_orders').fetchone()[0], 3)
                self.assertEqual(db.execute("SELECT quantity FROM shipments WHERE id='PO-501'").fetchone()[0], 200)
            payload = json.loads((root / 'supplier_fixture.json').read_text())
            self.assertTrue(payload['synthetic'])
            self.assertEqual(payload['shipments'][0]['quantity'], 200)

    def test_seed_refuses_to_replace_existing_database(self):
        with tempfile.TemporaryDirectory() as directory:
            seed_into(directory)
            database = Path(directory) / 'factory.sqlite'
            before = database.read_bytes()
            with self.assertRaises(SystemExit):
                seed_into(directory)
            self.assertEqual(database.read_bytes(), before)

    def test_historical_fixture_is_explicitly_synthetic(self):
        rows = [PastIncident.model_validate(row) for row in json.loads((ROOT / 'data/past_incidents.json').read_text())]
        self.assertEqual(len(rows), 5)
        self.assertEqual({row.source_type for row in rows}, {'synthetic'})
        self.assertEqual({row.action for row in rows}, {'wait', 'bridge', 'protect_buffer'})

    def test_decision_requires_acknowledgement_or_a_change_comment(self):
        base = {'action': 'approve', 'reviewer_id': 'tester', 'case_id': 'case', 'thread_id': 'thread',
                'snapshot_id': 'snapshot', 'comparison_version': 1, 'option_id': 'wait'}
        with self.assertRaises(ValidationError):
            HumanDecision.model_validate(base)
        self.assertEqual(HumanDecision.model_validate({**base, 'acknowledge_consequences': True}).option_id, 'wait')
        with self.assertRaises(ValidationError):
            HumanDecision.model_validate({**base, 'action': 'request_changes', 'option_id': None})
