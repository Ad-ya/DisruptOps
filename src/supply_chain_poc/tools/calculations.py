def calculate_material_requirement(scheduled_quantity: int, completed_quantity: int,
                                   quantity_per_product: int) -> int:
    """Calculate remaining whole material units for one scheduled production-order line.

    Inputs must come from verified schedule and BOM records; this calculator does not fetch them.
    """
    if any(type(value) is not int for value in (scheduled_quantity, completed_quantity, quantity_per_product)):
        raise ValueError('Quantities must be whole integers')
    if not 0 <= completed_quantity <= scheduled_quantity or quantity_per_product <= 0:
        raise ValueError('Invalid schedule, completion or BOM quantity')
    return (scheduled_quantity - completed_quantity) * quantity_per_product


def calculate_purchase_cost(quantity: int, unit_price_cents: int, shipping_cents: int = 0) -> dict[str, int]:
    """Calculate purchase and shipping costs in integer cents from verified offer inputs.

    This calculator does not confirm supplier approval, quote validity, availability or delivery.
    """
    if any(type(value) is not int for value in (quantity, unit_price_cents, shipping_cents)):
        raise ValueError('Quantity and monetary inputs must be whole integers')
    if quantity <= 0 or min(unit_price_cents, shipping_cents) < 0:
        raise ValueError('Quantity must be positive; costs cannot be negative')
    purchase = quantity * unit_price_cents
    return {'purchase_cents': purchase, 'shipping_cents': shipping_cents,
            'total_cents': purchase + shipping_cents}


