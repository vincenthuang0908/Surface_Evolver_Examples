"""Convert a closed triangular solder mesh to a separate STEP assembly solid.

The new FE generator exports all contact faces, so no guessing/capping is
needed. Legacy open liquid-air meshes are explicitly rejected. The assembly
is not fused, smoothed, remeshed, or boolean-modified.
"""
from __future__ import annotations
import argparse
from collections import Counter
import os
from pathlib import Path
import time
import numpy as np
from scipy.spatial import cKDTree
from ..cad import bounds, cq_module, load_shape, solid_signature
from ..common import (ComponentError, cli_entry, config_arg, integer, load_config,
                      logger_or_default, positive, read_json, require_file, result, section, sha256, write_json)
from ..mesh import read_off, require_valid_mesh, rigid_transform, write_off


def mesh_to_solid(vertices, faces, sewing_tolerance_mm=1e-7, check_self_intersections=True):
    cq = cq_module()
    from OCP.BRepBuilderAPI import BRepBuilderAPI_Sewing
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Check
    require_valid_mesh(vertices, faces, closed=True)
    sewer = BRepBuilderAPI_Sewing(sewing_tolerance_mm)
    for triangle in faces:
        wire = cq.Wire.makePolygon([cq.Vector(*map(float, vertices[i])) for i in triangle], close=True)
        face = cq.Face.makeFromWires(wire)
        sewer.Add(face.wrapped)
    sewer.Perform()
    sewed = cq.Shape.cast(sewer.SewedShape())
    shells = sewed.Shells()
    if len(shells) != 1 or not shells[0].Closed():
        raise ComponentError("Sewing did not produce exactly one closed shell")
    solid = cq.Solid.makeSolid(shells[0])
    if not solid.isValid() or solid.Volume() <= 0:
        raise ComponentError("Reconstructed solder solid is invalid or inward oriented")
    if check_self_intersections and not BRepAlgoAPI_Check(solid.wrapped, True, True).IsValid():
        raise ComponentError("OCCT detected self-interference or small-edge invalidity in the solder solid")
    return solid


def verify_faceted_geometry(solid, vertices, faces, tolerance) -> dict:
    """Same triangle connectivity + vertex displacement bounds every facet.

Unlike centroid-only distance sampling, this establishes a pointwise bound for
corresponding flat triangles by their barycentric vertex correspondence.
"""
    tree = cKDTree(np.asarray(vertices))
    original = Counter(tuple(sorted(map(int, tri))) for tri in faces)
    actual = Counter(); maximum = 0.0
    for face in solid.Faces():
        p = np.array([vertex.toTuple() for vertex in face.Vertices()])
        if len(p) != 3 or face.geomType() != "PLANE":
            raise ComponentError("STEP reconstruction changed the faceted triangle representation")
        distances, ids = tree.query(p)
        maximum = max(maximum, float(distances.max()))
        actual[tuple(sorted(map(int, ids)))] += 1
    if actual != original or maximum > tolerance:
        raise ComponentError(f"Reconstructed geometry differs from the input mesh (max vertex deviation {maximum:g} mm)")
    return {"same_triangle_connectivity": True, "maximum_vertex_deviation_mm": maximum,
            "surface_deviation_bound_mm": maximum, "method": "Barycentric bound from corresponding planar-triangle vertices"}


def match_original_solids(original_signatures, reopened_solids, tolerance=1e-6):
    signatures = [solid_signature(s) for s in reopened_solids]
    unmatched = set(range(len(signatures)))
    for expected in original_signatures:
        matched = None
        for i in sorted(unmatched):
            actual = signatures[i]
            if (np.allclose(expected["bounds_mm"], actual["bounds_mm"], atol=tolerance, rtol=0)
                and np.allclose(expected["center_mm"], actual["center_mm"], atol=tolerance, rtol=0)
                and np.isclose(expected["volume_mm3"], actual["volume_mm3"], atol=1e-7, rtol=1e-6)
                and expected["face_count"] == actual["face_count"]):
                matched = i; break
        if matched is None:
            raise ComponentError("An original solid's position, volume, bounds, or face count changed after STEP export")
        unmatched.remove(matched)
    if len(unmatched) != 1:
        raise ComponentError("Expected exactly one extra solder solid after matching every original solid")
    return reopened_solids[unmatched.pop()]


def convert_cad(solder_mesh_path, original_step_path, geometry_path, config, output_path, logger=None) -> dict:
    log = logger_or_default(logger, "cad_converter"); settings = section(config, "cad_converter")
    mesh_path = require_file(solder_mesh_path, "solder OFF mesh")
    original_path = require_file(original_step_path, "original STEP")
    geometry_file = require_file(geometry_path, "geometry JSON")
    output = Path(output_path).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    report_path = output.parent / "conversion_report.json"
    if output.exists() or output == original_path:
        raise ComponentError("Refusing to overwrite an existing STEP or the original input; choose a fresh output path")
    start = time.perf_counter()
    report = {"schema_version": 1, "component": "cad_converter", "status": "running", "outputs": {}}
    write_json(report_path, report)
    try:
        if not settings.get("preserve_original_geometry", True):
            raise ComponentError("Only non-destructive, separate-solid conversion is implemented")
        tolerance = positive(settings.get("mesh_tolerance_mm", 0.01), "mesh_tolerance_mm")
        sewing_tol = positive(settings.get("sewing_tolerance_mm", 1e-7), "sewing_tolerance_mm")
        if sewing_tol > tolerance:
            raise ComponentError("sewing_tolerance_mm must not exceed mesh_tolerance_mm")
        geometry = read_json(geometry_file)
        if geometry.get("units") != "mm":
            raise ComponentError("Converter requires geometry units=mm")
        expected_source_hash = geometry.get("source", {}).get("sha256")
        if expected_source_hash and expected_source_hash != sha256(original_path):
            raise ComponentError("Original STEP differs from the file used by the CAD extractor")
        v, f = read_off(mesh_path)
        maximum_faces = integer(settings.get("maximum_faces", 20000), "maximum_faces", 4, 1000000)
        if len(f) > maximum_faces:
            raise ComponentError(f"Mesh has {len(f)} faces, exceeding the configured {maximum_faces}; reduce refinement or deliberately increase the limit")
        mesh_info = require_valid_mesh(v, f, closed=True)
        world = rigid_transform(v, geometry["coordinate_system"]["local_to_world"])
        log.info("Reconstructing %d triangular CAD faces", len(f))
        check_si = settings.get("check_self_intersections", True)
        solder = mesh_to_solid(world, f, sewing_tol, check_si)
        geometric_check = verify_faceted_geometry(solder, world, f, tolerance)
        if not np.isclose(solder.Volume(), mesh_info["signed_volume_mm3"], rtol=1e-6, atol=1e-9):
            raise ComponentError("Reconstructed solid volume differs from mesh volume")
        cq = cq_module()
        if not hasattr(cq.Assembly, "importStep"):
            raise ComponentError("Assembly-preserving STEP import needs CadQuery 2.8 or newer")
        assembly = cq.Assembly.importStep(str(original_path))
        log.info("Original assembly imported")
        originals = assembly.toCompound().Solids()
        signatures = [solid_signature(s) for s in originals]
        log.info("Recorded %d original solid signatures", len(signatures))
        if geometry.get("source", {}).get("solid_count") not in {None, len(originals)}:
            raise ComponentError("Original assembly solid count differs from extractor metadata")
        # Check only original solids with intersecting bounding boxes, not all
        # 420 solids in the provided assembly. Original shapes are never altered.
        overlaps = []; sb = np.array(bounds(solder))
        if settings.get("check_original_interference", True):
            overlap_tolerance = positive(settings.get("overlap_volume_tolerance_mm3", 1e-7), "overlap_volume_tolerance_mm3")
            for i, (shape, sig) in enumerate(zip(originals, signatures)):
                bb = np.array(sig["bounds_mm"])
                if np.all(sb[:3] < bb[3:] - 1e-8) and np.all(bb[:3] < sb[3:] - 1e-8):
                    common = shape.intersect(solder)
                    volume = abs(common.Volume()) if common.Solids() else 0.0
                    overlaps.append({"original_solid_index": i, "volume_mm3": volume})
                    if volume > overlap_tolerance:
                        raise ComponentError(f"Solder penetrates original solid {i} by {volume:.6g} mm^3")
        name = "simulated_solder_pin_" + str(geometry.get("selection", {}).get("pin_index", 1)).zfill(3)
        if name in assembly.objects:
            raise ComponentError(f"Assembly already contains an object named {name}")
        assembly.add(solder, name=name)
        temporary = output.with_name(output.stem + ".partial.step")
        assembly.export(str(temporary), exportType="STEP", mode="default")
        log.info("Reopening STEP and checking original-solid preservation")
        reopened = load_shape(temporary); reopened_solids = reopened.Solids()
        log.info("Reopened %d solids", len(reopened_solids))
        if len(reopened_solids) != len(originals)+1:
            raise ComponentError("Exported STEP does not contain exactly the originals plus one solder solid")
        preserved_solder = match_original_solids(signatures, reopened_solids,
                              positive(settings.get("preservation_tolerance_mm", 1e-6), "preservation_tolerance_mm"))
        reopened_check = verify_faceted_geometry(preserved_solder, world, f, tolerance)
        if not preserved_solder.isValid():
            raise ComponentError("Solder solid became invalid after STEP round-trip")
        os.replace(temporary, output)
        solder_path = output.parent / "solder_only.step"
        cq.exporters.export(solder, str(solder_path))
        world_mesh = write_off(output.parent / "solder_world.off", world, f)
        report = result("cad_converter", {"combined_step": output, "solder_step": solder_path, "world_mesh": world_mesh},
            source_sha256=sha256(original_path), mesh_sha256=sha256(mesh_path), output_sha256=sha256(output),
            original_solid_count=len(originals), output_solid_count=len(reopened_solids),
            original_geometry_preserved=True, preservation_check="Every original solid matched by volume, center, bounds and face count; no boolean operations modify originals",
            assembly_structure_policy="Imported XCAF assembly tree retained; solder added as a separate named child",
            mesh_validation=mesh_info, solder_volume_mm3=float(solder.Volume()),
            geometric_check=geometric_check, reopened_geometric_check=reopened_check,
            self_intersections_checked=check_si, original_interference_checks=overlaps,
            original_interference_checked=settings.get("check_original_interference", True),
            step_reopened=True, smoothing_performed=False,
            local_to_world=geometry["coordinate_system"]["local_to_world"])
        return report
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        if isinstance(exc, ComponentError): raise
        raise ComponentError(f"CAD conversion failed: {exc}") from exc
    finally:
        report["duration_seconds"] = time.perf_counter()-start
        write_json(report_path, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__); config_arg(parser)
    parser.add_argument("--mesh", required=True, type=Path)
    parser.add_argument("--original-step", required=True, type=Path)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    return convert_cad(args.mesh, args.original_step, args.geometry, load_config(args.config), args.output)

if __name__ == "__main__":
    cli_entry(main)
