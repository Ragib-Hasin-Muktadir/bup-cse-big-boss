from __future__ import annotations

from typing import List, Optional, Tuple

import pulp

from app.schemas import (
    OptimizeRequest,
    HourlyPlanEntry,
    DirectiveInterpretation,
    StructuredAdjustment,
)

EPS = 1e-6
ALL_HOURS = list(range(24))


# ---------- directive → constraint data ----------

def _collect(directives: List[DirectiveInterpretation], dtype: str) -> List[StructuredAdjustment]:
    out = []
    for d in directives:
        if d.applies and d.directive_type == dtype and d.structured_adjustment is not None:
            out.append(d.structured_adjustment)
    return out


def _target_hours(sa: StructuredAdjustment) -> List[int]:
    if sa.hours:
        return [h for h in sa.hours if 0 <= h <= 23]
    return ALL_HOURS


def _build_limits(request: OptimizeRequest, directives: List[DirectiveInterpretation]):
    b = request.battery

    solar_factor = {h: 1.0 for h in ALL_HOURS}
    for sa in _collect(directives, "solar_reduction"):
        if sa.factor is None:
            continue
        f = max(0.0, min(1.0, float(sa.factor)))
        for h in _target_hours(sa):
            solar_factor[h] = min(solar_factor[h], f)

    reserve = {h: b.minimum_energy_kwh for h in ALL_HOURS}
    for sa in _collect(directives, "minimum_battery_reserve"):
        if sa.minimum_energy_kwh is None:
            continue
        m = min(float(sa.minimum_energy_kwh), b.capacity_kwh)
        for h in _target_hours(sa):
            reserve[h] = max(reserve[h], m)

    no_charge, no_discharge = set(), set()
    for sa in _collect(directives, "no_charge_window"):
        no_charge.update(_target_hours(sa))
    for sa in _collect(directives, "no_discharge_window"):
        no_discharge.update(_target_hours(sa))

    max_grid = {}
    for sa in _collect(directives, "max_grid_window"):
        if sa.max_grid_kwh is None:
            continue
        cap = max(0.0, float(sa.max_grid_kwh))
        for h in _target_hours(sa):
            max_grid[h] = min(max_grid.get(h, float("inf")), cap)

    return solar_factor, reserve, no_charge, no_discharge, max_grid


# ---------- core LP ----------

def _solve(
    request: OptimizeRequest,
    directives: List[DirectiveInterpretation],
    enforce_end_neutrality: bool,
    soft: bool,
) -> Optional[List[HourlyPlanEntry]]:
    hours = sorted(request.hours, key=lambda h: h.hour)
    b = request.battery

    solar_factor, reserve, no_charge, no_discharge, max_grid = _build_limits(request, directives)

    max_tariff = max((h.tariff_bdt_per_kwh for h in hours), default=1.0) or 1.0
    penalty = 1000.0 * max_tariff
    tie_break = 1e-4 * max_tariff

    prob = pulp.LpProblem("GridWise", pulp.LpMinimize)

    grid, solar_used, charge, discharge, soc = {}, {}, {}, {}, {}
    slack_grid, slack_res = {}, {}

    for h in hours:
        i = h.hour
        grid[i] = pulp.LpVariable(f"grid_{i}", lowBound=0)
        solar_used[i] = pulp.LpVariable(f"solar_{i}", lowBound=0)
        charge[i] = pulp.LpVariable(f"chg_{i}", lowBound=0, upBound=b.max_charge_kwh_per_hour)
        discharge[i] = pulp.LpVariable(f"dis_{i}", lowBound=0, upBound=b.max_discharge_kwh_per_hour)
        soc[i] = pulp.LpVariable(f"soc_{i}", lowBound=0, upBound=b.capacity_kwh)
        slack_grid[i] = pulp.LpVariable(f"sg_{i}", lowBound=0)
        slack_res[i] = pulp.LpVariable(f"sr_{i}", lowBound=0)

    obj = pulp.lpSum(grid[h.hour] * h.tariff_bdt_per_kwh for h in hours)
    obj += tie_break * pulp.lpSum(charge[h.hour] + discharge[h.hour] for h in hours)
    if soft:
        obj += penalty * pulp.lpSum(slack_grid[h.hour] + slack_res[h.hour] for h in hours)
    prob += obj

    prev = b.initial_energy_kwh
    for h in hours:
        i = h.hour

        prob += solar_used[i] + grid[i] + discharge[i] == h.demand_kwh + charge[i]
        prob += solar_used[i] <= h.solar_kwh * solar_factor[i]