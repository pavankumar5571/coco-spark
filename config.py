"""Explicit generation contract. No provider defaults are permitted to apply."""

PROVIDER_SURFACE = "GEMINI_DEVELOPER_API"   # not Vertex; audio-bundled SKUs apply

IMAGE_MODEL   = "gemini-3.1-flash-image"
IMAGE_ASPECT  = "16:9"

VIDEO_MODEL   = "veo-3.1-lite-generate-preview"   # LITE, not full tier
VIDEO_RES     = "720p"                            # not 1080p
VIDEO_SECONDS = 4                                 # allowed {4,6,8}; shortest that works
VIDEO_ASPECT  = "16:9"

# Rough INR estimates for the running total. Verify against real billing.
INR_PER_IMAGE   = 3.5
INR_PER_VID_SEC = 4.4     # ~$0.05/s at 88 INR/USD, Lite with audio on Developer API

BUDGET_INR = 100.0        # hard stop
