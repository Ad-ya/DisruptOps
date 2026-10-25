import json
import sqlite3
from contextlib import closing
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def seed(output_dir: Path = ROOT):
    output_dir.mkdir(parents=True, exist_ok=True)
    database_path = output_dir / 'factory.sqlite'
    if database_path.exists():
        raise SystemExit('factory.sqlite already exists; remove it explicitly to reset the demo.')
    with closing(sqlite3.connect(database_path)) as db, db:
        db.executescript((ROOT / 'schema.sql').read_text())
        db.executemany('INSERT INTO materials VALUES (?,?,?,?,?)', [
            ('MAT-01', 'Assembly component', 'piece', 'SPEC-A', 20),
            ('MAT-02', 'Packaging kit', 'piece', 'SPEC-B', 10),
        ])
        db.executemany('INSERT INTO products VALUES (?,?)', [('FG-A', 'Product A'), ('FG-B', 'Product B')])
        db.executemany('INSERT INTO suppliers VALUES (?,?,?)', [
            ('SUP-A', 'Original supplier', 1), ('SUP-B', 'Backup supplier', 1),
            ('SUP-C', 'Unapproved supplier', 0),
        ])
        db.executemany('INSERT INTO bom VALUES (?,?,?)', [
            ('FG-A', 'MAT-01', 2), ('FG-A', 'MAT-02', 1),
            ('FG-B', 'MAT-01', 1), ('FG-B', 'MAT-02', 1),
        ])
        db.executemany('INSERT INTO production_orders VALUES (?,?,?,?)', [
            ('WO-A', 'FG-A', 50, 'active'), ('WO-B', 'FG-B', 100, 'active'),
            ('WO-CANCELLED', 'FG-A', 100, 'cancelled'),
        ])
        for offset in range(5):
            day = (date(2026, 11, 1) + timedelta(days=offset)).isoformat()
            db.executemany('INSERT INTO production_schedule VALUES (?,?,?,?)', [
                ('WO-A', day, 10, 0), ('WO-B', day, 20, 0),
            ])
        db.execute('INSERT INTO production_schedule VALUES (?,?,?,?)',
                   ('WO-CANCELLED', '2026-11-01', 100, 0))
        db.executemany('INSERT INTO inventory VALUES (?,?,?)', [
            ('MAT-01', 100, '2026-11-01'), ('MAT-02', 200, '2026-11-01'),
        ])
        db.execute('INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?)',
                   ('PO-501', 'SUP-A', 'MAT-01', 200, '2026-11-03', '2026-11-06', None, None, 'pending'))
        db.executemany('INSERT INTO shipments VALUES (?,?,?,?,?,?,?,?,?)', [
            ('OLD-1', 'SUP-B', 'MAT-01', 100, '2026-09-01', None, '2026-09-01', 100, 'delivered'),
            ('OLD-2', 'SUP-B', 'MAT-01', 100, '2026-09-10', None, '2026-09-12', 100, 'delivered'),
            ('OLD-3', 'SUP-B', 'MAT-01', 100, '2026-10-01', None, '2026-10-01', 100, 'delivered'),
        ])
    fixture = {
        'synthetic': True,
        'shipments': [{'shipment_id': 'PO-501', 'supplier_id': 'SUP-A',
                       'material_id': 'MAT-01', 'quantity': 200,
                       'revised_usable_date': '2026-11-06',
                       'reason': 'Synthetic production backlog', 'source_record_id': 'NOTICE-001'}],
        'offers': [
            {'offer_id': 'QUOTE-B', 'supplier_id': 'SUP-B', 'material_id': 'MAT-01',
             'specification': 'SPEC-A', 'available_quantity': 150, 'minimum_quantity': 20,
             'usable_arrival_date': '2026-11-03', 'unit_price_cents': 1200,
             'shipping_cents': 5000, 'currency': 'USD', 'valid_until': '2026-11-02'},
            {'offer_id': 'QUOTE-C', 'supplier_id': 'SUP-C', 'material_id': 'MAT-01',
             'specification': 'SPEC-A', 'available_quantity': 200, 'minimum_quantity': 10,
             'usable_arrival_date': '2026-11-02', 'unit_price_cents': 900,
             'shipping_cents': 3000, 'currency': 'USD', 'valid_until': '2026-11-02'},
        ],
    }
    (output_dir / 'supplier_fixture.json').write_text(json.dumps(fixture, indent=2) + '\n')
    print('Created factory.sqlite and synthetic supplier_fixture.json')


if __name__ == '__main__':
    seed()
