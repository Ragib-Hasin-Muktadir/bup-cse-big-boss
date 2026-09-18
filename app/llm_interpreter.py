from __future__ import annotations

import json
import os
import re
from typing import List

from anthropic import Anthropic

from app.schemas import DirectiveInterpretation, StructuredAdjustment

MODEL = os.getenv("LLM_MODEL", "claude-sonnet-4-5")
_client = Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"), timeout=25.0, max_retries=1)

VALID_TYPES = {
    "solar_reduction",
    "minimum_battery_reserve",
    "no_charge_window",
    "no_discharge_window",
    "max_grid_window",
    "no_op",
}

SYSTEM_PROMPT = """You convert campus-energy operator notes into structured directives.

You will receive a numbered list of notes. Return ONE JSON array, one object per note,
in the same order. Output JSON only — no prose, no markdown fences.

Each object:
{
  "note_index": <int, 0-based, matches input>,
  "applies": <bool>,
  "directive_type": "solar_reduction" | "minimum_battery_reserve" | "no_charge_window"
                    | "no_discharge_window" | "max_grid_window" | "no_op",
  "structured_adjustment": { ... } or null,
  "explanation": "<one short sentence, in English>"
}

structured_adjustment shape by type:
- solar_reduction        -> {"hours": [int...], "factor": float}
- minimum_battery_reserve-> {"hours": [int...], "minimum_energy_kwh": float}
- no_charge_window       -> {"hours": [int...]}
- no_discharge_window    -> {"hours": [int...]}
- max_grid_window        -> {"hours": [int...], "max_grid_kwh": float}
- no_op                  -> null

Rules:
- Hours are integers 0-23. Expand ranges inclusively: "from 13:00 to 16:00" -> [13,14,15,16].
  "1pm to 4pm" -> [13,14,15,16]. "morning" -> [6,7,8,9,10,11]. "afternoon" -> [12..17].
  "evening" -> [18..21]. "night"/"overnight" -> [22,23,0,1,2,3,4,5]. "peak hours" -> [18,19,20,21].
- factor is the FRACTION OF SOLAR STILL AVAILABLE. "reduce solar by 30%" -> factor 0.7.
  "solar at 40% capacity" -> factor 0.4. "panels offline" -> factor 0.0.
- If a note gives no actionable constraint (chit-chat, observation, a note about
  something already true), use "no_op", applies=false, structured_adjustment=null.
- Never invent numbers that are not implied by the note.
- Output exactly one object per input note."""


def _extract_json(text: str):
    text = text.strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\[.*\]", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _fallback(i: int, reason: str) -> DirectiveInterpretation:
    return DirectiveInterpretation(
        note_index=i,
        applies=False,
        directive_type="no_op",
        structured_adjustment=None,
        explanation=f"Could not interpret note reliably ({reason}); treated as no-op.",
    )


def _to_model(obj: dict, i: int) -> DirectiveInterpretation:
    dtype = obj.get("directive_type")
    if dtype not in VALID_TYPES:
        return _fallback(i, "unknown directive type")

    sa_raw = obj.get("structured_adjustment")
    sa = None
    if isinstance(sa_raw, dict):
        sa = StructuredAdjustment(
            hours=sa_raw.get("hours"),
            factor=sa_raw.get("factor"),
            minimum_energy_kwh=sa_raw.get("minimum_energy_kwh"),
            max_grid_kwh=sa_raw.get("max_grid_kwh"),
        )

    applies = bool(obj.get("applies", dtype != "no_op"))
    if dtype == "no_op":
        applies, sa = False, None

    return DirectiveInterpretation(
        note_index=i,
        applies=applies,
        directive_type=dtype,
        structured_adjustment=sa,
        explanation=str(obj.get("explanation") or "").strip()[:300] or "Interpreted from operator note.",
    )


def interpret_notes(notes: List[str]) -> List[DirectiveInterpretation]:
    """সব note এক কলে — latency কম রাখার জন্য।"""
    if not notes:
        return []

    numbered = "\n".join(f"{i}. {n}" for i, n in enumerate(notes))
    user_msg = f"Operator notes:\n{numbered}\n\nReturn the JSON array now."

    try:
        resp = _client.messages.create(
            model=MODEL,
            max_tokens=1200,
            temperature=0,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_msg}],
        )
        text = "".join(block.text for block in resp.content if block.type == "text")
    except Exception as e:  # network / auth / rate limit
        return [_fallback(i, f"LLM error: {type(e).__name__}") for i in range(len(notes))]

    data = _extract_json(text)
    if not isinstance(data, list):
        return [_fallback(i, "non-JSON response") for i in range(len(notes))]

    by_index = {}
    for obj in data:
        if isinstance(obj, dict):
            try:
                idx = int(obj.get("note_index"))
            except (TypeError, ValueError):
                continue
            by_index[idx] = obj

    out = []
    for i in range(len(notes)):
        obj = by_index.get(i)
        out.append(_to_model(obj, i) if obj else _fallback(i, "missing in LLM output"))
    return out