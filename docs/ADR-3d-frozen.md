# ADR: 3D is PROVEN_PROMISING and NOT_ADOPTED

Decided 2026-08-19 jointly, after Gate 1 and a drift audit that Pavan's question forced.

## Gate 1-A result — single image, front crop only

Graded on the 8s turntable at four fixed angles against the five frozen observations.

    FACE/HEAD IDENTITY     PASS   excellent from front; eye reads as a white sliver in
                                  the two profile frames — the weakest thing observed
    SILHOUETTE/PROPORTIONS PASS   head-to-body, limb length, shell volume all hold
    CLOTHING/FORM          PASS   the hoodie stays a GARMENT layered over the shell
                                  rather than melting into the body
    ASYMMETRIC MARKER      PASS   patch present on the left, ABSENT on the right
    REAR GEOMETRY          PASS   real shell panels, hood at the neck, not mush

From ONE image. Better than expected.

GPT's correction, recorded because it matters: this does NOT show the model "understood"
an unseen bare right sleeve. With front-only input the right side is inferred, so the
desired asymmetry is a successful outcome that may also be fortunate. G1-B exists to test
whether explicit multi-view evidence makes it reproducible rather than lucky.

## The audit that changed the decision

Pavan asked why we cannot use nano banana. The literal answer is that we already do —
nano banana IS Google's Gemini image model and config.IMAGE_MODEL is
gemini-3.1-flash-image. It also cannot do this job: TRELLIS outputs a mesh, nano banana
outputs a picture.

But the question exposed an unexamined premise. WHERE HAS COCO ACTUALLY DRIFTED?

    our pipeline, Gemini    IDENTITY_PRESERVATION PASSED on every clip ever generated.
                            P01, P01B, E01 s01, s02, s03. Coco has never drifted.
    ChatGPT image gen       the russet turnaround. A DIFFERENT generator.
    room object forms       s04 — missing LOCATION authority. A world problem, not a
                            character problem.

We were evaluating a 3D pipeline to permanently fix character identity drift, and our
character identity has not drifted in our own stack. The thing actually blocking E01 is a
ROOM, and a mesh of Coco does not fix a room.

## Retracted

    "We need 3D because Coco cannot remain consistent."

There is no evidence for that claim. It was the load-bearing argument for the entire
detour and it does not survive the audit.

## What survives

A production-economics hypothesis: a reusable 3D asset system could eventually give
deterministic characters, environments, cameras and animation at low marginal cost per
episode. Potentially large at 50-100 episodes. It is not an E02 blocker.

And it has many unproven gates after reconstruction — rigging, deformation, facial
performance, appealing animation, multi-character interaction, environment construction,
lighting, rendering, throughput. G1-A crossed the first small bridge only.

Status: PROVEN_PROMISING / NOT_ADOPTED. No Blender, no rigging, no facial rig, no
subscription, no Coco upload.

## Three problems we had wrongly bundled

    character identity      canonical reference images appear SUFFICIENT with Gemini
    world consistency       text cannot preserve detailed object FORM; two attempts to
                            manufacture a universal plate outside observed pixels failed
    animation economics     Veo charges per generated second and returns probabilistic
                            motion and camera behaviour

Different problems, different solutions. Treating them as one is what produced a 3D
detour aimed at the wrong defect.

## Not resurrecting universal plates either

GPT's amendment, taken: do not go back and try to solve omniscient world plates. That
route is falsified twice for cottage_night.

The better future abstraction, NOT to be built now:

    WORLD = topology + accepted visual observations + persistent-object references

cottage_night would eventually carry a room-wide accepted reference plus separate
bookshelf, bed/quilt, chair, window and rug references, with topology describing their
relationships, and a shot compiler selecting only what the requested composition needs.
That is what already works for characters: SHOW the form rather than describe it.

Deferred deliberately. We have already paid to learn not to generalise infrastructure
before an episode demonstrates the abstraction is needed.

## Consequence for E02

Do not design E02 around cottage_night merely because we own it. That is sunk-cost
thinking, and cottage_night is the one world we have proven is hard to control.

Design E02 around a world that is inherently easy to control — a soft stage, a garden
clearing, a cloud world, a simple geometric space. Keep persistent geometry sparse and
intentional. Let the characters carry the episode rather than twelve pieces of furniture
that must each survive generative reinterpretation.

## The principle this session actually earned

    Use GENERATION where variation is desirable.
    Use REFERENCES where identity or form must persist.
    Use DETERMINISTIC COMPUTATION where correctness must be guaranteed.

That is the architecture the experiments support, not the one we originally imagined.
