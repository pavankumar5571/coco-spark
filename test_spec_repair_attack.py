"""Attacks on the bounded repair engine, written against the ways a writer gets its way.

The engine exists so that a language model may fix what is BROKEN and may not touch what
is INTACT. Every case here is one attempt to cross that line, because a model that can
rewrite an evidence id or an approved cast entry turns a validated pipeline into a
validated-looking one.

    A REJECTED PATCH MUST NOT WIDEN WHAT IS ALLOWED
    A REJECTED BATCH MUST NOT LEAVE ITS ACCEPTED HALF BEHIND
    IMMUTABLE MEANS IMMUTABLE ON EVERY PATH, NOT ONLY THE MODEL'S
    THE FALLBACK MUST NOT INHERIT WHAT THE MODEL WROTE
    THE CALLER'S DOCUMENT IS NOT OURS TO EDIT

No network, and no provider that is not a fake. Generic throughout: the fixtures use a
mode of EDUCATIONAL and a robot, so nothing here can pass by knowing about this channel.
"""
from __future__ import annotations

import sys
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import spec_repair

SCHEMA = {"type": "object", "properties": {
    "opportunity_id": {"type": "string"},
    "mode": {"type": "string", "enum": ["EDUCATIONAL", "SONG"]},
    "cast": {"type": "array"},
    "duration": {"type": "number"},
    "title": {"type": "string"},
}, "required": ["opportunity_id", "mode", "cast", "duration", "title"]}

IMMUTABLE = ("/opportunity_id", "/cast")


def valid():
    return {"opportunity_id": "opp-robot-1", "mode": "EDUCATIONAL",
            "cast": ["unit-7"], "duration": 45, "title": "Counting Bolts"}


def _ok(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name:58s}{'' if cond else '  <-- ' + detail}")
    return bool(cond)


class Provider:
    """Returns a scripted patch list per attempt, and records what it was allowed."""

    def __init__(self, *rounds):
        self.rounds = list(rounds)
        self.allowed_seen = []
        self.calls = 0

    def repair(self, document, errors, allowed):
        self.calls += 1
        self.allowed_seen.append(list(allowed))
        return self.rounds[min(self.calls - 1, len(self.rounds) - 1)]


def a_forbidden_patch_does_not_widen_the_allowed_set():
    """The laundering case.

    When a patch is rejected the engine replaces its error list with the REJECTION list,
    and the next attempt derives its allowed paths from those errors. So a refusal names
    the forbidden path as an error path, and asking twice makes it legal. A model does not
    have to be adversarial to do this. A model that is merely persistent does it by
    accident.

    Asserted on the ALLOWED SET the provider is handed, not on the returned document. The
    first version of this case checked the document, which is None on an unrecoverable
    verdict, so it passed while the laundering was happening in front of it.
    """
    broken = valid()
    broken.pop("title")
    provider = Provider([{"op": "replace", "path": "/duration", "value": 9}],
                        [{"op": "replace", "path": "/duration", "value": 9}])
    spec_repair.repair_spec(broken, schema=SCHEMA, provider=provider,
                            immutable_paths=IMMUTABLE, max_model_attempts=2)
    later = provider.allowed_seen[1] if len(provider.allowed_seen) > 1 else []
    return _ok("a refused path is not allowed on the next attempt",
               "/duration" not in later,
               f"attempt 2 was allowed {later}, which is what attempt 1 was refused for")


def a_rejected_batch_leaves_nothing_behind():
    """Half a patch list is not a patch list.

    If the first patch applies and the second is refused, the document carries an edit
    from a batch that was rejected as a whole. The verdict returns no document, so this is
    invisible from the outside - until the fallback factory is handed that same mutated
    document, which is how it escapes.

    The first version of this case used a replace on a missing key, which the engine
    refuses for an unrelated reason, so it passed without ever testing atomicity. This one
    uses add, so the first patch genuinely applies.
    """
    broken = valid()
    broken.pop("title")
    provider = Provider([{"op": "add", "path": "/title", "value": "Patched"},
                         {"op": "replace", "path": "/opportunity_id", "value": "opp-forged"}])
    seen = {}

    def fallback_factory(document, errors):
        seen["title"] = document.get("title")
        return valid()

    spec_repair.repair_spec(broken, schema=SCHEMA, provider=provider,
                            immutable_paths=IMMUTABLE, max_model_attempts=1,
                            fallback_factory=fallback_factory)
    return _ok("a partly refused batch leaves no accepted half behind",
               seen.get("title") != "Patched",
               f"the fallback was handed title={seen.get('title')!r} from a rejected batch")


def an_immutable_path_is_immutable_deterministically_too():
    """Immutability is enforced in the model stage and nowhere else.

    Deterministic repair is OURS, which is exactly why it is dangerous: an alias table and
    a defaults table are configuration, and configuration is edited by whoever is in a
    hurry. If the immutable list does not bind the deterministic stage, the guarantee
    reads as: the model may not rewrite evidence identity, but a config line may.
    """
    broken = valid()
    broken.pop("title")
    out = spec_repair.repair_spec(
        broken, schema=SCHEMA,
        aliases={"/opportunity_id": {"opp-robot-1": "opp-rewritten"}},
        defaults={"/title": "Filled"}, immutable_paths=IMMUTABLE)
    doc = out["document"] or {}
    return _ok("deterministic repair cannot rewrite an immutable path",
               doc.get("opportunity_id") == "opp-robot-1",
               f"opportunity_id became {doc.get('opportunity_id')}")


def the_fallback_does_not_inherit_the_models_edits():
    """The fallback exists for when the model FAILED.

    It is handed the document the model has already written into, so a factory that starts
    from what it was given carries the failed attempt's content into the approved-template
    path. It then revalidates cleanly, which is precisely what makes it invisible.
    """
    broken = valid()
    broken.pop("title")
    # add, not replace: the key is missing, and a replace would be refused for an
    # unrelated reason and pass this case without ever exercising it.
    provider = Provider([{"op": "add", "path": "/title", "value": "MODEL WROTE THIS"}])
    seen = {}

    def fallback_factory(document, errors):
        seen["title"] = document.get("title")
        base = valid()
        base["title"] = document.get("title") or "Approved Template"
        return base

    spec_repair.repair_spec(
        broken, schema=SCHEMA, provider=provider, immutable_paths=IMMUTABLE,
        max_model_attempts=1, fallback_factory=fallback_factory,
        semantic_validator=lambda d: [{"code": "SEMANTIC", "path": "/title",
                                       "message": "always fails"}])
    return _ok("the fallback is not handed the model's edits",
               seen.get("title") != "MODEL WROTE THIS",
               f"fallback saw title={seen.get('title')!r}")


def the_callers_document_is_never_mutated():
    """A caller that passes a dict and then logs it must log what it sent.

    If the engine edits in place, the record of what the model was GIVEN becomes the
    record of what the model PRODUCED, and no later audit can tell them apart.
    """
    broken = valid()
    broken.pop("title")
    before = deepcopy(broken)
    spec_repair.repair_spec(broken, schema=SCHEMA, defaults={"/title": "Filled"})
    return _ok("the caller's own dict is untouched", broken == before,
               f"caller dict changed to {broken}")


def repairing_a_valid_document_changes_nothing():
    """Idempotence. A pipeline that reruns a stage must not drift, or two runs of one
    input produce two manifests and the hash chain stops meaning anything."""
    out = spec_repair.repair_spec(valid(), schema=SCHEMA, defaults={"/title": "Filled"},
                                  aliases={"/mode": {"EDUCATIONAL": "SONG"}})
    return _ok("a valid document is returned unchanged",
               out["document"] == valid() and out["status"].startswith("VALID"),
               f"status={out['status']} doc={out['document']}")


def an_unrecoverable_verdict_carries_no_document():
    """A caller that checks the document instead of the status must not find a usable
    object on a failure. Refusals have been quietly consumed in this project before."""
    out = spec_repair.repair_spec("{not json", schema=SCHEMA)
    return _ok("an unrecoverable verdict has no document",
               out["status"] == "UNRECOVERABLE" and out["document"] is None,
               str(out)[:80])


def every_stage_is_hashed_in_order():
    """The manifest is the only evidence of what happened between two validations. A
    stage that is missing or unhashed proves nothing about itself."""
    broken = valid()
    broken.pop("title")
    out = spec_repair.repair_spec(broken, schema=SCHEMA, defaults={"/title": "Filled"})
    stages = [m["stage"] for m in out["manifest"]]
    hashed = all("sha256" in m for m in out["manifest"] if m["stage"] != "PARSE")
    return _ok("every non-parse stage carries a hash",
               hashed and stages[0] == "INPUT", f"stages={stages} hashed={hashed}")


def main():
    print("  G05 REPAIR ATTACK - what stops a writer from getting its way")
    results = []
    for fn in (a_forbidden_patch_does_not_widen_the_allowed_set,
               a_rejected_batch_leaves_nothing_behind,
               an_immutable_path_is_immutable_deterministically_too,
               the_fallback_does_not_inherit_the_models_edits,
               the_callers_document_is_never_mutated,
               repairing_a_valid_document_changes_nothing,
               an_unrecoverable_verdict_carries_no_document,
               every_stage_is_hashed_in_order):
        try:
            results.append(fn())
        except Exception as exc:
            results.append(_ok(fn.__name__, False, f"{type(exc).__name__}: {exc}"))
    failed = results.count(False)
    print(f"  {len(results) - failed}/{len(results)} held, {failed} open")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
