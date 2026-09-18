from fastapi import FastAPI
from app.schemas import (
    OptimizeRequest,
    OptimizeResponse,
    DirectiveInterpretation,
    HourlyPlanEntry,
)

app = FastAPI(title="GridWise Energy Optimizer")


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/optimize-energy", response_model=OptimizeResponse)
def optimize_energy(request: OptimizeRequest):
    return build_dummy_response(request)


def build_dummy_response(request: OptimizeRequest) -> OptimizeResponse:
    interpretations = [
        DirectiveInterpretation(
            note_index=i,
            applies=False,
            directive_type="no_op",
            structured_adjustment=None,
            explanation="Dummy placeholder — pipeline not yet implemented.",
        )
        for i in range(len(request.operator_notes))
    ]

    sorted_hours = sorted(request.hours, key=lambda x: x.hour)
    hourly_plan = [
        HourlyPlanEntry(
            hour=h.hour,
            grid_kwh=h.demand_kwh,
            solar_used_kwh=0,
            battery_action="idle",
            battery_kwh=0,
            battery_energy_after_kwh=request.battery.initial_energy_kwh,
        )
        for h in sorted_hours
    ]

    total_grid = sum(e.grid_kwh for e in hourly_plan)
    total_cost = sum(e.grid_kwh * h.tariff_bdt_per_kwh for e, h in zip(hourly_plan, sorted_hours))
    peak_grid = max(e.grid_kwh for e in hourly_plan)

    return OptimizeResponse(
        scenario_id=request.scenario_id,
        directive_interpretation=interpretations,
        hourly_plan=hourly_plan,
        total_grid_kwh=total_grid,
        total_cost_bdt=total_cost,
        peak_grid_kwh=peak_grid,
        plan_summary="Dummy plan — grid covers full demand, no optimization yet.",
    )