# Production automation contract

This is the session-independent target architecture. It is generic: episode content is
data; production code must not contain Coco, E02, bedroom, bedtime or other episode cases.

## Closed loop

    YouTube mining -> opportunity evidence -> Gemini episode specification
      -> schema repair -> Suno song (when the format requires one)
      -> asset resolution -> Blender assembly -> deterministic validation
      -> semantic critique -> bounded repair -> preview/final render
      -> private publish -> YouTube measurements -> next mining cycle

Responsibilities are deliberately separated:

- YouTube mining supplies reproducible demand and channel-performance evidence. Gemini may
  interpret that evidence; it may not silently replace an evidence-backed opportunity.
- Gemini is the writer/director and semantic critic. It emits schema-constrained plans and
  bounded patches, never arbitrary Blender operations.
- Suno is the song generator: vocals, melody, arrangement and instrumental. Its outputs
  carry prompt, account/plan, commercial-rights evidence and hashes. Any paid generation
  stops at the money gate.
- Blender is the deterministic visual production engine: reusable assets, rig actions,
  scene assembly, cameras, lighting and rendering.
- Python validators enforce schemas, geometry, timing, continuity, collisions, framing and
  render health. GitHub Actions orchestrates; a runner executes Blender; R2 stores immutable
  large artifacts. R2 does not execute jobs.

Veo and image generators are optional asset/special-shot providers, never required for the
core episode path. Their use is paid and therefore requires Pavan.

## Rejection means repair, not abandonment

Schema validation has three bounded levels:

1. **Deterministic repair** fixes mechanical defects such as types, missing safe defaults,
   numbering, rounding and approved-name aliases.
2. **Constrained semantic repair** sends exact errors to Gemini and accepts only a JSON
   Patch or corrected fields. Valid portions of the episode are not regenerated.
3. **Deterministic fallback** substitutes an approved camera/action/location template that
   preserves intent after the retry limit.

Only an unrecoverable rights/safety failure, unavailable critical asset, editorial meaning
change, irreversible outward act or money requirement escalates to Pavan. Every attempt,
patch, fallback and final verdict is recorded in the build manifest.

## Episode interface

An episode file contains content only: opportunity evidence ID, cast, location, reusable
asset versions, beats, actions, expressions, dialogue, song brief, camera intent, props,
effects and render profile. A beat is executable and measurable, including duration,
observable story state, required/forbidden visibility, continuity and exit conditions.

The same episode specification must run locally, on a self-hosted runner or on an on-demand
cloud runner. Executor configuration may change; episode logic may not.

## Automated Blender gates

Before rendering, scene-space checks use camera projection, ray casts, rigs and constraints
to validate screen position/size, visibility, occlusion, look/movement room, gaze, contacts,
collisions, pose checkpoints, state and continuity.

Low-resolution probes at entry, quarter, middle, three-quarter and exit frames add image
checks for empty/black frames, clipping, contrast, silhouette, face visibility, clutter,
flicker and expected object counts. Object Index or Cryptomatte masks provide subject truth.

Composition repair searches only approved bounded controls: camera templates and permitted
regions, focal length, aim target, lighting presets, action duration, placement zones and
declared deformation controls. It scores valid candidates, records the winner and never
opens Blender for episode-specific hand adjustment.

Gemini Vision may rank technically valid probes for intent/readability and propose changes
expressible through those controls. It cannot waive deterministic failures. After a fixed
attempt budget, the engine uses a conservative approved template or reports an explicit
unrecoverable contract failure.

## Execution and storage

Development may use the installed local Blender for Rs 0. It is not the permanent launch
runner: keeping Pavan's computer powered on is not an acceptable production dependency.
The launch design is runner-independent and supports an ephemeral cloud Blender runner that
starts for a job, retrieves versioned assets, renders, uploads, and terminates. Activating
R2 billing, GitHub GPU runners or any cloud compute requires Pavan's cost approval.

Git stores code, schemas, small manifests, hashes, provenance and verdicts. R2 stores large
versioned assets, `.blend` builds, probes, frames, audio and masters. Uploads are resumable;
published/released artifacts are immutable; temporary probes and failed scratch builds have
lifecycle expiry. A storage outage must not corrupt an accepted local artifact.

## Release and learning

A passing build report includes per-beat composition, action, continuity, audio-sync and
render verdicts. Technical success is not authority to publish: the first release remains
private until the existing publishing and perception gates pass. After release, impressions,
CTR, retention, rewatches, traffic/search terms and subscriber conversion become new mining
evidence. Predictions and actual outcomes are compared so the next opportunity score and
creative plan improve.

The target is a deterministic animation compiler:

    evidence-backed episode specification -> validated Blender episode

The battle-test bar remains three materially different episodes with no production-code
patches between them.

## Module acceptance gate

No module is authoritative because its author says it works. Every module in the closed
loop must pass this sequence before merge and before a downstream module may rely on it:

1. One agent implements the contract and supplies retrievable evidence.
2. The other agent reads the exact source commit, independently attacks assumptions and
   contributes adversarial scenarios; reviewing the handoff description is not acceptance.
3. The implementation is repaired against every valid finding.
4. At least three materially different scenarios pass, including a valid control, a likely
   false-positive case and a missing/ambiguous/adversarial-evidence case. A module may require
   more scenarios when its failure space is broader.
5. The combined scenario set is frozen and rerun from a clean checkout with no production-
   code patches between scenarios. Paid calls remain zero unless Pavan explicitly authorises
   that module's paid battle.
6. Both agents post explicit `ACCEPT` entries naming the same commit and evidence. Silence,
   session expiry, green CI or one agent's acceptance cannot substitute for the second.
7. Only then is the branch merged and the next module allowed to treat the output as
   authoritative.

A later module may expose a missed defect. That reopens the owning module, adds the case to
its frozen regression set, and repeats the two-agent gate; it must not be patched downstream
as an episode-specific workaround.
