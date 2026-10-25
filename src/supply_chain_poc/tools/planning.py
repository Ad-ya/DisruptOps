from datetime import date

from supply_chain_poc.tools.calculations import calculate_purchase_cost


def validate_offer(material: dict, supplier: dict, offer: dict, quantity: int, decision_date: str) -> dict:
    """Validate a captured offer and calculate cents without fetching changing inputs."""
    if type(quantity) is not int or quantity <= 0:
        raise ValueError('quantity must be a positive whole number')
    decision_day = date.fromisoformat(decision_date)
    offer_id = offer['offer_id']
    if offer['material_id'] != material['id'] or offer['supplier_id'] != supplier['id']:
        raise ValueError('Offer material or supplier identity mismatch')
    if not supplier['approved'] or offer['specification'] != material['specification']:
        raise ValueError('Supplier is unapproved or material specification is incompatible')
    if offer['currency'] != 'USD':
        raise ValueError('POC supports USD only')
    minimum, available = offer['minimum_quantity'], offer['available_quantity']
    if any(type(value) is not int for value in (minimum, available)) or not 0 < minimum <= quantity <= available:
        raise ValueError('Quantity violates minimum order or confirmed availability')
    arrival = date.fromisoformat(offer['usable_arrival_date'])
    if decision_day > date.fromisoformat(offer['valid_until']) or arrival < decision_day:
        raise ValueError('Offer has expired or arrival date is before the decision date')
    cost = calculate_purchase_cost(quantity, offer['unit_price_cents'], offer['shipping_cents'])
    return {'offer_id': offer_id, 'supplier_id': offer['supplier_id'],
            'quantity': quantity, 'usable_date': arrival.isoformat(), **cost}


def shipment_receipts(shipments: list[dict], notices: dict[str, dict], start_date: str) -> dict[str, int]:
    receipts = {}
    for shipment in shipments:
        update = notices[shipment['id']]
        expected = (shipment['id'], shipment['supplier_id'], shipment['material_id'], shipment['quantity'])
        actual = (update['shipment_id'], update['supplier_id'], update['material_id'], update['quantity'])
        if actual != expected:
            raise ValueError('Supplier notice conflicts with the factory shipment identity or quantity')
        usable_date = date.fromisoformat(update['revised_usable_date']).isoformat()
        if usable_date < start_date:
            raise ValueError('Overdue shipment requires inventory reconciliation')
        receipts[usable_date] = receipts.get(usable_date, 0) + shipment['quantity']
    return receipts


def simulate_stock(context: dict, requirements: dict, receipts: dict[str, int],
                   priced: list[dict], demand_percent: int = 100) -> dict:
    """FIFO backlog fulfillment; count newly late requirements once, separately from ending backlog."""
    if type(demand_percent) is not int or demand_percent <= 0:
        raise ValueError('demand_percent must be positive')
    stock, safety = context['inventory']['usable_quantity'], context['material']['safety_stock']
    backlog, timeline = 0, []
    for day, base_requirement in requirements['daily'].items():
        demand = (base_requirement * demand_percent + 99) // 100
        opening, received, previous_backlog = stock, receipts.get(day, 0), backlog
        fulfilled = min(stock + received, demand + previous_backlog)
        newly_late = demand - max(0, fulfilled - previous_backlog)
        stock = stock + received - fulfilled
        backlog = previous_backlog + demand - fulfilled
        timeline.append({'day': day, 'opening_stock': opening, 'receipts': received,
                         'new_requirement': demand, 'fulfilled': fulfilled,
                         'closing_stock': stock, 'backlog': backlog, 'newly_late_units': newly_late})
    end = timeline[-1]['day']
    return {'material_id': context['material']['id'], 'demand_percent': demand_percent,
            'timeline': timeline, 'unfulfilled_at_horizon': backlog,
            'total_required': sum(row['new_requirement'] for row in timeline),
            'missed_due_date_units': sum(row['newly_late_units'] for row in timeline),
            'first_shortage_date': next((row['day'] for row in timeline if row['backlog']), None),
            'peak_backlog': max(row['backlog'] for row in timeline),
            'days_with_backlog': sum(row['backlog'] > 0 for row in timeline),
            'days_below_safety_stock': sum(row['closing_stock'] < safety for row in timeline),
            'minimum_closing_stock': min(row['closing_stock'] for row in timeline),
            'additional_spend_cents': sum(row['total_cents'] for row in priced),
            'validated_purchases': priced, 'demand_provenance': requirements['supporting_orders'],
            'later_receipts': {day: qty for day, qty in receipts.items() if day > end}}

