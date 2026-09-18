import json
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from app.schemas import OptimizeRequest
from app.optimizer import solve_schedule
from app.validator import validate_plan

payload = json.loads((pathlib.Path(__file__).parent / "sample_request.json").read_text())
req = OptimizeRequest(**payload)

t0 = time.perf_counter()
plan, mode = solve_schedule(req, [])   # directive ছাড়া baseline
elapsed = time.perf_counter() - t0

ok, issues = validate_plan(plan, req.hours, req.battery)
by_hour = {h.hour: h for h in req.hours}
cost = sum(p.grid_kwh * by_hour[p.hour].tariff_bdt_per_kwh for p in plan)

print(f"mode={mode}  solved in {elapsed:.3f}s  valid={ok}")
if issues:
    print("ISSUES:", issues)
print(f"total cost = {cost:.2f} BDT")
print(f"{'hr':>3} {'grid':>8} {'solar':>8} {'action':>10} {'kWh':>8} {'soc':>8}")
for p in plan:
    print(f"{p.hour:>3} {p.grid_kwh:>8.2f} {p.solar_used_kwh:>8.2f} "
          f"{p.battery_action:>10} {p.battery_kwh:>8.2f} {p.battery_energy_after_kwh:>8.2f}")