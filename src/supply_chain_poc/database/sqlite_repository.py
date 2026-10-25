import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

from supply_chain_poc.core.database.base_repository import BaseFactoryRepository


class SQLiteFactoryRepository(BaseFactoryRepository):
    def __init__(self, database_path: Path) -> None:
        self.database_path = database_path.resolve()
        if not self.database_path.is_file():
            raise FileNotFoundError(f'Factory database not found: {self.database_path}')

    def _rows(self, query: str, parameters: tuple = ()) -> list[dict]:
        with closing(sqlite3.connect(self.database_path.as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            return [dict(row) for row in db.execute(query, parameters)]

    def _one(self, query: str, identifier: str) -> dict:
        rows = self._rows(query, (identifier,))
        if not rows:
            raise ValueError(f'No matching factory record: {identifier}')
        return rows[0]

    def get_material_context(self, material_id: str) -> dict:
        """Read a material's specification, usable stock, buffer and pending receipts from SQLite."""
        return {
            'material': self._one('SELECT * FROM materials WHERE id=?', material_id),
            'inventory': self._one('SELECT * FROM inventory WHERE material_id=?', material_id),
            'shipments': self._rows("SELECT * FROM shipments WHERE material_id=? AND status='pending'", (material_id,)),
        }

    def get_shipment(self, shipment_id: str) -> dict:
        """Read shipment quantity, supplier and recorded delivery dates from SQLite."""
        return self._one('SELECT * FROM shipments WHERE id=?', shipment_id)

    def get_supplier(self, supplier_id: str) -> dict:
        """Read the supplier's identity and internal approval status from SQLite."""
        return self._one('SELECT * FROM suppliers WHERE id=?', supplier_id)

    def get_requirements(self, material_id: str, start_date: str, days: int = 5) -> dict:
        """Calculate daily remaining material requirements from active orders, schedules and BOM; return supporting order IDs."""
        self._one('SELECT * FROM materials WHERE id=?', material_id)
        start = date.fromisoformat(start_date)
        if type(days) is not int or not 1 <= days <= 30:
            raise ValueError('days must be between 1 and 30')
        end = (start + timedelta(days=days - 1)).isoformat()
        rows = self._rows('''SELECT s.day, o.id AS order_id, o.product_id,
                    s.planned_quantity-s.completed_quantity AS remaining_products,
                    b.quantity_per_product
                    FROM production_schedule s JOIN production_orders o ON o.id=s.order_id
                    JOIN bom b ON b.product_id=o.product_id
                    WHERE o.status='active' AND b.material_id=? AND s.day BETWEEN ? AND ?
                    ORDER BY s.day,o.id''', (material_id, start.isoformat(), end))
        totals = {(start + timedelta(days=i)).isoformat(): 0 for i in range(days)}
        for row in rows:
            row['required_quantity'] = row['remaining_products'] * row['quantity_per_product']
            totals[row['day']] += row['required_quantity']
        return {'material_id': material_id, 'daily': totals, 'supporting_orders': rows}

    def supplier_history(self, supplier_id: str, material_id: str) -> dict:
        """Calculate full-and-on-time counts from all recorded completed deliveries, with source rows and sample size."""
        self.get_supplier(supplier_id)
        rows = self._rows("SELECT * FROM shipments WHERE supplier_id=? AND material_id=? AND status='delivered'",
                          (supplier_id, material_id))
        on_time = sum(r['actual_date'] <= r['promised_date'] and r['accepted_quantity'] >= r['quantity'] for r in rows)
        return {'sample_count': len(rows), 'full_and_on_time': on_time, 'records': rows,
                'limitation': 'Observed delivery records, not a future delivery probability or incident-outcome study.'}

    def find_past_incidents(self, material_id: str, supplier_id: str, delay_days: int,
                            stock_cover_days: float, as_of: str, planning_days: int = 5) -> dict:
        """Find up to ten earlier incidents with the same material, supplier and horizon,
        delay within two days, and stock coverage within one day. Outcomes are observations.
        """
        date.fromisoformat(as_of)
        if delay_days < 0 or stock_cover_days < 0 or not 1 <= planning_days <= 30:
            raise ValueError('Invalid incident matching parameters')
        try:
            rows = self._rows('''SELECT * FROM past_incidents WHERE material_id=? AND supplier_id=?
                AND occurred_on<? AND planning_days=? AND ABS(delay_days-?)<=2
                AND ABS(stock_cover_days-?)<=1
                ORDER BY ABS(delay_days-?),ABS(stock_cover_days-?),occurred_on DESC,id LIMIT 10''',
                (material_id, supplier_id, as_of, planning_days, delay_days, stock_cover_days,
                 delay_days, stock_cover_days))
        except sqlite3.OperationalError as error:
            if 'no such table: past_incidents' in str(error):
                raise RuntimeError('Run the integration entry point with --setup-incidents first.') from error
            raise
        return {'records': rows, 'sample_count': len(rows),
                'matching_rules': 'Same material/supplier/horizon; prior to case date; delay +/-2 days; stock cover +/-1 day.',
                'limitation': 'Small observational samples with different conditions; no causal effect or future probability implied.'}
