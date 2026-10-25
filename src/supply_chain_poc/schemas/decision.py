from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, model_validator



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

