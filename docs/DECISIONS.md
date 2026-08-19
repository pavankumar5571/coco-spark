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
