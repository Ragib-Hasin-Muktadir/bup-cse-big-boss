# GridWise — LLM-Directed Campus Energy Optimizer

BUP CSE Fest 2026 Hackathon · Team <your team name>

An HTTP API that reads free-text operator notes, converts them into structured
energy directives using an LLM, and produces a cost-minimal 24-hour campus
energy schedule that respects those directives.

## Live endpoint
- Base URL: https://bup-cse-big-boss.onrender.com
- Health:   https://bup-cse-big-boss.onrender.com/health
- Docs:     https://bup-cse-big-boss.onrender.com/docs

## Architecture

Operator notes
  -> LLM Interpreter   (app/llm_interpreter.py)  — Claude, strict JSON, one call for all notes
  -> Guardrail Validator (app/guardrails.py)     — type/range/shape checks, unsafe -> no_op
  -> Math Optimizer    (app/optimizer.py)        — PuLP linear program (CBC solver)
  -> Final Validator   (app/validator.py)        — re-checks energy balance and battery bounds
  -> API Response      (app/main.py)

The LLM is used **only** for interpreting notes into structured directives.
All scheduling decisions come from the linear program — never from the LLM.

## Optimization model

Decision variables per hour h: grid_h, solar_used_h, charge_h, discharge_h, soc_h

Minimize  sum_h (grid_h * tariff_h)

Subject to:
- solar_used_h + grid_h + discharge_h == demand_h + charge_h   (energy balance)
- solar_used_h <= solar_h * solar_factor_h                      (solar availability)
- soc_h == soc_{h-1} + charge_h - discharge_h                   (state of charge)
- minimum_energy_kwh <= soc_h <= capacity_kwh                   (battery bounds)
- 0 <= charge_h <= max_charge_kwh_per_hour
- 0 <= discharge_h <= max_discharge_kwh_per_hour
- soc_23 >= initial_energy_kwh                                  (end-of-day neutrality)

Directives add: solar factor caps, per-hour SOC floors, charge/discharge bans,
and per-hour grid ceilings.

If directives make the problem infeasible, the solver relaxes in a fixed order
(end-neutrality -> soft directive penalties -> directives dropped) so a valid
24-hour plan is always returned.

## Directive types

| Type | Fields | Effect |
|---|---|---|
| solar_reduction | hours, factor | usable solar = solar * factor |
| minimum_battery_reserve | hours, minimum_energy_kwh | SOC floor in those hours |
| no_charge_window | hours | charge = 0 |
| no_discharge_window | hours | discharge = 0 |
| max_grid_window | hours, max_grid_kwh | grid import ceiling |
| no_op | — | note carries no actionable constraint |

`factor` is the fraction of solar still available (0.7 = output reduced by 30%).

## LLM provider
- Provider: Anthropic
- Model: configurable via `LLM_MODEL` (default `claude-sonnet-4-5`)
- temperature = 0, JSON-only output, timeout 25s, one retry
- Any LLM failure degrades safely to `no_op` — the API never 500s on LLM errors

## Environment variables
| Name | Required | Description |
|---|---|---|
| ANTHROPIC_API_KEY | yes | Anthropic API key |
| LLM_MODEL | no | Model id (default `claude-sonnet-4-5`) |
| PORT | no | Server port (default 8000) |

## Run locally
```bash
git clone https://github.com/Ragib-Hasin-Muktadir/bup-cse-big-boss
cd bup-cse-big-boss
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export ANTHROPIC_API_KEY=your_key
uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## Run with Docker
```bash
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=your_key <username>/gridwise:latest
```

## Example

```bash
curl https://bup-cse-big-boss.onrender.com/health
```
```json
{"status": "ok"}
```

```bash
curl -X POST https://bup-cse-big-boss.onrender.com/optimize-energy \
  -H "Content-Type: application/json" \
  -d @tests/sample_request.json
```
```json
{
  "scenario_id": "test-001",
  "directive_interpretation": [
    {
      "note_index": 0,
      "applies": true,
      "directive_type": "solar_reduction",
      "structured_adjustment": {"hours": [13, 14, 15, 16], "factor": 0.6},
      "explanation": "Cloud cover reduces solar output to 60% between 1pm and 4pm."
    }
  ],
  "hourly_plan": [
    {"hour": 0, "grid_kwh": 80.0, "solar_used_kwh": 0.0,
     "battery_action": "charge", "battery_kwh": 40.0, "battery_energy_after_kwh": 120.0}
  ],
  "total_grid_kwh": 1820.5,
  "total_cost_bdt": 17204.25,
  "peak_grid_kwh": 130.0,
  "plan_summary": "Total grid import 1820.50 kWh costing 17204.25 BDT..."
}
```

## Error handling
- Malformed body / wrong hour count -> `400` with a structured `detail`
- LLM unavailable -> notes degrade to `no_op`, schedule still returned
- Infeasible directives -> staged relaxation, valid plan still returned

## Team
- Person A — optimizer, API, deployment, Docker
- Person B — LLM interpretation, guardrails, documentation