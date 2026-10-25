import json
from urllib.error import URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import urlopen

from supply_chain_poc.core.suppliers.base_supplier_client import BaseSupplierClient


class HttpSupplierClient(BaseSupplierClient):
    def __init__(self, base_url: str, timeout_seconds: float = 5) -> None:
        if urlparse(base_url).scheme not in {'http', 'https'} or timeout_seconds <= 0:
            raise ValueError('An HTTP(S) supplier URL and positive timeout are required')
        self.base_url = base_url.rstrip('/')
        self.timeout_seconds = timeout_seconds

    def _get(self, endpoint: str) -> dict:
        try:
            with urlopen(self.base_url + endpoint, timeout=self.timeout_seconds) as response:
                payload = json.load(response)
        except (URLError, TimeoutError, OSError, ValueError) as error:
            raise RuntimeError(f'Supplier API unavailable or invalid response: {error}') from error
        if not isinstance(payload, dict) or not isinstance(payload.get('records'), list):
            raise ValueError('Supplier response must contain a records list')
        if not all(isinstance(row, dict) for row in payload['records']):
            raise ValueError('Supplier records must be objects')
        return payload

    def get_supplier_update(self, shipment_id: str) -> dict:
        """Fetch the supplier's revised shipment date, quantity and notice reference over HTTP."""
        payload = self._get('/shipments/' + quote(shipment_id, safe=''))
        rows = payload['records']
        if len(rows) != 1 or rows[0].get('shipment_id') != shipment_id:
            raise ValueError(f'No unambiguous supplier update for shipment: {shipment_id}')
        return payload

    def get_alternative_offers(self, material_id: str) -> dict:
        """Fetch offer IDs, material specifications, capacities, dates, prices and freight over HTTP."""
        payload = self._get('/offers?' + urlencode({'material_id': material_id}))
        if any(row.get('material_id') != material_id for row in payload['records']):
            raise ValueError('Supplier returned an offer for a different material')
        return payload
