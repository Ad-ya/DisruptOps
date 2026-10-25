import json
import sqlite3
from contextlib import closing
from pathlib import Path

from supply_chain_poc.schemas.incidents import PastIncident


def setup_incidents(database_path: Path, fixture_path: Path) -> dict:
    if not database_path.is_file():
        raise FileNotFoundError(f'Factory database not found: {database_path}')
    incidents = [PastIncident.model_validate(row).model_dump(mode='json')
                 for row in json.loads(fixture_path.read_text())]
    if any(row['source_type'] != 'synthetic' for row in incidents):
        raise ValueError('Demo setup only imports explicitly synthetic incidents')
    if len({row['id'] for row in incidents}) != len(incidents):
        raise ValueError('Duplicate incident IDs in fixture')
    sql = (Path(__file__).parent / 'migrations/001_past_incidents.sql').read_text()
    inserted = 0
    with closing(sqlite3.connect(database_path)) as db, db:
        db.execute('PRAGMA foreign_keys=ON')
        db.execute(sql)
        for row in incidents:
            columns = ','.join(row)
            placeholders = ','.join('?' for _ in row)
            inserted += db.execute(f'INSERT INTO past_incidents ({columns}) VALUES ({placeholders}) '
                                   'ON CONFLICT(id) DO NOTHING', tuple(row.values())).rowcount
    return {'inserted': inserted, 'fixture_count': len(incidents),
            'note': 'Existing factory records and incident rows are not overwritten.'}
