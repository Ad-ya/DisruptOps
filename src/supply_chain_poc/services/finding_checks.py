
def check_finding_against_comparison(finding: dict, comparison: dict) -> None:
    """Schema validity alone cannot make invented option IDs or altered metrics valid."""
    if finding['status'] != 'ok':
        return
    role = finding['role']
    option_ids = {row['option_id'] for row in comparison['options']}
    if role == 'disruption':
        for key in ('shipment_id', 'material_id', 'quantity', 'revised_usable_date'):
            if finding[key] != comparison['confirmed_disruption'][key]:
                raise ValueError(f'Disruption finding disagrees with confirmed {key}')
    if role == 'inventory':
        expected = next(row for row in comparison['options'] if row['option_id'] == 'wait')['scenarios']['expected']
        for key in ('material_id', 'first_shortage_date', 'unfulfilled_at_horizon', 'days_below_safety_stock'):
            if finding[key] != expected[key]:
                raise ValueError(f'Inventory finding disagrees with calculated {key}')
    if role == 'procurement':
        if finding['comparison_snapshot_id'] != comparison['snapshot_id']:
            raise ValueError('Finding refers to a different comparison snapshot')
        listed = finding['option_ids']
        if set(listed) != option_ids:
            raise ValueError('Finding omits or invents comparison options')
        known = {comparison['snapshot_id'], *(eid for row in comparison['options'] for eid in row['evidence_ids'])}
        if set(finding['evidence_ids']) - known:
            raise ValueError('Finding cites evidence absent from the comparison')

