import json


def render_case(case: dict) -> str:
    lines = [f'Thread: {case["thread_id"]}; status: {case["status"]}; version: {case["comparison_version"]}']
    if case.get('reason'):
        lines.append(case['reason'])
    if case.get('comparison'):
        lines += ['', render_comparison(case['comparison'])]
    if case.get('decision_template'):
        lines += ['', f'Approval expires at {case["approval_expires_at"]}.', case['decision_instructions'],
                  '', json.dumps(case['decision_template'], indent=2)]
    elif case.get('decision'):
        lines += ['', f'Decision: {case["decision"]["action"]}; reviewer: {case["decision"]["reviewer_id"]}.',
                  case['decision']['scope']]
    return '\n'.join(lines)


def render_comparison(comparison: dict) -> str:
    lines = [f'Case material: {comparison["material_id"]}; snapshot: {comparison["snapshot_id"]}',
             f'Planning window: {comparison["start_date"]} to {comparison["end_date"]}; currency: USD', '',
             f'Opening stock: {comparison["opening_stock"]} {comparison["unit"]}; safety buffer: {comparison["safety_stock"]}.', '',
             '| Scenario | Choice | Extra spend | Units missing due date | Unmet at horizon | Minimum stock | Buffer breach days | Matched incidents |',
             '|---|---|---:|---:|---:|---:|---:|---:|']
    for option in comparison['options']:
        for name, impact in option['scenarios'].items():
            cents = impact['additional_spend_cents']
            money = f'${cents // 100:,}.{cents % 100:02}'
            lines.append(f'| {name} | {option["label"]} | {money} | {impact["missed_due_date_units"]} | '
                         f'{impact["unfulfilled_at_horizon"]} | {impact["minimum_closing_stock"]} | {impact["days_below_safety_stock"]} | '
                         f'{option["historical_evidence"]["sample_count"]} |')
    lines += ['', f'Rule-based recommendation: {comparison["recommended_option_id"]}', comparison['ranking_basis'], '',
              'Historical observations (not causal claims or predicted probabilities):']
    for option in comparison['options']:
        history = option['historical_evidence']
        lines.append(f'- {option["option_id"]}: {history["sample_count"]} matched observations; '
                     f'{history["incidents_with_unfulfilled_demand"]} had unfulfilled demand at their horizon.')
        delivery = option['supplier_delivery_history']
        lines.append(f'  - Supplier delivery record: {delivery["full_and_on_time"]}/{delivery["sample_count"]} '
                     'recorded deliveries were full and on time; a zero sample means no evidence.')
        for incident in history['records']:
            lines.append(f'  - {incident["id"]} [{incident["source_type"]}]: '
                         f'{incident["observed_unfulfilled_units"]} unmet units, '
                         f'{incident["observed_buffer_breach_days"]} buffer-breach days; {incident["notes"]}')
    if comparison['excluded_offers']:
        lines += ['', 'Excluded offers:'] + [f'- {row["offer_id"]}: {row["reason"]}' for row in comparison['excluded_offers']]
    lines += ['', 'Assumptions and limitations:'] + [f'- {text}' for text in comparison['assumptions'] + comparison['unknowns']]
    return '\n'.join(lines)
