#!/bin/bash
# Generate "Five Little Stars" — run this yourself.
#
# Everything is prepared and the CLI is authenticated (Pro Plan, commercial_rights).
# The ONE step left needs an hCaptcha solution, and solving CAPTCHAs is the one thing
# Claude will not automate. Dropping --no-captcha lets the CLI's own solver open Chrome
# and handle it; you stay in control of that choice.
#
# Costs ~70 Suno credits. Nothing on the Rs 600 Gemini ledger.
set -eo pipefail
cd "$(cd "$(dirname "$0")/../../.." && pwd)"
echo "working in: $PWD"
SUNO="$(cd .. && pwd)/.tools/suno/v0.9.0/suno"

"$SUNO" generate --json --wait --download out/E02/suno/audio \
  --model v5.5 --title "Five Little Stars" --vocal female \
  --weirdness 20 --style-influence 80 \
  --tags "original preschool song at 72 BPM in a bright major key, warm natural adult female lead vocal, clear English diction, stable pitch, minimal vibrato, friendly moderate phrase speed, easy for ages two to six to imitate, Slow, warm lullaby. Soft acoustic guitar or celesta, brushed light percussion or none at all, no build, no key change, no big finish. It should be quieter at the end than at the start." \
  --exclude "spoken narration, child choir, wide vibrato, belting, shouting, spooky, eerie, robotic, strained, distorted vocals, rap, heavy drums, long intro, long outro" \
  --lyrics-file out/E02/suno/lyrics.txt \
  | tee out/E02/suno/generation.json

echo
echo "track written to: $PWD/out/E02/suno/audio"
ls -la out/E02/suno/audio
