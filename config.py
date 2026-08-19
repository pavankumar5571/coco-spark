"""Explicit generation contract. No provider defaults are permitted to apply."""

PROVIDER_SURFACE = "GEMINI_DEVELOPER_API"   # not Vertex; audio-bundled SKUs apply

IMAGE_MODEL   = "gemini-3.1-flash-image"
IMAGE_ASPECT  = "16:9"

VIDEO_MODEL   = "veo-3.1-lite-generate-preview"   # LITE, not full tier
VIDEO_RES     = "720p"                            # not 1080p
VIDEO_SECONDS = 4                                 # allowed {4,6,8}; shortest that works
VIDEO_ASPECT  = "16:9"

# Rough INR estimates for the running total. Verify against real billing.
INR_PER_IMAGE   = 5.0    # MEASURED-ish; was 3.5 (underestimated)
INR_PER_VID_SEC = 8.0    # MEASURED: ~Rs 32/4s clip, was 4.4 (underestimated ~2x)

# Ledger 327.29 + the approved E01 opening slice (169.50 worst case, fully reserved
# before the first paid call). A CEILING, NOT A TARGET: if a reservation will not fit,
# that means STOP, not raise the cap. NOT the account balance.
BUDGET_INR = 500.0   # The cap is per-experiment on purpose: an open cap is how the
                     # previous project reached Rs 30,000. (Account had ~Rs 2433.)

# Veo rewrites the prompt before generating unless told not to. Our prompt is COMPILED
# from the bible and the camera compiler, so letting the provider rewrite it hands our
# controlled input to an uncontrolled paraphrase — a prime suspect for the particles that
# appeared despite an explicit no-particles clause.
VIDEO_ENHANCE_PROMPT = False

VIDEO_SEED = None
VIDEO_NEGATIVE_PROMPT_SUPPORTED = False

# What this provider surface ACTUALLY accepts, established by making the call and reading
# the rejection -- not by reading the SDK. GenerateVideosConfig exposes all three of these
# fields; two of them are refused by the backend. A field existing in the client library
# says nothing about the model honouring it.
#
# Each rejection below arrived BEFORE generation, so the reservation released and none of
# them cost anything. That is the reserve-before-invoke design earning its keep.
SURFACE_FINDINGS = {
    ("veo-3.1-lite-generate-preview", "seed"):
        "REJECTED 2026-08-19: 'seed parameter is not supported in Gemini API'. "
        "No reproducible re-renders on this surface.",
    ("veo-3.1-lite-generate-preview", "negative_prompt"):
        "REJECTED 2026-08-19: 400 INVALID_ARGUMENT, '`negativePrompt` isn't supported by "
        "this model'. Exclusion cannot be expressed as a parameter here; prose in the "
        "prompt body is the only channel, and prose already failed 3 of 4 clips.",
    ("veo-3.1-lite-generate-preview", "enhance_prompt"):
        "ACCEPTED 2026-08-19 (not rejected at request time). Whether the backend HONOURS "
        "it is untested and must not be assumed.",
}

CROSSFADE_SECONDS = 0.0   # hard cut; do not use transitions to conceal bad continuity

PLANNER_MODEL = "gemini-3.5-flash-lite"

# The ledger is an ESTIMATE and has already drifted 1.64x against real billing once.
# It is a guard, never an authority. Reconcile against AI Studio before trusting it.
SAFETY_MARGIN = 1.5      # every estimate is inflated by this before it is charged

# Explicit contract versions. Bump on ANY semantic change to the corresponding compiler,
# so a cached artifact made under older behaviour is invalidated. Clearer than pretending
# the code is immutable or trying to hash source automatically.
PLAN_CONTRACT_VERSION  = "1"
FRAME_COMPILER_VERSION = "1"
PLANNER_MAX_INR        = 3.0    # conservative reservation; token cost is unknown up front

# Production spend requires a committed tree, so a paid result can always be attributed
# to an exact revision. Tests set this False to exercise other properties, and one
# dedicated test asserts the guard itself.
REQUIRE_CLEAN_TREE = True
