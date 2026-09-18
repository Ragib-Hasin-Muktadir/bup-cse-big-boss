from typing import List, Optional, Literal, Dict, Any
from pydantic import BaseModel, Field, field_validator


# ---------- Input models ----------

class HourEntry(BaseModel):
    hour: int
    demand_kwh: float
    solar_kwh: float
    tariff_bdt_per_kwh: float


class Battery(BaseModel):
    capacity_kwh: float
    initial_energy_kwh: float
    minimum_energy_kwh: float
    max_charge_kwh_per_hour: float
    max_discharge_kwh_per_hour: float


class OptimizeRequest(BaseModel):
    scenario_id: str
    operator_notes: List[str] = Field(..., min_length=1, max_length=3)
    hours: List[HourEntry] = Field(..., min_length=24, max_length=24)
    battery: Battery

    @field_validator("hours")
    @classmethod
    def check_hours(cls, v: List[HourEntry]):
        hour_values = sorted(h.hour for h in v)
        if hour_values != list(range(24)):
            raise ValueError("hours must contain exactly 24 unique entries for hours 0-23")
        return v


# ---------- Directive interpretation (output of LLM + guardrail) ----------

DirectiveType = Literal[
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
]


class StructuredAdjustment(BaseModel):
    # Union of all possible directive shapes — only relevant fields are set
    # depending on directive_type. Keep flexible instead of strict Union
    # to save time; guardrail_validator.py enforces per-type correctness.
    hours: Optional[List[int]] = None
    factor: Optional[float] = None                # solar_reduction
    minimum_energy_kwh: Optional[float] = None     # minimum_battery_reserve
    max_grid_kwh: Optional[float] = None           # max_grid_window


class DirectiveInterpretation(BaseModel):
    note_index: int
    applies: bool
    directive_type: DirectiveType
    structured_adjustment: Optional[StructuredAdjustment] = None
    explanation: str


# ---------- Output plan ----------

BatteryAction = Literal["charge", "discharge", "idle"]


class HourlyPlanEntry(BaseModel):
    hour: int
    grid_kwh: float
    solar_used_kwh: float
    battery_action: BatteryAction
    battery_kwh: float
    battery_energy_after_kwh: float


class OptimizeResponse(BaseModel):
    scenario_id: str
    directive_interpretation: List[DirectiveInterpretation]
    hourly_plan: List[HourlyPlanEntry] = Field(..., min_length=24, max_length=24)
    total_grid_kwh: float
    total_cost_bdt: float
    peak_grid_kwh: float
    plan_summary: str