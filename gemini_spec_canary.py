"""Three-call live Gemini canary for G05. Hard limit: three calls, Rs 9 approved."""
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess

import config as C
import make
from spec_repair import repair_spec


SPEC_SCHEMA = {"type": "object", "properties": {
    "opportunity_id": {"type": "string"},
    "mode": {"type": "string", "enum": ["SONG", "STORY"]},
    "duration": {"type": "integer"},
    "title": {"type": "string"}},
    "required": ["opportunity_id", "mode", "duration", "title"]}

PATCH_SCHEMA = {"type": "array", "items": {"type": "object", "properties": {
    "op": {"type": "string", "enum": ["add", "replace"]},
    "path": {"type": "string"}, "value": {}},
    "required": ["op", "path", "value"]}}

APPROVED_MAX_INR = 9.0
MAX_CALLS = 3
SAFETY_MARGIN = getattr(C, "SAFETY_MARGIN", 1.0)
BASE_RESERVATION_INR = APPROVED_MAX_INR / (MAX_CALLS * SAFETY_MARGIN)


def semantic(document):
    return ([] if document.get("duration", 0) > 0 else
            [{"code": "NON_POSITIVE", "path": "/duration", "message": "must be > 0"}])


class LiveGemini:
    def __init__(self):
        self.client = make.client()
        self.calls = 0
        self.actual_inr = 0.0
        self.authorised_reservations_inr = 0.0
        self.records = []

    def _call(self, *, scenario, prompt, response_schema):
        if self.calls >= MAX_CALLS:
            raise RuntimeError("G05 live call ceiling reached")
        next_reservation = BASE_RESERVATION_INR * SAFETY_MARGIN
        if self.authorised_reservations_inr + next_reservation > APPROVED_MAX_INR:
            raise RuntimeError("G05 cumulative reservation ceiling reached before provider call")
        reservation = make.reserve("llm", f"g05-live:{scenario}", BASE_RESERVATION_INR)
        self.authorised_reservations_inr += next_reservation
        try:
            _, types, _ = make._sdk()
            response = self.client.models.generate_content(
                model=C.PLANNER_MODEL, contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    max_output_tokens=512,
                    temperature=0))
            usage = getattr(response, "usage_metadata", None)
            actual = (((usage.prompt_token_count / 1e6) * 0.10 +
                       (usage.candidates_token_count / 1e6) * 0.40) * 88) if usage else 1.0
            if self.actual_inr + actual > APPROVED_MAX_INR:
                make.settle(reservation, actual)
                raise RuntimeError("G05 approved Rs 9 cumulative ceiling exceeded")
            make.settle(reservation, actual)
        except BaseException:
            # Do not release a reservation already settled by the ceiling branch.
            ledger = make.ledger()
            if ledger["ops"][reservation]["state"] == "RESERVED":
                make.settle(reservation, None)
            raise
        self.calls += 1
        self.actual_inr += actual
        payload = json.loads(response.text)
        self.records.append({"scenario": scenario, "actual_inr": actual,
                             "prompt_tokens": getattr(usage, "prompt_token_count", None),
                             "output_tokens": getattr(usage, "candidates_token_count", None)})
        return payload

    def generate(self):
        return self._call(
            scenario="generation", response_schema=SPEC_SCHEMA,
            prompt=("Return one internal episode specification canary as JSON. Preserve "
                    "opportunity_id exactly as yt-live-g03-unproven. mode SONG, duration "
                    "60 seconds, and a concise generic counting-song title. Do not claim "
                    "the opportunity is proven; this tests structure only."))

    def repair(self, document, errors, allowed_paths):
        scenario = "shape-repair" if any(e["code"] == "REQUIRED" for e in errors) \
            else "semantic-repair"
        return self._call(
            scenario=scenario, response_schema=PATCH_SCHEMA,
            prompt=("Return only a JSON Patch array using add or replace. Fix exactly the "
                    f"listed errors and only these allowed paths: {json.dumps(allowed_paths)}. "
                    "Do not touch opportunity_id or any valid field.\nErrors:\n" +
                    json.dumps(errors) + "\nDocument:\n" + json.dumps(document)))


def main():
    live = LiveGemini()
    generated = live.generate()
    generated_result = repair_spec(
        generated, schema=SPEC_SCHEMA, semantic_validator=semantic,
        immutable_paths=("/opportunity_id",), max_model_attempts=0)

    missing_title = {"opportunity_id": "yt-live-g03-unproven",
                     "mode": "SONG", "duration": 60}
    shape_result = repair_spec(
        missing_title, schema=SPEC_SCHEMA, semantic_validator=semantic, provider=live,
        immutable_paths=("/opportunity_id",), max_model_attempts=1)

    bad_duration = {"opportunity_id": "yt-live-g03-unproven", "mode": "SONG",
                    "duration": 0, "title": "Counting Canary"}
    semantic_result = repair_spec(
        bad_duration, schema=SPEC_SCHEMA, semantic_validator=semantic, provider=live,
        immutable_paths=("/opportunity_id",), max_model_attempts=1)

    results = [generated_result, shape_result, semantic_result]
    accepted_hashes = [hashlib.sha256(json.dumps(
        result["document"], sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        if result["document"] is not None else None for result in results]
    passed = (live.calls == 3 and live.actual_inr <= APPROVED_MAX_INR and
              all(result["status"].startswith("VALID") for result in results) and
              all(result["document"]["opportunity_id"] == "yt-live-g03-unproven"
                  for result in results))
    report = {
        "kind": "GEMINI_SPEC_REPAIR_LIVE_CANARY_V1",
        "at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], text=True).strip(),
        "model": C.PLANNER_MODEL, "approved_max_inr": APPROVED_MAX_INR,
        "authorised_reservations_inr": live.authorised_reservations_inr,
        "base_reservation_per_call_inr": BASE_RESERVATION_INR,
        "calls": live.calls, "actual_inr": round(live.actual_inr, 6),
        "provider_usage": live.records,
        "statuses": [result["status"] for result in results],
        "immutable_opportunity_ids": [result["document"]["opportunity_id"]
                                      if result["document"] else None for result in results],
        "accepted_document_sha256": accepted_hashes,
        "repair_manifests": [result["manifest"] for result in results],
        "passed": passed,
    }
    destination = Path("evidence/gemini-spec-repair-live-canary.json")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
