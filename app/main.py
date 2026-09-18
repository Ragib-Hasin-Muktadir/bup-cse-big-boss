from __future__ import annotations

import logging
import time
from typing import List

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.guardrails import validate_all
from app.llm_interpreter import interpret_notes
from app.optimizer import solve_schedule
from app.schemas import (
    DirectiveInterpretation,
    HourlyPlanEntry,
    OptimizeRequest,
    OptimizeResponse,
)
from app.validator import validate_plan

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gridwise")

app = FastAPI(title="GridWise Energy Optimizer", version="1.0.0")


@app.exception_handler(RequestValidationError)
async def validation_handler(request, exc: RequestValidationError):
    return JSONResponse(
        status_code=400,
        content={"error": "invalid_request", "detail": exc.errors()},
    )


@app.get("/health")
def health():
    return {"status": "ok"}


def _summary(plan: List[HourlyPlanEntry], directives: List[DirectiveInterpretation],
             total_cost: float, total_grid: float, peak: float) -> str:
    applied = [d.directive_type for d in directives if d.applies]
    charge_h = [p.hour for p in plan if p.battery_action == "charge"]
    dis_h = [p.hour for p in plan if p.battery_action == "discharge"]
    parts = [
        f"Total grid import {total_grid:.2f} kWh costing {total_cost:.2f} BDT, peaking at {peak:.2f} kWh.",
        f"Battery charges in hours {charge_h} and discharges in hours {dis_h}." if (charge_h or dis_h)
        else "Battery stays idle across the day.",
    ]
    parts.append(
        f"Applied operator directives: {', '.join(applied)}." if applied
        else "No operator directive changed the baseline schedule."
    )
    return " ".join(parts)


@app.post("/optimize-energy", response_model=OptimizeResponse)
def optimize_energy(request: OptimizeRequest):
    t0 = time.perf_counter()

    raw = interpret_notes(request.operator_notes)
    directives = validate_all(raw, request.battery)
    plan, mode = solve_schedule(request, directives)

    ok, issues = validate_plan(plan, request.hours, request.battery)
    if not ok:
        log.warning("plan invalid (%s): %s", mode, issues[:5])
        plan, mode = solve_schedule(request, [])
        ok, issues = validate_plan(plan, request.hours, request.battery)
        if not ok:
            log.error("fallback plan still invalid: %s", issues[:5])

    by_hour = {h.hour: h for h in request.hours}
    total_grid = sum(p.grid_kwh for p in plan)
    total_cost = sum(p.grid_kwh * by_hour[p.hour].tariff_bdt_per_kwh for p in plan)
    peak = max((p.grid_kwh for p in plan), default=0.0)

    log.info("scenario=%s mode=%s latency=%.2fs", request.scenario_id, mode, time.perf_counter() - t0)

    return OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=directives,
        hourly_plan=sorted(plan, key=lambda p: p.hour),
        total_grid_kwh=round(total_grid, 3),
        total_cost_bdt=round(total_cost, 3),
        peak_grid_kwh=round(peak, 3),
        plan_summary=_summary(plan, directives, total_cost, total_grid, peak),
    )