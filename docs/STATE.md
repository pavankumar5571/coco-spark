# Coco Spark TV — verified state, 2026-08-20

Rewritten at every milestone so a new session starts with no gap. Everything here is
checkable; where it is not, it says so.

    ledger      Rs 485.52 of the Rs 600 cap. Rs 114.48 authorised and unspent.
    spent today Rs 0.
    main        419782c

## Production-system direction — locked

The durable generic contract is `docs/PRODUCTION-AUTOMATION.md`. The loop is YouTube mining
evidence -> Gemini structured plan -> repairable schema validation -> Suno song when needed
-> reusable Blender assembly -> deterministic and semantic validation -> bounded repair ->
render/private publish -> YouTube measurements back into mining. A rejected schema is
repaired or falls back under a fixed policy; it is not silently abandoned. Episode content
is data. Production code must survive replacing Coco, E02 and the bedroom with unrelated
cast, episode and location data.

GitHub Actions is orchestration, R2 is large-artifact storage, and a runner executes Blender.
Pavan's Windows computer is development-only, not a permanent launch dependency. Paid R2
billing or ephemeral cloud/GPU execution remains behind Pavan's money approval.

## What is published

E01, video id `nFN75I3MlV8`, **PRIVATE**, uploaded 2026-08-20 04:25. First artifact this
project has ever put on a platform. Verified by reading the API back rather than trusting
the upload: privacy `private`, madeForKids `true`, uploadStatus `processed`, processing
`succeeded`, duration `PT13S` against a 12.000s master, title as intended. Frozen as
`TEST_ARTICLE` — no s04, no particle repair, no branding, never public.

Human inspection passed on playback, audio, aspect and privacy state. **A/V sync is
recorded as NOT DETERMINABLE**, not as a pass: the master's audio is a test tone, so there
is no onset to align a picture against. E01 verified the pipe, not the timing.

## Modules

    C01  Reproducible Launch Env + Private Publishing   MERGED at 3832091
    G01  Opportunity Engine Audit                       RULED, off the critical path
    G02  Opportunity Evidence Engine                    MERGED, 5/5 attack routes closed
    G03  Collector + persistence                        CLOSED at 29da8bb, both signatures
    G04  YouTube API adapter                            CLOSED at 402e5d2, both signatures
    B01  E02 Brand + Timeline                           not started
    E02  first public episode                           BLOCKED on a design decision

C01's six contract items all pass, proved in a clean container in CI, not on a developer
machine: fresh environment bootstraps, secrets do not leak, offline suites pass, upload is
idempotent, privacy cannot accidentally become public, observed state is verified.

## Open, and who owns it

**G03 is closed.** The one thing this system had never done - observe the same
videos twice, an hour apart, across a process restart - it did at 19:51:57Z on 2026-08-20.

    video          t0     t1   delta   elapsed   views/hr
    1iXF33mEJaw   340    340       0    1.006h        0.0
    KTCnNsY9fOw    16     16       0    1.006h        0.0
    FmPPe5ADuZ8     0      2      +2    1.006h        2.0

    OPPORTUNITY_UNPROVEN, opportunity_proof_allowed TRUE for the first time,
    2 API calls, 2 quota units, no search - the ids came from SQLite.

The interval is a measurement, not a parameter: two clock reads by two processes, and
nothing in the path lets a caller supply it. The system was finally ABLE to declare an
opportunity and declined to, which is the result that matters - a system tuned to say yes
would have said yes to a two-view hour.

The final attack focused on the two zero deltas, because zero is also what a cached
response looks like.

The cache attack subsequently used a second request with the three IDs in reverse order,
creating a distinct request key. It returned the same mixed values: 340, 2, and 16. This
rules out a URL-keyed or client-side replay; the changed video shows the valid batch was
not uniformly stale. It cannot rule out an opaque provider-side cache. No API client can prove
the provider's internal event stream. G03's measured fact is therefore stated narrowly:
these were the counters YouTube returned at each observation instant, including real
numeric zero deltas rather than missing values.

The committed SQLite artifact contains nine raw rows, not six: after Claude's valid
19:51:58Z refresh, Codex's overlapping heartbeat made a second refresh at 19:52:50Z.
Those last three rows are explicitly `below_minimum_interval=true`, remain available for
audit, and are excluded by `snapshots()` and from opportunity evidence. Thus the artifact
contains six eligible rows across two valid instants and three audit-only rows at a third
instant. The extra run cost two quota units and did not alter the verdict. It also became
an unplanned production trial of the interval guard: all three live rows were preserved
for audit and excluded from evidence.

Future live experiments have one designated writer. The reviewing agent reads a copied
artifact, so coordination cannot add measurements while a result is being described.


**THE CHARACTER.** The channel's public logo and the production bible are two different
bears. `bible.yaml` says *bright red short-sleeved t-shirt with a small yellow star*; the
channel avatar shows a **blue patterned bandana**, pink inner ears and cheek blushes. Every
paid portrait and all four Tripo views came from the bible, so the pipeline has been
rendering a character the audience has never seen. GPT's Gate-1 observation list in message
225 names the blue bandana — it was known once and never reached the bible.

Pavan has said a new logo is acceptable if both agents agree, so this is ours to settle.

**E02's grammar.** Stills-plus-camera-move is FALSIFIED, by Pavan, twice, on aesthetic
grounds — messages 219 and 224. It costs Rs 52 and fits the cap and is still the wrong
product. Do not cost it again.

**Spend.** Nothing is authorised. Whatever E02 becomes, its first rupee is Pavan's call.

## 3D — un-frozen on corrected grounds

`ADR-3d-frozen.md` froze 3D because the argument was "we need it because Coco drifts", and
the audit showed Coco has never drifted in our own stack. That reasoning stands and answers
a question nobody asked. Pavan has never complained about drift; he has complained three
times about MOTION QUALITY. Un-frozen for motion quality and recurring production
economics, co-signed by Codex.

Gate 1-A passed all five frozen observations on a clean-room turtle — deliberately not
Coco, so no channel IP went to a third party. GPT's own assessment: reconstruction 7/10,
**full 3D episode pipeline 4-5/10**, because rigging, deformation, facial animation,
lighting, scene integration and throughput are all untested.

**There is no clean free image-to-3D route on this machine.** Codex checked each licence
and hardware requirement: TripoSR is clean MIT but single-image and needs ~6GB VRAM;
TRELLIS needs Linux and NVIDIA 16GB+ and this machine has no `nvidia-smi`; TRELLIS.2 has an
open issue that the repo has no LICENSE file; Hunyuan3D-2's licence excludes the EU, UK and
South Korea; Stable Fast 3D is Stability's gated licence. Tripo's free tier is an IP
giveaway — CC BY 4.0, models made public, commercial use prohibited.

So the route is **Blender-first**: model from the four owned orthographic views, Rigify,
render locally. Blender states artwork and .blend data are the creator's property with
commercial use allowed. No generator, no subscription, no GPU, no licence audit.

    Blender 5.2.0 LTS installed, Rigify present
    blender/scaffold.py  NOT DONE. It works, and it hardcodes assets/design/coco/ —
                         so it fails the standing genericity test and must take a
                         character id before it can be called finished. Recorded as
                         unfinished rather than as a future tidy-up: deferred
                         generalisation is a defect with a promise attached.
    brief.py             mode names (BEDTIME_STORY, SONG, STORY) live in code rather
                         than in the bible. Same class, smaller.

Rigify does not coerce a human silhouette — metarig bones are repositioned to the
character. The real risk is skin weighting, so Gate 1-B must include shoulder, hip, elbow,
knee, neck and facial deformation poses before adoption.

## E02 timing — done and unaffected by the visual decision

`brief.py` compiles the phrase map and beat map into one production brief. The song is the
clock whoever draws the pictures, so this survives the switch to 3D intact.

    master_t = signature_seconds + song_t     branding shifts the ORIGIN, never a word

It found four defects on its first run, all free. The episode **opened on nothing** — beat
0 started on the first sung word, leaving 2.5s of instrumental lead-in with no picture.
Two counting beats were hand-typed at 37.19 and 37.90 while the words they count are sung
at 37.66 and 38.37 — the counting cuts did not land on the counts. The beat map's note
claimed 15 cuts over 7 pictures where the data says 16 over 4 stills. And SONG programme
loudness is UNSET and refuses rather than defaulting: `--private-test` yields -20.0 marked
`PROVISIONAL_FOR_PRIVATE_TEST`, and `public_release_allowed` stays false until a human has
listened to a real mastered mix.

## Where the money went, and what it bought

Six paid clips ever. Four accepted, two rejected. The findings that cost real rupees:
particles in three of four clips with no provider control on this surface; an unrequested
accelerating push-in on half of them, measurable and correctable offline; and a WIDE shot
that invented a room because prose cannot pin object FORM. All three are why the pipeline
now prevents rather than discovers.
