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

# Ledger 470.52 + a purpose-built cottage_night plate (7.50) + the E01 closing shot
# (7.50 frame + 48.00 clip). Raised by Pavan to 600 to buy the plate BEFORE re-rendering
# s04, because our own plate QC graded the existing authority WEAK on the exact object
# that broke that shot.
# A CEILING, NOT A TARGET: if a reservation will not fit, that means STOP, not raise the
# cap. NOT the account balance.
BUDGET_INR = 600.0   # The cap is per-experiment on purpose: an open cap is how the
                     # previous project reached Rs 30,000. (Account had ~Rs 2433.)

# Every generation-parameter lever we hoped for is refused by this model. NO parameter on
# veo-3.1-lite/Gemini Developer API can express exclusion, disable rewriting, or pin a
# seed. Prose in the prompt body is the only channel that exists here, and prose failed on
# 3 of 4 clips. This is a SURFACE limit, not a wording problem.
VIDEO_ENHANCE_PROMPT = None          # REJECTED by this model; see SURFACE_FINDINGS

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
        "REJECTED 2026-08-19: 400 INVALID_ARGUMENT, 'enhancePrompt isn't supported by "
        "this model'. It cannot even be SENT, so the prompt-enhancer hypothesis is not "
        "merely unproven on this surface -- it is untestable. That a model refuses the "
        "field is also weak evidence it does no prompt rewriting to disable.",
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

# ─────────────────────────────── audio ───────────────────────────────
# The provider generates native audio we never asked for, and it generates it PER CLIP.
# Measured on E01's accepted footage: s01 -17.2 LUFS, s02 -30.6, s03 -27.4 — a 13.4 LU
# lurch at the first cut, on footage a human had already accepted, because every probe we
# had ever written looks and none of them listens.
#
# Normalising three independently invented room tones only makes three different rooms
# equally loud. So the programme's audio is AUTHORED AT EPISODE LEVEL and the provider's
# is discarded as a generation by-product: one continuous bed cannot have a seam at a cut,
# because it does not know a cut happened.
STRIP_PROVIDER_AUDIO = True

# A HOUSE mixing target, not a YouTube requirement. YouTube does not publish a mandatory
# upload loudness; it normalises loud material on playback. -14 LUFS is where we choose to
# deliver so our own episodes match each other.
PROGRAMME_LUFS           = -14.0
PROGRAMME_LUFS_TOLERANCE = 1.5
PROGRAMME_TRUE_PEAK      = -1.5
AUDIO_FADE_SECONDS       = 1.5    # bed in and out, so an episode never starts or ends abruptly

# A deliberate closing hold built from pixels already accepted, rather than bought. Free.
ENDING_HOLD_SECONDS = 3.0
ENDING_PUSH_PERCENT = 4.0    # how far the slow push-in travels over the whole hold
ENDING_FADE_SECONDS = 1.5    # fade to black, inside the hold
