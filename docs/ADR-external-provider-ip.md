# ADR: protected channel IP does not leave without a rights check

Decided 2026-08-19 jointly, immediately after nearly losing the mascot.

## Rule

    PROTECTED CHANNEL IP — canonical assets AND DERIVATIVES — may enter an external
    provider only after ALL FIVE are explicitly checked:

        1. input privacy          is what we send retained, and visible to whom
        2. output ownership       do we own what comes back
        3. commercial use         may we monetise it
        4. publication/retention  is it published; can it be deleted
        5. training use           is our asset used to train their model

    Generic disposable evaluation assets are outside this boundary by design.

## The near-miss that forced it

Coco's canonical portrait was uploaded to Tripo and the Generate button was one click
away, costing 55 of 200 free credits. Pavan asked whether any free software did the same
job. Checking that question surfaced Tripo's free-tier terms:

    commercial use   PROHIBITED
    models           made PUBLIC automatically
    licence          CC BY 4.0, attribution required
    monetising       violates ToS AND invalidates IP claims

The channel's central mascot would have been published under CC BY, on the tier where
doing so voids our own IP claim, in exchange for a test we could run elsewhere for
nothing. Neither Claude nor GPT checked the licence before designing a production gate
around the tool.

Same failure class as assuming a parameter works because the SDK accepts it: a capability
was assumed without reading its terms.

## Why derivatives are inside the boundary

The first proposed workaround was to upload the REJECTED russet turnaround as a
crash-test dummy, on the grounds that it is explicitly not canon. GPT blocked it:
rejection does not erase lineage. A red shirt, a star emblem and preschool teddy
proportions remain unnecessarily close to channel IP.

"Technically it was not canonical" is precisely the loophole this clause closes.

## The experimental-design reason, which is stronger than the IP one

Using a Coco derivative would also have CONTAMINATED the gate. A poor result and we could
not tell whether the reconstructor failed or the rejected turnaround carried inconsistent
geometry. A good result and we would have learned that reconstruction works on a Coco
derivative, when the question was whether it works on this CLASS of stylised character.

A clean-room dummy answers the question that was actually asked.

## Consequence

Gate 1 runs on an unrelated disposable character — a green shelled turtle in a plain
yellow hoodie, deliberately unlike Coco, Pip and Nana in silhouette and palette, carrying
ONE asymmetric marker on a single side of the shell.

That marker is the sharpest instrument in the test: a reconstructor that has invented
bilateral symmetry will duplicate it onto both sides or mirror it to the wrong one. That
is a binary tell, unlike "the face looks a bit off".
