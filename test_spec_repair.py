"""G05 adversarial controls; no provider/network can exist behind FakeProvider."""
from copy import deepcopy
from spec_repair import repair_spec
import gemini_spec_canary as live_canary

assert (live_canary.BASE_RESERVATION_INR * live_canary.SAFETY_MARGIN *
        live_canary.MAX_CALLS) <= live_canary.APPROVED_MAX_INR

SCHEMA = {"type": "object", "properties": {
    "opportunity_id": {"type": "string"},
    "mode": {"type": "string", "enum": ["SONG", "STORY"]},
    "duration": {"type": "integer"},
    "title": {"type": "string"}},
    "required": ["opportunity_id", "mode", "duration", "title"]}

def semantic(doc):
    return ([] if doc.get("duration", 0) > 0 else
            [{"code": "NON_POSITIVE", "path": "/duration", "message": "must be > 0"}])

VALID = {"opportunity_id": "opp-1", "mode": "SONG", "duration": 60, "title": "Count"}

class FakeProvider:
    def __init__(self, patches): self.patches, self.calls = list(patches), 0
    def repair(self, document, errors, allowed_paths):
        self.calls += 1
        assert errors and allowed_paths
        return deepcopy(self.patches[min(self.calls - 1, len(self.patches) - 1)])

# Valid input is unchanged and never calls a provider.
p = FakeProvider([[{"op": "replace", "path": "/title", "value": "Wrong"}]])
r = repair_spec(VALID, schema=SCHEMA, semantic_validator=semantic, provider=p)
assert r["status"] == "VALID_ORIGINAL" and r["document"] == VALID and p.calls == 0

# Mechanical fences, approved aliases and safe defaults repair without a model.
r = repair_spec('```json\n{"opportunity_id":"opp-1","mode":"song","duration":60}\n```',
    schema=SCHEMA, semantic_validator=semantic,
    aliases={"/mode": {"song": "SONG"}}, defaults={"/title": "Untitled"})
assert r["status"] == "VALID_DETERMINISTIC" and r["document"]["mode"] == "SONG"

# Exact rejected field may be repaired, while immutable evidence never changes.
p = FakeProvider([[{"op": "replace", "path": "/duration", "value": 30}]])
bad = {**VALID, "duration": 0}
r = repair_spec(bad, schema=SCHEMA, semantic_validator=semantic, provider=p,
                immutable_paths=("/opportunity_id",), max_model_attempts=1)
assert r["status"] == "VALID_MODEL_REPAIR" and r["document"]["opportunity_id"] == "opp-1"

# A patch to a valid or immutable field is rejected even when another field is invalid.
p = FakeProvider([[{"op": "replace", "path": "/opportunity_id", "value": "forged"}]])
r = repair_spec(bad, schema=SCHEMA, semantic_validator=semantic, provider=p,
                immutable_paths=("/opportunity_id",), max_model_attempts=1)
assert r["status"] == "UNRECOVERABLE" and r["document"] is None
assert r["manifest"][-1]["errors"][0]["code"] == "PATCH_FORBIDDEN"

# Retry count is a hard ceiling; valid fallback is revalidated and recorded.
p = FakeProvider([[{"op": "remove", "path": "/duration"}]])
r = repair_spec(bad, schema=SCHEMA, semantic_validator=semantic, provider=p,
                max_model_attempts=2, fallback_factory=lambda _d, _e: deepcopy(VALID))
assert p.calls == 2 and r["status"] == "VALID_FALLBACK"
assert [x["stage"] for x in r["manifest"]].count("MODEL_REPAIR") == 2

# Invalid fallback is never trusted by construction.
r = repair_spec(bad, schema=SCHEMA, semantic_validator=semantic,
                fallback_factory=lambda _d, _e: {**VALID, "duration": 0})
assert r["status"] == "UNRECOVERABLE" and r["manifest"][-1]["errors"]

# Malformed JSON fails explicitly; it cannot reach model repair or fallback silently.
r = repair_spec('{bad', schema=SCHEMA, semantic_validator=semantic, provider=p,
                fallback_factory=lambda _d, _e: deepcopy(VALID))
assert r["status"] == "UNRECOVERABLE" and r["manifest"][0]["stage"] == "PARSE"

# Safe deterministic refusal is visible to operators rather than silently ignored.
r = repair_spec(bad, schema=SCHEMA, semantic_validator=semantic,
                aliases={"/opportunity_id": {"opp-1": "forged"}},
                immutable_paths=("/opportunity_id",))
det = next(x for x in r["manifest"] if x["stage"] == "DETERMINISTIC")
assert det["refusals"] == [{"code": "ALIAS_REFUSED_IMMUTABLE",
                            "path": "/opportunity_id"}]

print("G05 spec repair controls passed: 8 adversarial routes")
