# Publishing Coco Spark TV — verified facts, and what they mean for us

Checked against Google's own help pages on 2026-08-19. Secondary sources disagreed with
the primary ones on two points and the primary ones win; where a claim is ours rather
than YouTube's, it says so.

## Inauthentic content — the policy that decides whether this channel survives

YouTube renamed "repetitious content" to **inauthentic content** on 2025-07-15. Monetised
content must "be your original creation" and must not be "mass-produced, generic,
repetitive, or manipulative". AI is allowed: what is prohibited is "AI-generated content
made with generic or unoriginal templates giving the impression of mass production without
adding the creator's original, authentic insights or perspective", and the final product
"must still demonstrate your creative vision and provide educational or entertainment
value".

Consequences are limited or no ad earnings, suspension from the Partner Programme, or
channel termination — **case by case, and channel-wide in scope**.

There is **no three-strike system for AI content**. An earlier draft of our reasoning said
there was, sourced from SEO blogs rather than from YouTube. Corrected here.

WHAT IT MEANS FOR US. A cheap pipeline tempts you toward volume, and volume is precisely
the failure mode the policy names. Our per-episode human QC gate, our terminal
REJECTED_QC, our refusal to re-roll — that is not process overhead, it is the difference
between this channel and a channel that gets demonetised. Twenty judged episodes a year
beat two hundred unjudged ones, and the policy is the reason as much as the audience is.

  Source: https://support.google.com/youtube/answer/1311392

## Shorts

Up to **3 minutes**, maximum **1080p**. The upload path documented is vertical video; the
help page does not state that a 16:9 file is rejected, but it is not the documented route
either. E01 is 16:9 720p and should be published as a NORMAL video, not aimed at Shorts.
If Shorts is the target for a later episode, shoot it vertical from the first frame rather
than cropping a horizontal episode into one.

  Source: https://support.google.com/youtube/answer/10059070

## Made for Kids

Preschool content is Made for Kids and must be set as such. That setting removes comments,
notifications, cards and end screens, personalised advertising and several other features.
Design the episode so it does not depend on any of them — no "comment below", no end-screen
subscribe card, no reliance on notification-driven return traffic.

## Loudness

YouTube does not publish a mandatory upload loudness; it normalises loud material on
playback. **-14 LUFS is OUR house target**, chosen so our own episodes match each other,
recorded in config as PROGRAMME_LUFS. It is not a YouTube requirement and must not be
quoted as one.

## Audio, and why it is authored rather than generated

Veo generates native audio per clip. Measured on E01's accepted footage: s01 -17.2 LUFS,
s02 -30.6, s03 -27.4 — a 13.4 LU lurch at the first cut, in footage a human had already
accepted, because every QC probe we had ever written looks and none of them listened.

Normalising three independently invented room tones only makes three different rooms
equally loud. So the provider's audio is stripped at assemble and the programme carries one
continuous authored bed, composed offline from the mode's chord in the bible. It is
ORIGINAL — no third-party rights, no claim, no licence to track — which matters for a
channel whose entire defence is that it is original work.
