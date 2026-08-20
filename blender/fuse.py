"""Fuse the base volume into one deformable surface, deterministically.

    blender -b -P blender/fuse.py -- --character coco --out out/gate1d

WHY THIS EXISTS. Gate 1-C produces separate closed tubes that intersect at their joins. It
is honest geometry and it is not a surface anything can deform: a rig binds to one
continuous mesh, and nine overlapping shells have no shared skin across a shoulder.

The obvious next step is "a person sculpts it". That was refused, correctly. A pipeline
with a human modelling stage in the middle is not a pipeline — it is a person with tooling,
and it stops the moment nobody is at the desk. So the fusion is a program.

WHAT IT DOES. A voxel remesh: the intersecting shells are sampled into one volume and a
single surface is generated from it. That is what makes overlapping tubes into one skin.
The voxel size is a fraction of the character's own height, so a taller character gets a
proportionally finer grid rather than the same absolute one.

WHAT IT COSTS, and this file measures it rather than hoping. A voxel grid rounds off
anything smaller than a voxel, so detail is lost at the scale of the grid. The output is
rendered as orthographic silhouette masks so the next stage can measure exactly how much
the shape moved away from the approved drawing — and refuse it if that is too much. Nothing
here decides that the result is good enough; it produces the evidence for deciding.
"""
import json
import math
import os
import sys
from pathlib import Path

import bmesh
import bpy

ROOT = Path(bpy.path.abspath("//")) if bpy.data.filepath else Path.cwd()
DESIGN = ROOT / "assets" / "design"

sys.path.insert(0, str(ROOT / "blender"))
import mesh as basemesh    # noqa: E402  — the base volume is built, never hand-edited
import scaffold            # noqa: E402

# Voxels across the character's full height. 180 keeps ears and limbs at several voxels
# across while staying inside a headless machine's memory. It is a resolution, not a
# quality judgement, and the silhouette error is measured afterwards either way.
VOXELS_PER_HEIGHT = 180


def _args():
    argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    if "--character" not in argv:
        raise SystemExit("  --character is required; there is no default character")
    character = argv[argv.index("--character") + 1]
    out = argv[argv.index("--out") + 1] if "--out" in argv else "out/gate1d"
    out = (ROOT / out).resolve() if not os.path.isabs(out) else Path(out)
    voxels = int(argv[argv.index("--voxels") + 1]) if "--voxels" in argv \
        else VOXELS_PER_HEIGHT
    return character, out, voxels


def fuse(obj, voxel_size):
    """One surface from many, by volume rather than by boolean.

    Booleans on self-intersecting closed tubes fail in ways that depend on the order they
    are applied in, which is exactly the kind of nondeterminism this project refuses. A
    voxel remesh has no such ordering: it samples the volume and skins it.
    """
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    modifier = obj.modifiers.new("fuse", type="REMESH")
    modifier.mode = "VOXEL"
    modifier.voxel_size = voxel_size
    modifier.use_smooth_shade = True
    bpy.ops.object.modifier_apply(modifier=modifier.name)
    return obj


def surface_facts(obj):
    bm = bmesh.new()
    bm.from_mesh(obj.data)
    non_manifold = sum(1 for edge in bm.edges if not edge.is_manifold)
    loose = sum(1 for vert in bm.verts if not vert.link_faces)
    shells, seen = 0, set()
    for face in bm.faces:
        if face.index in seen:
            continue
        shells += 1
        stack = [face]
        while stack:
            current = stack.pop()
            if current.index in seen:
                continue
            seen.add(current.index)
            for edge in current.edges:
                stack.extend(f for f in edge.link_faces if f.index not in seen)
    facts = {"vertices": len(bm.verts), "faces": len(bm.faces),
             "non_manifold_edges": non_manifold, "loose_vertices": loose,
             "separate_shells": shells}
    bm.free()
    return facts


def orthographic_masks(obj, height_m, out):
    """Render the fused surface as flat silhouettes, from the approved angles.

    Orthographic on purpose: a perspective render of a rounded form is wider at the
    camera's height than at its feet, and comparing that to a flat drawing would report a
    shape error that is really a lens.
    """
    data = bpy.data.cameras.new("ortho")
    data.type = "ORTHO"
    data.ortho_scale = height_m * 1.25
    cam = bpy.data.objects.new("ortho", data)
    bpy.context.collection.objects.link(cam)
    bpy.context.scene.camera = cam

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in \
        {i.identifier for i in
         bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items} \
        else "BLENDER_EEVEE"
    scene.render.resolution_x = scene.render.resolution_y = 1024
    scene.render.film_transparent = True          # alpha IS the silhouette
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"

    written = {}
    for name, yaw in (("front", 0.0), ("side", 90.0)):
        angle = math.radians(yaw)
        distance = height_m * 4.0
        cam.location = (math.sin(angle) * distance, -math.cos(angle) * distance,
                        height_m / 2.0)
        cam.rotation_euler = (math.radians(90.0), 0.0, angle)
        scene.render.filepath = str(out / f"mask_{name}.png")
        bpy.ops.render.render(write_still=True)
        written[name] = f"mask_{name}.png"
    return written, data.ortho_scale


def main():
    character, out, voxels = _args()
    out.mkdir(parents=True, exist_ok=True)
    measurement = basemesh.load_measurement(character)
    height_m = float(measurement["standing_height_m"])

    scaffold.clear()
    chains, stats = basemesh.components(measurement)
    obj, _, _ = basemesh.build(chains, f"{character}_fused")
    before = surface_facts(obj)

    voxel_size = height_m / voxels
    fuse(obj, voxel_size)
    after = surface_facts(obj)

    masks, ortho_scale = orthographic_masks(obj, height_m, out)
    blend = out / f"{character}_fused.blend"
    bpy.ops.wm.save_as_mainfile(filepath=str(blend))

    one_surface = after["separate_shells"] == 1
    watertight = after["non_manifold_edges"] == 0 and after["loose_vertices"] == 0
    report = {
        "kind": "GATE_1D_FUSED_SURFACE",
        "character": character,
        "standing_height_m": height_m,
        "voxels_per_height": voxels,
        "voxel_size_m": round(voxel_size, 6),
        "before_fusion": before,
        "after_fusion": after,
        "one_connected_surface": one_surface,
        "watertight": watertight,
        # Deliberately NOT true merely because the topology is clean. A surface that is
        # one manifold piece and the wrong shape is still the wrong shape, and only the
        # silhouette comparison can say. The next stage sets this.
        "rig_ready": False,
        "rig_ready_pending": "silhouette error against the approved sheets is not measured "
                             "here; run assets/design/silhouette_error.py",
        "masks": masks,
        "ortho_scale_m": round(ortho_scale, 4),
        "blend": blend.name,
        "base_volume_stats": stats,
    }
    (out / "fuse.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"  GATE 1-D FUSED SURFACE - {character}")
    print(f"    voxel {voxel_size * 1000:.2f} mm ({voxels} across the height)")
    print(f"    before  {before['separate_shells']} shells, {before['vertices']} verts")
    print(f"    after   {after['separate_shells']} shells, {after['vertices']} verts, "
          f"{after['non_manifold_edges']} non-manifold edges")
    print(f"    one connected surface: {one_surface}, watertight: {watertight}")
    print(f"    masks rendered; silhouette error is measured by the next stage")
    print(f"    -> {out}")


if __name__ == "__main__":
    main()
