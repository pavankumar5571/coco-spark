"""Paid-call firewall. Designed by ChatGPT, implemented here.

ONE INVARIANT:
    No paid provider method may be invoked unless every deterministic precondition AND
    the full reserved cost have already passed.

The five gates (precheck, schema, camera compile, validate, preflight) are implementation
details. This tests the property they exist to guarantee: can any invalid deterministic
state cross the paid-call boundary?

Every mutation below must finish with paid_calls == 0.
Runs offline. No API key, no network, no cost.
"""
import copy, json, shutil, sys, tempfile
from pathlib import Path

import yaml

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

BIBLE = yaml.safe_load((ROOT / "bible.yaml").read_text())
# A fixture, deliberately NOT a production brief. This previously loaded episodes/E01.yaml,
# so the moment a real episode gained a CAMERA_VARIATION requirement the suite's positive
# control started failing — the tests were coupled to content that is supposed to change.
EP = {"id": "T01", "mode": "BEDTIME_STORY", "title": "fixture",
      "location": "cottage_night", "locations": ["cottage_night"],
      "cast": ["coco", "nana"], "shots": 2,
      "idea": "Fixture episode for the planning firewall. Never generated."}


class FakeProvider:
    """Counts paid invocations. Any call at all is a firewall breach."""
    def __init__(self): self.calls = []
    def image(self, *a, **k): self.calls.append("image"); return b"fake"
    def video(self, *a, **k): self.calls.append("video"); return b"fake"


def good_shot(sid, **kw):
    s = {
        "id": sid, "cast": ["coco", "nana"], "coverage_role": "SUBJECT",
        "frame": "f", "motion": "m", "camera": "static",
        "boundary": {"type": "CONTINUOUS"}, "events": [],
        "start_state": {
            "location_id": "cottage_night", "population": ["coco", "nana"],
            "characters": {
                "coco": {"awareness": "AWAKE", "posture": "SITTING_UP", "zone": "BED"},
                "nana": {"awareness": "AWAKE", "posture": "PERCHED", "zone": "CHAIR"}},
            "props": {},
            "visual": {"camera_setup_id": "A", "shot_size": "MEDIUM",
                       "camera_angle": "EYE_LEVEL"}},
    }
    s["end_state"] = copy.deepcopy(s["start_state"])
    s.update(kw)
    return s


def mutations():
    """Each returns (name, shots) where shots MUST be rejected."""
    m = []

    s = good_shot("s01"); s["start_state"]["population"] = ["coco"]
    m.append(("population disagrees with characters", [s]))

    s = good_shot("s01"); s["end_state"]["characters"]["nana"]["zone"] = "WINDOW"
    m.append(("zone change, no MOVE event", [s]))

    s = good_shot("s01"); s["end_state"]["characters"]["nana"]["zone"] = "WINDOW"
    s["events"] = [{"type": "MOVE", "entity": "nana", "from_zone": "BED", "to_zone": "DOOR"}]
    m.append(("MOVE event with wrong from/to", [s]))

    s = good_shot("s01"); s["end_state"]["characters"]["coco"]["awareness"] = "ASLEEP"
    m.append(("material change, no STATE_CHANGE", [s]))

    s = good_shot("s01"); s["end_state"]["props"] = {"apple": "coco"}
    m.append(("prop set changes inside a shot", [s]))

    s = good_shot("s01"); del s["start_state"]["visual"]["camera_setup_id"]
    m.append(("incomplete visual state", [s]))

    s = good_shot("s01"); del s["start_state"]["location_id"]
    m.append(("no location_id", [s]))

    s = good_shot("s01"); s["start_state"]["characters"]["coco"]["awareness"] = "kind of sleepy"
    m.append(("value outside the closed vocabulary", [s]))

    s = good_shot("s01"); s["cast"] = ["coco", "stranger"]
    m.append(("unknown entity in cast", [s]))

    a, b = good_shot("s01"), good_shot("s02")
    a["end_state"]["characters"]["coco"]["awareness"] = "DROWSY"
    a["events"] = [{"type": "STATE_CHANGE", "entity": "coco", "field": "awareness",
                    "from": "AWAKE", "to": "DROWSY"}]
    b["start_state"]["characters"]["coco"]["awareness"] = "ASLEEP"
    m.append(("material jump across a CONTINUOUS cut", [a, b]))

    a, b = good_shot("s01"), good_shot("s02")
    b["boundary"] = {"type": "TIME_JUMP", "reason": "later"}
    m.append(("boundary type forbidden by the mode", [a, b]))

    a, b = good_shot("s01"), good_shot("s02")
    b["start_state"]["population"] = ["coco", "nana", "pip"]
    b["start_state"]["characters"]["pip"] = {"awareness": "AWAKE", "posture": "STANDING",
                                             "zone": "RUG"}
    b["cast"] = ["coco", "nana", "pip"]
    m.append(("character materialises across the cut", [a, b]))

    return m


def main():
    from validate import validate
    import camera
    provider = FakeProvider()
    failures, checked = [], 0

    for name, shots in mutations():
        checked += 1
        issues = validate(shots, EP, BIBLE, {})
        errs = [i for i in issues if i.severity == "ERROR"]
        if not errs:
            failures.append(f"NOT REJECTED: {name}")
            provider.image()          # simulate what the pipeline would have done
        else:
            print(f"  blocked  {name:46s} {errs[0].code}")

    # unsatisfiable requirement must be caught before planning
    checked += 1
    try:
        camera.precheck({"mode": "SONG", "shots": 1, "cast": ["coco"],
                         "requirements": [{"id": "cv", "type": "CAMERA_VARIATION",
                                           "strength": "MUST",
                                           "params": {"required_sizes": ["WIDE", "CLOSE"]}}]},
                        BIBLE)
        failures.append("NOT REJECTED: unsatisfiable coverage requirement")
        provider.image()
    except camera.Unsatisfiable:
        print(f"  blocked  {'unsatisfiable coverage requirement':46s} UNSATISFIABLE_REQUIREMENT")

    # the control: a valid plan must NOT be rejected
    checked += 1
    a, b = good_shot("s01"), good_shot("s02")
    if [i for i in validate([a, b], EP, BIBLE, {}) if i.severity == "ERROR"]:
        failures.append("FALSE POSITIVE: a valid plan was rejected")
    else:
        print(f"  passed   {'valid plan (control)':46s} clean")

    # ── composition vs physical setup ────────────────────────────────────────
    import camera as _cam
    from make import reference_policy as _pol

    def _s(sid, role, ids, size_role=None):
        import copy
        s = {"id": sid, "cast": ["coco", "nana"], "coverage_role": role,
             "focus": {"type": "CHARACTER", "ids": ids}, "frame": "x", "motion": "m",
             "boundary": {"type": "CONTINUOUS"}, "events": [],
             "start_state": {"location_id": "cottage_night",
                "population": ["coco", "nana"],
                "characters": {
                    "coco": {"awareness": "AWAKE", "posture": "SITTING_UP", "zone": "BED"},
                    "nana": {"awareness": "AWAKE", "posture": "PERCHED", "zone": "CHAIR"}},
                "props": {}}}
        s["end_state"] = copy.deepcopy(s["start_state"])
        return s

    # identical size and angle, DIFFERENT subject -> must not inherit pixels
    ep2 = {"mode": "BEDTIME_STORY", "shots": 2, "cast": ["coco", "nana"],
           "requirements": []}
    pair = _cam.assign([_s("s01", "REACTION", ["coco"]),
                        _s("s02", "REACTION", ["nana"])], ep2, BIBLE)
    v1, v2 = pair[0]["start_state"]["visual"], pair[1]["start_state"]["visual"]
    same_frame = (v1["shot_size"] == v2["shot_size"]
                  and v1["camera_setup_id"] == v2["camera_setup_id"])
    pol = _pol(pair[0], pair[1], BIBLE)[0]
    checked += 1
    if same_frame and pol == "PREDECESSOR_PIXELS":
        failures.append("NOT REJECTED: same size/setup, different subject -> inheritance")
        provider.image()
    else:
        print(f"  blocked  {'CLOSE on coco -> CLOSE on nana (same setup)':46s} "
              f"{pol}")

    # the compiled framing must not contradict the assigned camera
    checked += 1
    compiled = pair[1].get("frame_compiled", "")
    if "identical" in compiled.lower() or not compiled:
        failures.append("NOT REJECTED: compiled frame text missing or self-contradictory")
    else:
        print(f"  passed   {'compiled framing matches assigned camera':46s} "
              f"{compiled[:38]}...")

    print(f"\n  {checked} cases | paid calls made: {len(provider.calls)}")
    if failures or provider.calls:
        for f in failures:
            print(f"  ✗ {f}")
        sys.exit(1)
    print("  FIREWALL HELD — no deterministic defect reached a paid call")


if __name__ == "__main__":
    main()
