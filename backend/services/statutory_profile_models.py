"""Request models for effective-dated employment statutory profiles."""

from datetime import date
from typing import Literal

from pydantic import BaseModel, ConfigDict, model_validator


class EmploymentStatutoryProfileIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effective_from: date
    effective_to: date | None = None
    work_location_id: str | None = None
    establishment_id: str | None = None
    work_state: str | None = None
    municipality: str | None = None
    pf_applicable: bool | None = None
    epf_membership_status: Literal["member", "not_member"] | None = None
    eps_applicable: bool | None = None
    membership_effective_from: date | None = None
    pf_on_higher_wages: bool | None = None
    pt_applicable: bool | None = None
    pt_employee_category: str | None = None
    lwf_applicable: bool | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from")
        return self


class StatutoryEstablishmentIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    location_id: str | None = None
    pf_covered: bool | None = None
    pf_scheme_category: str | None = None
    lwf_covered: bool | None = None
    lwf_category: str | None = None
    effective_from: date
    effective_to: date | None = None

    @model_validator(mode="after")
    def valid_range(self):
        if self.effective_to and self.effective_to < self.effective_from:
            raise ValueError("effective_to must be on or after effective_from")
        return self
