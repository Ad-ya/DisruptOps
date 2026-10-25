from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class PastIncident(BaseModel):
    model_config = ConfigDict(extra='forbid')
    id: str = Field(min_length=1)
    material_id: str
    supplier_id: str
    occurred_on: date
    delay_days: int = Field(ge=0)
    stock_cover_days: float = Field(ge=0)
    daily_requirement: int = Field(gt=0)
    planning_days: int = Field(ge=1, le=30)
    action: Literal['wait', 'bridge', 'protect_buffer']
    replacement_supplier_id: str | None = None
    observed_unfulfilled_units: int = Field(ge=0)
    observed_buffer_breach_days: int = Field(ge=0)
    observed_additional_cost_cents: int = Field(ge=0)
    notes: str
    source_type: Literal['synthetic', 'recorded']
