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

BUDGET_INR = 293.51   # ledger 214.62 + Rs 78.89 usable (Rs 100 topped up, Rs 21.11 cleared the overdraft)

CROSSFADE_SECONDS = 0.0   # hard cut; do not use transitions to conceal bad continuity

PLANNER_MODEL = "gemini-3.5-flash-lite"

# The ledger is an ESTIMATE and has already drifted 1.64x against real billing once.
# It is a guard, never an authority. Reconcile against AI Studio before trusting it.
SAFETY_MARGIN = 1.5      # every estimate is inflated by this before it is charged
