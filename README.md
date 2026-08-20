# Coco Spark — minimal episode pipeline

848 lines. No Docker, no Postgres, no queue, no orchestration framework.

    episodes/<id>.yaml   9-line brief: id, mode, title, location, cast, shots, idea
    bible.yaml           channel-wide: cast, locations+geography, typed vocab, mode policy
    validate.py          deterministic validator, zero model calls, zero cost
    make.py              plan -> portraits -> frames -> video -> assemble
    config.py            the generation contract; no adapter defaults may apply

## Run

    python make.py plan E01        LLM writes shots.json, HARD GATED by the validator
    python make.py portraits       canonical identity anchors, once per channel
    python make.py episode E01     interleaved: frame -> clip -> frame -> clip -> assemble

## Operating rule

Every abstraction must be justified EITHER by an observed failure OR by a clearly stated
invariant whose violation would be materially harmful. The first half blocks speculative
complexity; the second half stops us waiting to lose money before implementing an obvious
safety property.

Review standard: adversarial. Most defects in this codebase were found when one reviewer
tried to falsify another's confidence, reading source rather than summaries.

**PROVABLE_AUTHORITY.** External mutation is allowed only when AUTHORITY, RUNTIME and
OBSERVABILITY for the operation are proven before the mutation. Reasoning and the three
real failures behind it are in `docs/DECISIONS.md`.

## Design rules, each learned from a real failure

1. STATE says what is true. EVENTS say why it changed. Every discontinuity must be
   explained by a typed event (ENTER/EXIT/MOVE/TRANSFER/STATE_CHANGE) — never inferred
   from prose. No English keywords: the audience is 48% India, 14% Bangladesh.

2. THE CUT RULE. On a CONTINUOUS boundary a material dimension may not differ across the
   edit; the transition must be shown inside a shot. Deliberate discontinuity requires an
   explicit boundary type (TIME_JUMP / LOCATION_CHANGE / MONTAGE), a narrative reason,
   and mode permission.
   Learned from: Coco fell asleep IN THE CUT. The viewer never saw the most important
   beat in a bedtime story.

3. PREDECESSOR-PIXEL INHERITANCE. When a boundary is CONTINUOUS and material AND visual
   state are unchanged, the next first frame IS the previous clip's final frame. Copy it.
   Free, byte-identical, and the discontinuity becomes structurally impossible.

4. RESUME REQUIRES PROOF. Artifact exists AND provenance.status == COMPLETE AND
   input_hash matches AND checksum matches. os.path.exists() is not a checkpoint — a
   stale predecessor frame from an abandoned plan silently corrupted a run once.
   All writes are .tmp -> validate -> atomic rename.

5. PERSISTENT WORLD FACTS live in the bible, never in a shot prompt. A chair mentioned
   only in one shot's description vanished in the next.

6. FIXED GEOGRAPHY is explicit state. Without it shot 3 mirrored the room.

7. NO ADAPTER DEFAULTS. Provider surface, model, resolution, duration and audio mode are
   all explicit. A silent 1080p/8s/full-tier default is the difference between ~Rs 1,000
   and ~Rs 15,000 an episode.

8. THE LEDGER IS A GUARD, NOT AN AUTHORITY. It drifted 1.64x against real billing and
   overdrew the account. Reconcile against the provider.

## Status

Working: plan, validate, portraits, frames (with inheritance), video, assemble.
E01 rendered end to end.

Known gaps: the planner silently ignores brief instructions it does not satisfy (asked
for camera variation, returned all WIDE); props are declared in the schema but the
planner does not populate them; no post-video semantic QC; no billing reconciliation.


## Evidence state, 2026-08-19

    deterministic path        heavily exercised offline, 16/16 + 29/29
    motion primitive          PROVEN ONCE  (P01, SITTING_UP -> LYING_SIDE)
    identity preservation     PROVEN ONCE  (P01)
    world preservation        PROVEN ONCE  (P01)
    clip publishability       REJECTED     (P01, UNREQUESTED_VISUAL_ADDITION)
    prevention for that class IMPLEMENTED, NEVER VALIDATED AGAINST THE PROVIDER
    automated semantic judge  intentionally absent — one observation is not a threshold
    actual provider debit     UNRESOLVED

Other motion classes, multi-character interaction, prop transfer, walking and dialogue are
deliberately untested.
