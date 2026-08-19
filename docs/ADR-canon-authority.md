# ADR: canon constrains generation; generation never redefines canon

Decided 2026-08-19 jointly. GPT's formulation, adopted as a permanent rule.

## Rule

    canon -> constrains generation          ALWAYS
    generation -> redefines canon           NEVER

A downstream artifact may not become upstream truth because it happened to render
attractively.

## The case that forced it

A turnaround generated from Coco's canonical portrait came back as a DIFFERENT BEAR:

    fur      light honey, smooth        ->  darker russet, heavy texture
    muzzle   small cream, closed smile  ->  larger, open smile, teeth visible
    star     small                      ->  large
    head     round, smooth, big cranium ->  shaggier, heavier brow

The russet bear is arguably the better-looking render. That is exactly why the rule is
needed: it was a failed derivative, and adopting it would have let a generation we did
not choose redefine the character in the only footage a human has approved.

CANON IS THE HONEY BEAR. out/portraits/coco.png and the accepted E01 footage. The russet
turnaround is permanently rejected and is not eligible to become canon by any route.

## Why this is the same defect we found all day

Every failure today had this shape — a downstream artifact trying to become upstream
truth:

    s04 rebuilt the room's object forms and would have become the room
    plate attempt 001 invented a round rug and would have become the rug
    the promoted plate cropped the bookshelf and became weak authority for it
    the russet turnaround would have become Coco

The fix is always the same: name what is authoritative, and make everything downstream
prove it matches rather than quietly replacing it.

## Consequence

Any artifact derived from a canonical asset must pass an identity comparison against that
asset BEFORE it is used as input to anything else. A turnaround goes nowhere near Tripo
until it has been compared to the canonical portrait and judged the same character.
