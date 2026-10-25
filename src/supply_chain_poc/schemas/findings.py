from datetime import date
from typing import Annotated, ClassVar, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StrictInt, computed_field, model_validator


class AgentFinding(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    ROLE: ClassVar[str]
    status: Literal['ok', 'needs_information', 'failed'] = Field(
        description='ok only when required facts are verified and unresolved_questions is empty; otherwise needs_information or failed.')
    summary: str = Field(min_length=1)
    evidence_ids: list[Annotated[str, Field(min_length=1)]] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list,
        description='Nonblocking caveats and simulation assumptions; these do not prevent the assigned assessment.')
    unresolved_questions: list[str] = Field(default_factory=list,
        description='Blocking missing facts only. Must be [] for ok; needs_information must name the missing facts.')

    @computed_field
    @property
    def role(self) -> str:
        """Trusted agent identity; not a field the language model must generate."""
        return self.ROLE

    @model_validator(mode='after')
    def check_evidence(self) -> Self:
        if self.status == 'ok' and not self.evidence_ids:
            raise ValueError('A successful finding needs supporting evidence IDs')
        if self.status == 'needs_information' and not self.unresolved_questions:
            raise ValueError('Specify what information is missing')
        if self.status == 'ok' and self.unresolved_questions:
            raise ValueError('Missing required answers must use needs_information')
        return self


class DisruptionFinding(AgentFinding):
    ROLE = 'disruption'
    shipment_id: str | None = None
    material_id: str | None = None
    revised_usable_date: date | None = None
    quantity: StrictInt | None = Field(default=None, ge=1)
    historical_incident_ids: list[str] = Field(default_factory=list)

    @model_validator(mode='after')
    def check_confirmed_shipment(self) -> Self:
        if self.status == 'ok' and any(value is None for value in (
                self.shipment_id, self.material_id, self.revised_usable_date, self.quantity)):
            raise ValueError('A confirmed disruption needs shipment, material, date and quantity')
        return self


class InventoryFinding(AgentFinding):
    ROLE = 'inventory'
    material_id: str | None = None
    first_shortage_date: date | None = None
    unfulfilled_at_horizon: StrictInt | None = Field(default=None, ge=0)
    days_below_safety_stock: StrictInt | None = Field(default=None, ge=0, le=30)

    @model_validator(mode='after')
    def check_computed_impact(self) -> Self:
        if self.status == 'ok' and any(value is None for value in (
                self.material_id, self.unfulfilled_at_horizon, self.days_below_safety_stock)):
            raise ValueError('A successful inventory finding needs computed impact fields')
        return self


class ProcurementFinding(AgentFinding):
    ROLE = 'procurement'
    comparison_snapshot_id: str | None = None
    option_ids: list[str] = Field(default_factory=list)
    recommended_option_id: str | None = None

    @model_validator(mode='after')
    def check_recommendation(self) -> Self:
        if self.status == 'ok' and (not self.comparison_snapshot_id or
                self.recommended_option_id not in self.option_ids):
            raise ValueError('Recommendation must identify its comparison snapshot and a listed option')
        return self


FINDING_SCHEMAS = {'disruption': DisruptionFinding, 'inventory': InventoryFinding,
                   'procurement': ProcurementFinding}


def validate_finding(role: str, value: dict) -> dict:
    if 'role' in value and value['role'] != role:
        raise ValueError('Finding belongs to a different configured agent')
    payload = {key: item for key, item in value.items() if key != 'role'}
    return FINDING_SCHEMAS[role].model_validate(payload).model_dump(mode='json')
