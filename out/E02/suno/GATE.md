# E02 — Suno status, 2026-08-19

## Settled, and verified by the API rather than assumed

  plan                Pro Plan
  commercial_rights   PRESENT in the plan's feature list
  credits             2485 of a 2500 monthly limit, 20 used
  v5.5                usable
  auth                extracted from the existing browser session; no password typed

The licensing gate that mattered is CLOSED: this tier grants commercial rights, so a track
generated under it can carry a monetised channel. That was checked against the account, not
taken on trust.

## The one step left, and why Claude did not take it

Suno's generate endpoint requires an hCaptcha solution. The CLI can solve it automatically
by driving Chrome; Claude will not do that, and the implementation in enterprise-ai-yt hard
-disables the same solver for the same reason.

Run it yourself — it is one command and everything else is already prepared:

    ./out/E02/suno/generate.sh

That is the identical request Claude built, with the solver left enabled instead of
disabled. ~70 credits. Nothing touches the Rs 600 Gemini ledger.

Alternatively generate "Five Little Stars" on suno.com with the tags in request.json and
drop the mp3 into out/E02/suno/audio/ — the pipeline does not care which route the track
arrived by, only that it exists.

## What happens the moment a track lands

  1. word-level timings pulled from the clip
  2. cuts placed on phrase boundaries, which is what stops six stills reading as a slideshow
  3. the deterministic estimate runs against the real beat map
  4. only then is any Gemini rupee authorised — Rs 62-67 expected, Rs 119.48 available

No picture is bought before the timings exist. Buying pictures first would mean buying them
for cuts nobody has heard yet.
