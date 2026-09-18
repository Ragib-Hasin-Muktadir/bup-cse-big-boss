from __future__ import annotations

from typing import List

from app.schemas import Battery, DirectiveInterpretation, StructuredAdjustment

VALID_HOURS = set(range(24))


def _clean_hours(raw) -> List[int]:
    if not isinstance(raw, list):
        return []
    out = set()
    for x in raw:
        try:
            h = int(x)
        except (TypeError, ValueError):
            continue
        if h in VALID_HOURS:
            out.add(h)
    return sorted(out)


def _reject(d: DirectiveInterpretation, reason: str) -> DirectiveInterpretation:
    return DirectiveInterpretation(
        note_index=d.note_index,
        applies=False,
        directive_type="no_op",
        structured_adjustment=None,
        explanation=f"{d.explanation} [Rejected by guardrail: {reason}]",
    )


def validate_directive(d: DirectiveInterpretation, battery: Battery) -> DirectiveInterpretation:
    if d.directive_type == "no_op" or not d.applies:
        return DirectiveInterpretation(
            note_index=d.note_index,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation=d.explanation,
        )

    sa = d.structured_adjustment
    if sa is None:
        return _reject(d, "missing structured_adjustment")

    hours = _clean_hours(sa.hours)
    t = d.directive_type

    if t in ("no_charge_window", "no_discharge_window") and not hours:
        return _reject(d, "no valid hours given")

    if t == "solar_reduction":
        if sa.factor is None:
            return _reject(d, "missing factor")
        f = float(sa.factor)
        if f > 1.0:                      # "reduce by 30" ভুল করে 30 দিলে
            f = f / 100.0 if f <= 100 else 1.0
        f = max(0.0, min(1.0, f))
        clean = StructuredAdjustment(hours=hours or sorted(VALID_HOURS), factor=f)

    elif t == "minimum_battery_reserve":
        if sa.minimum_energy_kwh is None:
            return _reject(d, "missing minimum_energy_kwh")
        m = max(0.0, float(sa.minimum_energy_kwh))
        m = min(m, battery.capacity_kwh)          # ক্যাপাসিটির বাইরে যেতে দেব না
        m = max(m, battery.minimum_energy_kwh)    # হার্ড floor-এর নিচে নামাব না
        clean = StructuredAdjustment(hours=hours or sorted(VALID_HOURS), minimum_energy_kwh=m)

    elif t in ("no_charge_window", "no_discharge_window"):
        clean = StructuredAdjustment(hours=hours)

    elif t == "max_grid_window":
        if sa.max_grid_kwh is None:
            return _reject(d, "missing max_grid_kwh")
        cap = float(sa.max_grid_kwh)
        if cap < 0:
            return _reject(d, "negative max_grid_kwh")
        clean = StructuredAdjustment(hours=hours or sorted(VALID_HOURS), max_grid_kwh=cap)

    else:
        return _reject(d, "unsupported directive type")

    return DirectiveInterpretation(
        note_index=d.note_index,
        applies=True,
        directive_type=t,
        structured_adjustment=clean,
        explanation=d.explanation,
    )


def validate_all(directives: List[DirectiveInterpretation], battery: Battery) -> List[DirectiveInterpretation]:
    return [validate_directive(d, battery) for d in directives]