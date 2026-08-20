# Decisions

## R2 instead of GCS — AGREED IN PRINCIPLE, BLOCKED FOR NOW (2026-08-19)

**Decision.** Cloudflare R2 is the preferred future media/archive object store. No R2 work
enters the E02 critical path. `mini` stays local through E02's publication.

**Why it came up.** Pavan asked to replace GCP with R2 because R2 is free.

**What was actually found.**

| system | GCP dependency |
|---|---|
| `mini` (this pipeline) | **none** — Gemini *Developer* API (an API key, not a GCP project), artifacts on local disk and in git |
| `enterprise-ai-yt` | `AIS_GCS_BUCKET=ai_youtube`, service-account credential, `WF_STORAGE_TIERING`, `WF_ARCHIVE_EPISODE`/`RESTORE`, a `fakegcs` test fixture |
| `prev/` | same pattern, in the dead system |

So the thing to replace is not in the system being built.

**The numbers, checked rather than remembered.** R2 Standard: 10 GB-month storage, 1M Class
A operations, 10M Class B operations, free internet egress. GCS also has a free allowance —
5 GiB Standard plus operation allowances, and in eligible North American cases 100 GiB of
outbound transfer — and charges beyond it.

**A correction to my own argument.** I wrote that "GCS bills every byte pulled back out".
That is too broad: transfer pricing depends on source, destination and location, and
includes free and intra-location cases. GPT caught it. The migration may still be right; it
does not need an inaccurate justification.

**Why it is blocked rather than merely deprioritised.** By our standing bar — *which
demonstrated E02 blocker does this remove?* — none. Adding R2 to `mini` now would introduce
credentials, network I/O, upload and download failure modes and consistency semantics into a
pipeline whose entire advantage is that every artifact is local, checksummed and immutable.

**The architecture when it does happen** — and the ordering is the point:

    local working set -> immutable accepted artifact -> asynchronous R2 archival
    -> local production continues -> release artifact archived to R2

not `every stage -> R2 -> download -> next stage`. That keeps a storage outage outside the
generation path while eventually getting the MP4s and PNGs out of git. Git should hold code,
schemas, manifests, hashes, provenance and QC verdicts — not a growing library of binaries.

**Before scheduling the `enterprise-ai-yt` migration, two things:**

1. **Measure the actual GCS spend.** At Rs 30/month this is a tidiness project wearing a
   cost-saving costume and should be scheduled honestly as one. At Rs 1,000/month the
   priority changes. Evidence decides, not the word "free".
2. **Inventory every GCS semantic those workflows rely on.** My "about a day" estimate is
   not accepted: S3 compatibility makes the object API easy, but storage tiering,
   archive/restore, authentication assumptions and any precondition behaviour are not
   automatically behaviour-compatible. An API-compatible PUT/GET is not compatible storage.

**Not doing, and strongly:** moving `mini`'s paid artifacts to R2 before the channel has
published anything. The expensive provider outputs stay local, immutable and provable during
production.

## "Proper video motion", and what we will spend to get it (2026-08-19)

**Pavan's requirement:** *"i dont want kanban style i want proper video motion format"* —
delivered after approving the animatic's pacing and locking take eb63dca0. An aesthetic
rejection of the stills grammar, not a cost objection.

**The number that bounds the argument.** Full generative motion for 71 seconds is 18 clips:
**Rs 658, worst case Rs 987**, against **Rs 119.48** of authorisation. Even two generated
beats do not fit (Rs 84 estimate → Rs 126 worst case). Exactly one 4-second generated beat
fits alongside stills. So this is a **cap decision, and it is Pavan's alone.**

**The false binary to avoid:** still-plus-zoom ←→ full generative video. There is a large
design space between them, and we have only just stepped into it.

**Ruling (GPT, agreed):**

1. **Spend Rs 0 now.**
2. **E01 → unlisted upload.** It validates YouTube ingestion, processing, Made-for-Kids,
   metadata, thumbnail, and audio after transcoding. It tells us nothing about whether the
   product works for viewers, and must not be treated as an audience test.
3. **The 6-second per-frame motion sample → Pavan's eyes.** If he says it feels like Coco
   Spark TV, we have found a very cheap production primitive and E02 continues under the
   Rs 600 cap. If he says it still looks like a moving picture, **believe him and kill the
   approach immediately** — do not spend a week improving it.
4. **If the sample fails:** do NOT buy the Rs 57 stills episode and do NOT raise the cap to
   Rs 1,000 for full Veo. Build one 5–8 second **deterministic character-motion prototype**
   from existing Coco imagery first — breathing, blink, small head/arm movement, animated
   stars, exact Suno timing — using layered assets over a stable world plate. The expensive
   model would generate *assets and poses*, not every second of video. No framework, just
   enough to answer the question.
5. **If that also looks cheap:** we have strong evidence Coco Spark TV genuinely needs
   generative video or another animation technology. *That* is when to investigate providers
   and reconsider the budget — not after buying 71 seconds.

**Not a gate yet:** audience retention. An unlisted upload is not an audience experiment.
First prove Pavan considers the visual format worthy of the channel name.

---

## PROVABLE_AUTHORITY — the invariant behind C01

**Ruling (GPT, 2026-08-20, agreed).** Keep SCOPE_PREFLIGHT as a concrete OAuth control.
Record the principle; do not build a universal engine for it, or C01 stops being
publishing verification and becomes infrastructure architecture.

> Before an operation can make an assertion, its execution environment must possess and
> demonstrate the authority and runtime capability required both to perform the operation
> and to verify the resulting state.

Three distinct checks, and today produced a real failure of each:

    AUTHORITY      the credential grants the required permissions
                   -> both this project AND enterprise-ai-yt minted upload-only tokens
    RUNTIME        the required runtime exists and is compatible
                   -> no Python on the operator's machine; the release path could not run
    OBSERVABILITY  the resulting state can be independently read back
                   -> verify returned 403; the check existed, the credential defeated it

**Acquisition-time validation is necessary and not sufficient.** Credentials get revoked,
scope policies change, runtimes disappear between consent and use. So the mutation path
also performs a cheap operation-specific preflight immediately before invoking an external
mutation — `upload_private` checks `upload` authority in the moment it is about to write.

## Duration authority

**Our measured media duration is authoritative for production.** YouTube's reported
duration is an external observation and a QC signal, never timeline authority.

    media_duration_s            measured from our encoded artifact — AUTHORITATIVE
    platform_reported_duration  YouTube's representation after ingestion
    platform_duration_delta_s   platform_reported - media_duration

Beat maps, cuts, animation events, intro/outro placement, A/V sync and compilation runtime
all use the measured media timeline. **Compilations must probe the archived masters and sum
their real durations** — never sum YouTube's displayed integers, because at 2.5 hours the
accumulated rounding becomes material.

Keep `duration_delta_s`. It is good evidence. E01 measured +1.0s (12.000s master, PT13S
reported), but a tolerance must come from repeated uploads, not from n=1.

## Module order, restated

    C01  Publishing Verification   Claude   verified -> battle-test -> cross-review -> merge
    G01  Opportunity Engine Audit  GPT      in parallel; enterprise publication records are
                                            TAINTED EVIDENCE until independently reconciled
    B01  E02 Brand + Timeline      Claude   BLOCKED until C01 merges. Small: signature
                                            contract, watermark, outro timing, thumbnail
                                            contract, programme loudness requirement. No
                                            "branding platform".
    E02 picture spend              BLOCKED until G01 rules on Five Little Stars

## Loudness, corrected

Do not derive a house target from YouTube's playback normalisation. They are separate
things — see PUBLISH.md, where -14 LUFS is already recorded as OURS and not YouTube's.
E02 gets a Coco Spark mastering contract measured before upload (integrated loudness, true
peak, silence, dynamics); YouTube's processed result is a second, later measurement.

E02 also delivers the first real post-platform A/V sync test: pick known lyric onsets
before upload, inspect the processed result against those same events. That closes the hole
E01 correctly left as NOT DETERMINABLE, because a test tone has no onset to align against.
