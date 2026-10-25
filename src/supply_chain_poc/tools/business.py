from datetime import date

from supply_chain_poc.core.database.base_repository import BaseFactoryRepository
from supply_chain_poc.core.suppliers.base_supplier_client import BaseSupplierClient
from supply_chain_poc.models import PurchaseLine
from supply_chain_poc.tools.planning import shipment_receipts, simulate_stock, validate_offer


class BusinessTools:
    def __init__(self, repository: BaseFactoryRepository, supplier_client: BaseSupplierClient) -> None:
        self.repository = repository
        self.supplier_client = supplier_client

    def price_purchase(self, material_id: str, offer_id: str, quantity: int, decision_date: str) -> dict:
        """Fetch and validate a supplier offer, then calculate replacement spending in USD cents. No order is placed."""
        if type(quantity) is not int or quantity <= 0:
            raise ValueError('quantity must be a positive whole number')
        date.fromisoformat(decision_date)
        offers = self.supplier_client.get_alternative_offers(material_id)['records']
        matches = [offer for offer in offers if offer.get('offer_id') == offer_id]
        if len(matches) != 1:
            raise ValueError('Unknown or ambiguous offer for this material')
        offer = matches[0]
        context = self.repository.get_material_context(material_id)
        supplier = self.repository.get_supplier(offer['supplier_id'])
        return validate_offer(context['material'], supplier, offer, quantity, decision_date)

    def _shipment_receipts(self, shipments: list[dict], start_date: str) -> dict[str, int]:
        notices = {row['id']: self.supplier_client.get_supplier_update(row['id'])['records'][0] for row in shipments}
        return shipment_receipts(shipments, notices, start_date)

    def project_stock(self, material_id: str, start_date: str, days: int = 5,
                      purchases: list[PurchaseLine] | None = None, demand_percent: int = 100) -> dict:
        """Project daily stock and unmet demand from active orders and current supplier notices.

        purchases is a list of {offer_id, quantity}. Prices, capacities and dates are fetched
        and validated, never accepted from the caller. Original orders remain scheduled.
        demand_percent=120 is an explicit stress assumption. Nothing is purchased.
        """
        context = self.repository.get_material_context(material_id)
        if start_date != context['inventory']['as_of']:
            raise ValueError('Projection must begin on the opening inventory snapshot date')
        if type(demand_percent) is not int or demand_percent <= 0:
            raise ValueError('demand_percent must be a positive integer')
        requirements = self.repository.get_requirements(material_id, start_date, days)
        receipts = self._shipment_receipts(context['shipments'], start_date)
        priced, seen = [], set()
        for purchase in purchases or []:
            if purchase['offer_id'] in seen:
                raise ValueError('Use one line per offer so total quantity is checked against capacity')
            seen.add(purchase['offer_id'])
            line = self.price_purchase(material_id, purchase['offer_id'], purchase['quantity'], start_date)
            priced.append(line)
            day = line['usable_date']
            receipts[day] = receipts.get(day, 0) + line['quantity']
        return simulate_stock(context, requirements, receipts, priced, demand_percent)
