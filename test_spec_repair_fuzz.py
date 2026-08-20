"""Random documents, random patches, invariants that must hold anyway.

The adversarial suite tests the routes I imagined, and it found four real defects — which
is the reason I do not trust it further than I can see. Every attack in it was authored by
someone who already knew where to look, and a model in production will not be that
considerate.

So this generates documents and patch lists at random and asserts the properties that must
hold for ALL of them, not for the ones I thought of:

    AN IMMUTABLE PATH NEVER CHANGES, whatever is thrown at it
    A VALID VERDICT'S DOCUMENT ACTUALLY VALIDATES
    AN UNRECOVERABLE VERDICT CARRIES NO DOCUMENT
    THE CALLER'S INPUT IS NEVER MUTATED
    EVERY RUN PRODUCES A HASHED MANIFEST
    A PROVIDER FAILURE DOES NOT DISCARD THE MANIFEST

Seeded, so a failure is reproducible: the seed is printed and can be replayed.
"""
from __future__ import annotations

import json
import random
import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spec_repair

SCHEMA = {"type": "object", "properties": {
    "opportunity_id": {"type": "string"},
    "mode": {"type": "string", "enum": ["EDUCATIONAL", "SONG", "STORY"]},
    "cast": {"type": "array"},
    "duration": {"type": "number"},
    "title": {"type": "string"},
}, "required": ["opportunity_id", "mode", "cast", "duration", "title"]}

IMMUTABLE = ("/opportunity_id", "/cast")
PATHS = ["/opportunity_id", "/mode", "/cast", "/duration", "/title", "/unknown", "/", ""]
VALUES = [None, 0, -1, 1.5, "", "SONG", "EDUCATIONAL", [], ["x"], {}, {"a": 1}, True,
          "opp-forged", 10 ** 12, " ", "../../etc/passwd"]
OPS = ["add", "replace", "remove", "copy", "move", "test", None, 42]


def _document(rng):
    doc = {"opportunity_id": f"opp-{rng.randint(0, 9)}",
           "mode": rng.choice(["EDUCATIONAL", "SONG", "STORY", "NONSENSE", None]),
           "cast": rng.choice([["unit-7"], [], ["a", "b"], None, "not-a-list"]),
           "duration": rng.choice([45, 0, -3, 1.5, None, "60"]),
           "title": rng.choice(["Counting Bolts", "", None, 7])}
    for key in list(doc):
        if rng.random() < 0.25:
            del doc[key]
    return doc


def _patches(rng):
    return [{"op": rng.choice(OPS), "path": rng.choice(PATHS),
             "value": rng.choice(VALUES)} for _ in range(rng.randint(0, 4))]


class RandomProvider:
    def __init__(self, rng):
        self.rng = rng

    def repair(self, document, errors, allowed):
        roll = self.rng.random()
        if roll < 0.1:
            raise RuntimeError("provider exploded")
        if roll < 0.2:
            return "not a list at all"
        if roll < 0.3:
            return None
        return _patches(self.rng)


def _ok(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:58s}{'' if cond else '  <-- ' + detail}")
    return bool(cond)


def fuzz(runs=400, seed=20260820):
    rng = random.Random(seed)
    findings = {}

    def note(key, detail):
        findings.setdefault(key, detail)

    for _ in range(runs):
        document = _document(rng)
        sent = deepcopy(document)
        immutable_before = {p: deepcopy(document.get(p.strip("/"))) for p in IMMUTABLE}
        try:
            out = spec_repair.repair_spec(
                document, schema=SCHEMA, semantic_validator=lambda d: [],
                provider=RandomProvider(rng), immutable_paths=IMMUTABLE,
                aliases={"/mode": {"NONSENSE": "STORY"}}, defaults={"/title": "Filled"},
                max_model_attempts=rng.randint(0, 3),
                fallback_factory=None if rng.random() < 0.5 else
                (lambda d, e: {"opportunity_id": "fallback", "mode": "STORY",
                               "cast": [], "duration": 30, "title": "Approved"}))
        except Exception as exc:
            note("a provider failure does not discard the manifest",
                 f"{type(exc).__name__}: {exc} — everything already recorded "
                 f"about this run is lost with it")
            continue

        if document != sent:
            note("the caller's input is never mutated", f"{sent} became {document}")

        result = out.get("document")
        if out["status"] == "UNRECOVERABLE" and result is not None:
            note("an unrecoverable verdict carries no document", str(out)[:120])
        if out["status"].startswith("VALID"):
            if result is None:
                note("a valid verdict carries a document", str(out)[:120])
            elif spec_repair.validate_document(result, SCHEMA, lambda d: []):
                note("a valid verdict's document actually validates", str(result)[:120])
            elif out["status"] != "VALID_FALLBACK":
                # The fallback is a different document by design; every other accepted
                # document must still carry the immutable values it arrived with.
                for path, before in immutable_before.items():
                    key = path.strip("/")
                    if before is not None and result.get(key) != before:
                        note("an immutable path never changes",
                             f"{path}: {before!r} -> {result.get(key)!r}")
        if not out.get("manifest"):
            note("every run produces a manifest", str(out)[:120])
        elif any("sha256" not in stage for stage in out["manifest"]
                 if stage["stage"] != "PARSE"):
            note("every non-parse stage is hashed", json.dumps(out["manifest"])[:120])

    return findings


def main():
    seed = int(sys.argv[1]) if len(sys.argv) > 1 else 20260820
    runs = 400
    print(f"  G05 FUZZ — {runs} random documents and patch lists, seed {seed}")
    findings = fuzz(runs, seed)
    properties = ["a provider failure does not discard the manifest",
                  "the caller's input is never mutated",
                  "an unrecoverable verdict carries no document",
                  "a valid verdict carries a document",
                  "a valid verdict's document actually validates",
                  "an immutable path never changes",
                  "every run produces a manifest",
                  "every non-parse stage is hashed"]
    results = [_ok(p, p not in findings, findings.get(p, "")) for p in properties]
    failed = results.count(False)
    print(f"  {len(results) - failed}/{len(results)} held over {runs} random runs, "
          f"{failed} open")
    if failed:
        print(f"  replay with: python {Path(__file__).name} {seed}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
