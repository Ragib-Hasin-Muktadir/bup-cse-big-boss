from __future__ import annotations

from typing import List, Tuple

from app.schemas import Battery, HourEntry, HourlyPlanEntry

TOL = 1e-3


def validate_plan(
    plan: List[HourlyPlanEntry],
    hours: List[HourEntry],
    battery: Battery,
) -> Tuple[bool, List[str]]:
    issues: List[str] = []
    by_hour = {h.hour: h for h in hours}

    if len(plan) != 24:
        issues.append(f"plan has {len(plan)} entries, expected 24")
    if sorted(p.hour for p in plan) != list(range(24)):
        issues.append("plan hours are not exactly 0-23")

    soc = battery.initial_energy_kwh
    for p in sorted(plan, key=lambda x: x.hour):
        h = by_hour.get(p.hour)
        if h is None:
            issues.append(f"hour {p.hour} not in input")
            continue

        if p.grid_kwh < -TOL:
            issues.append(f"hour {p.hour}: negative grid")
        if p.solar_used_kwh < -TOL or p.solar_used_kwh > h.solar_kwh + TOL:
            issues.append(f"hour {p.hour}: solar_used out of range")

        chg = p.battery_kwh if p.battery_action == "charge" else 0.0
        dis = p.battery_kwh if p.battery_action == "discharge" else 0.0

        if chg > battery.max_charge_kwh_per_hour + TOL:
            issues.append(f"hour {p.hour}: charge exceeds limit")
        if dis > battery.max_discharge_kwh_per_hour + TOL:
            issues.append(f"hour {p.hour}: discharge exceeds limit")

        supply = p.solar_used_kwh + p.grid_kwh + dis
        need = h.demand_kwh + chg
        if abs(supply - need) > 1e-2:
            issues.append(f"hour {p.hour}: energy balance off by {supply - need:.4f}")

        soc = soc + chg - dis
        if soc < battery.minimum_energy_kwh - TOL:
            issues.append(f"hour {p.hour}: SOC below minimum")
        if soc > battery.capacity_kwh + TOL:
            issues.append(f"hour {p.hour}: SOC above capacity")
        if abs(soc - p.battery_energy_after_kwh) > 1e-2:
            issues.append(f"hour {p.hour}: reported SOC mismatch")

    return (len(issues) == 0), issues