"""Build a base mesh from measured silhouettes, and say exactly what it is not.

Run headless:

    blender -b -P blender/mesh.py -- --character coco --out out/gate1c

WHAT THIS IS. A solid lofted from the front and side width profiles: at each height, the
front view gives the width across, the side view gives the depth through, and those two
numbers become one elliptical cross-section. Stack the sections and skin them. The result
matches both approved silhouettes at every height it was given, because it is built from
them rather than judged against them afterwards.

WHAT THIS IS NOT, and the report repeats it so nobody has to remember this docstring:

    IT IS NOT CHARACTER ART. It is a proportion-correct volume. No face, no ears as
    separate forms, no fingers, no costume. Those are modelled by a person, on top of this.

    IT IS CONVEX PER SLICE. A cross-section is one ellipse, so wherever the silhouette is
    disconnected — the gap between two legs, an arm held clear of the body — the loft
    fills the gap with geometry nobody drew. The measurement records every separate run
    per band precisely so this file can COUNT that and report it, instead of producing a
    confident blob.

    IT IS AN ELLIPSE, NOT THE OUTLINE. Two extents cannot describe a cross-section that is
    square, teardrop or kidney-shaped. Front and side are the only two views a turnaround
    guarantees, so two is what this uses.

WHY BUILD IT AT ALL. Because nothing existed, and "nothing" cannot be judged, corrected or
rigged. This turns an argument about proportions into an object somebody can look at and
reject. Every number in it is measured; none is invented; and the places where the method
is lying are printed with the height they occur at.
"""
import json
import math
import os
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

ROOT = Path(bpy.path.abspath("//")) if bpy.data.filepath else Path.cwd()
DESIGN = ROOT / "assets" / "design"
SEGMENTS = 32          # vertices around each ring; 32 is smooth without being unreadable

sys.path.insert(0, str(ROOT / "blender"))
import scaffold        # noqa: E402  — reuse the frozen angles, lighting and camera


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--character" not in argv:
        raise SystemExit("  --character is required; there is no default character")
    character = argv[argv.index("--character") + 1]
    out = argv[argv.index("--out") + 1] if "--out" in argv else "out/gate1c"
    out = (ROOT / out).resolve() if not os.path.isabs(out) else Path(out)
    return character, out


def load_measurement(character):
    path = DESIGN / character / "measurement.json"
    if not path.exists():
        raise SystemExit(f"  no measurement for {character!r}: {path}. Run "
                         f"assets/design/measure.py first — this file measures nothing "
                         f"itself, on purpose")
    data = json.loads(path.read_text(encoding="utf-8"))
    for view in ("front", "side"):
        if view not in data["views"]:
            raise SystemExit(f"  the {view} view is required to loft a cross-section and "
                             f"{character!r} does not have one")
    return data


def components(measurement):
    """Follow every separate RUN up the figure, so parts stay parts.

    Lofting the outer extent produced a chess piece: correct in silhouette, and a lie as a
    volume, because two ears became a bulge and two legs became a skirt. The measurement
    already records each separate run per band; this walks them bottom to top and links a
    run to the component it overlaps, so a shape that is drawn as three parts is built as
    three parts.

    ONE ASSUMPTION, AND IT IS THE ONLY INVENTED RULE IN THIS FILE. A turnaround gives depth
    for a whole band, not per part. The widest run in a band takes the band's measured
    depth; a narrower run is built circular in section, because a limb or an ear is roughly
    as deep as it is wide. It is stated in the report as an assumption rather than buried
    as a constant.
    """
    front = measurement["views"]["front"]["bands"]
    side = measurement["views"]["side"]["bands"]
    height_m = float(measurement["standing_height_m"])
    side_by_fraction = {round(b["height_fraction"], 4): b for b in side}

    live, finished, splits, merges, assumed = [], [], 0, 0, 0
    for band in sorted(front, key=lambda b: b["height_fraction"]):
        frac = round(band["height_fraction"], 4)
        other = side_by_fraction.get(frac)
        if other is None or not band.get("runs_m"):
            continue
        band_depth = float(other["width_m"]) / 2.0
        # The side view's centre offset is where the DEPTH sits, not merely how much of it
        # there is. Dropping it flattens a snout back into the skull and loses every
        # forward lean in the figure - the first component build did exactly that and
        # rendered a tower in profile.
        band_depth_centre = float(other.get("centre_offset_m") or 0.0)
        widest = max(band["runs_m"], key=lambda r: r[1] - r[0])

        sections = []
        for run in band["runs_m"]:
            x0, x1 = float(run[0]), float(run[1])
            rx = (x1 - x0) / 2.0
            if rx <= 0:
                continue
            if run is widest:
                ry = band_depth
            else:
                ry = rx                      # the stated assumption, counted below
                assumed += 1
            sections.append({"z": frac * height_m, "cx": (x0 + x1) / 2.0,
                             "cy": band_depth_centre,
                             "rx": rx, "ry": ry, "fraction": frac, "x0": x0, "x1": x1})

        claimed, next_live = [None] * len(sections), []
        for index, section in enumerate(sections):
            overlapping = [c for c in live
                           if not (section["x1"] < c[-1]["x0"] or section["x0"] > c[-1]["x1"])]
            if len(overlapping) == 1:
                overlapping[0].append(section)
                claimed[index] = overlapping[0]
            elif len(overlapping) > 1:
                # Two parts meeting: end both honestly and start one where they join.
                merges += 1
                for chain in overlapping:
                    finished.append(chain)
                claimed[index] = [section]
            else:
                claimed[index] = [section]
        for chain in live:
            taken = [c for c in claimed if c is chain]
            if not taken:
                finished.append(chain)       # this part ended at this height
            elif len(taken) > 1:
                splits += 1
        seen = []
        for chain in claimed:
            if chain is not None and not any(chain is s for s in seen):
                seen.append(chain)
        next_live = seen
        live = next_live
    finished.extend(live)

    usable = [chain for chain in finished if len(chain) >= 3]
    dropped = len(finished) - len(usable)
    return usable, {"components": len(usable), "dropped_short_components": dropped,
                    "splits": splits, "merges": merges,
                    "circular_sections_assumed": assumed}


def build(chains, name):
    """Skin every component into one object, each as its own closed tube."""
    verts, faces = [], []
    for chain in chains:
        chain = sorted(chain, key=lambda s: s["z"])
        first = len(verts)
        for section in chain:
            for i in range(SEGMENTS):
                angle = 2.0 * math.pi * i / SEGMENTS
                verts.append((section["cx"] + section["rx"] * math.cos(angle),
                              section["cy"] + section["ry"] * math.sin(angle),
                              section["z"]))
        for ring in range(len(chain) - 1):
            base, nxt = first + ring * SEGMENTS, first + (ring + 1) * SEGMENTS
            for i in range(SEGMENTS):
                j = (i + 1) % SEGMENTS
                faces.append((base + i, base + j, nxt + j, nxt + i))
        bottom = len(verts)
        verts.append((chain[0]["cx"], chain[0]["cy"], chain[0]["z"]))
        faces.extend((first + i, first + (i + 1) % SEGMENTS, bottom)
                     for i in range(SEGMENTS))
        top_ring = first + (len(chain) - 1) * SEGMENTS
        top = len(verts)
        verts.append((chain[-1]["cx"], chain[-1]["cy"], chain[-1]["z"]))
        faces.extend((top, top_ring + (i + 1) % SEGMENTS, top_ring + i)
                     for i in range(SEGMENTS))

    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(verts, [], faces)
    mesh.validate()
    for polygon in mesh.polygons:
        polygon.use_smooth = True
    obj = bpy.data.objects.new(name, mesh)
    bpy.context.collection.objects.link(obj)

    # WINDING IS NOT COSMETIC. from_pydata trusts the order it is handed, and a ring
    # skinned the wrong way round gives every face an inward normal. The mesh is then
    # correct in every measurable respect and renders as a black cut-out.
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()
    return obj, len(verts), len(faces)


def light_for_form(height_m):
    """A turntable rig for judging a SOLID, which is not the rig for judging references.

    scaffold.lighting exists to make emissive reference planes readable and is deliberately
    dim. Pointed at an actual surface it renders a black cut-out, which is exactly what the
    first attempt produced. Same three-point idea, energies chosen for a lit object.
    """
    d = max(0.3, height_m)
    specs = [("key", (2.2 * d, -2.6 * d, 2.6 * d), 220.0, 2.0 * d),
             ("fill", (-2.8 * d, -1.6 * d, 1.2 * d), 70.0, 2.6 * d),
             ("rim", (0.0, 3.0 * d, 2.4 * d), 130.0, 1.8 * d)]
    for name, loc, power, size in specs:
        data = bpy.data.lights.new(name, type="AREA")
        data.energy, data.size = power, size
        data.color = (1.0, 0.96, 0.90) if name == "key" else (0.90, 0.94, 1.0)
        obj = bpy.data.objects.new(name, data)
        obj.location = loc
        # AIMED WITH to_track_quat, NOT WITH HAND-ROLLED EULERS. A light that is merely
        # pointing somewhere else still renders - it renders an unlit object, which looks
        # exactly like a material problem, an engine problem or a normals problem. Blender
        # will compute the rotation that puts -Z on the target; there is no reason to do
        # that arithmetic by hand and several hours of reason not to.
        target = Vector((0.0, 0.0, 0.55 * height_m))
        obj.rotation_euler = (target - Vector(loc)).to_track_quat("-Z", "Y").to_euler()
        bpy.context.collection.objects.link(obj)

    world = bpy.data.worlds.new("form_world")
    world.use_nodes = True
    world.node_tree.nodes["Background"].inputs[0].default_value = (0.16, 0.18, 0.22, 1.0)
    world.node_tree.nodes["Background"].inputs[1].default_value = 0.8
    bpy.context.scene.world = world


def clay(obj):
    """A matte clay material, so FORM is visible rather than outline.

    This changes no geometry and is not cosmetic vanity: default grey on a pale world
    renders as a flat silhouette, and a silhouette is the one thing this mesh is already
    guaranteed to get right. Judging whether the VOLUME is any good needs shading.
    """
    material = bpy.data.materials.new("clay")
    material.use_nodes = True
    bsdf = material.node_tree.nodes["Principled BSDF"]
    bsdf.inputs["Base Color"].default_value = (0.72, 0.60, 0.50, 1.0)
    if "Roughness" in bsdf.inputs:
        bsdf.inputs["Roughness"].default_value = 0.65
    obj.data.materials.append(material)


def main():
    character, out = _args()
    out.mkdir(parents=True, exist_ok=True)
    measurement = load_measurement(character)
    height_m = float(measurement["standing_height_m"])

    scaffold.clear()
    chains, stats = components(measurement)
    if not chains:
        raise SystemExit("  no component survived; nothing to loft")
    obj, n_verts, n_faces = build(chains, f"{character}_base")

    light_for_form(height_m)
    clay(obj)
    cam = scaffold.camera()
    scaffold.render_settings()

    rendered = []
    for name, deg in {"front": 0, "right": 90, "back": 180, "left": 270}.items():
        scaffold.place_camera(cam, deg, height_m)
        bpy.context.scene.render.filepath = str(out / f"base_{name}.png")
        bpy.ops.render.render(write_still=True)
        rendered.append(f"base_{name}.png")

    blend = out / f"{character}_base.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    all_z = [s["z"] for chain in chains for s in chain]
    report = {
        "kind": "GATE_1C_BASE_MESH",
        "character": character,
        "standing_height_m": height_m,
        "segments_per_section": SEGMENTS,
        "vertices": n_verts,
        "faces": n_faces,
        "z_range_m": [round(min(all_z), 4), round(max(all_z), 4)],
        "source_measurement": f"assets/design/{character}/measurement.json",
        "topology": stats,
        "what_this_is_not": [
            "not character art: no face, no costume, no fingers, no sculpted detail",
            "each drawn part is a tube of ellipses, so a part is the right size and "
            "the wrong shape in cross-section",
            "parts that meet are built as separate overlapping tubes, not joined",
        ],
        "the_one_assumption": "a turnaround gives depth per BAND, not per part. The "
                              "widest run in a band takes the measured depth; a narrower "
                              "run is built circular in section, because a limb or an ear "
                              "is roughly as deep as it is wide.",
        "renders": rendered,
        "blend": blend.name,
    }
    (out / "mesh.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"  GATE 1-C BASE MESH - {character}")
    print(f"    {stats['components']} components, {n_verts} vertices, {n_faces} faces")
    print(f"    {stats['splits']} splits, {stats['merges']} merges, "
          f"{stats['dropped_short_components']} components too short to loft")
    print(f"    {stats['circular_sections_assumed']} sections built circular by the "
          f"stated depth assumption")
    print(f"    -> {out}")


if __name__ == "__main__":
    main()
