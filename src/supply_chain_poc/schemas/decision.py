from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator

from supply_chain_poc.schemas.findings import validate_finding
from supply_chain_poc.services.finding_checks import check_finding_against_comparison


class HumanDecision(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    action: Literal['approve', 'reject', 'request_changes']
    reviewer_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    thread_id: str = Field(min_length=1)
    snapshot_id: str = Field(min_length=1)
    comparison_version: StrictInt = Field(ge=1)
    option_id: str | None = None
    acknowledge_consequences: StrictBool = False
    comment: str = ''

    @model_validator(mode='after')
    def check_action(self) -> Self:
        if self.action == 'approve' and (not self.option_id or not self.acknowledge_consequences):
            raise ValueError('Approval requires an option and explicit acknowledgement of its consequences')
        if self.action != 'approve' and self.option_id is not None:
            raise ValueError('Only approval selects an option')
        if self.action == 'request_changes' and not self.comment:
            raise ValueError('Requested changes need a comment')
        return self


def validate_human_decision(value: dict, state: dict) -> HumanDecision:
    decision = HumanDecision.model_validate(value)
    if state.get('status') != 'awaiting_approval':
        raise ValueError('This case is not waiting for a human decision')
    case = state['context']
    case_id = case['case_id'] if isinstance(case, dict) else case.case_id
    if decision.thread_id != state['thread_id'] or decision.case_id != case_id:
        raise ValueError('Decision belongs to a different case or thread')
    if decision.snapshot_id != state['comparison']['snapshot_id']:
        raise ValueError('Decision references a different comparison snapshot')
    if decision.comparison_version != state['comparison_version']:
        raise ValueError('Decision references a different comparison version')
    for role in ('disruption', 'inventory', 'procurement'):
        finding = state['results'].get(role, {})
        if finding.get('status') != 'ok':
            raise ValueError('Assessment and procurement findings must be successful before a human decision')
        check_finding_against_comparison(validate_finding(role, finding), state['comparison'])
    actual = {row['option_id'] for row in state['comparison']['options']}
    if decision.action == 'approve' and decision.option_id not in actual:
        raise ValueError('Selected option is absent from the current comparison')
    return decision
