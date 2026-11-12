"""Generate a closed, rectangular-pin / plated-barrel Surface Evolver model.

No solver is invoked. The fully filled barrel is fixed; the top fillet is relaxed.
The outer pad contact line is pinned. The pin contact line may move on four
planar pin walls, with contact energy -cos(theta) times wetted pin area.
"""
from __future__ import annotations
import argparse
import math
from pathlib import Path
import numpy as np
from ..common import (ComponentError, cli_entry, config_arg, integer, load_config,
                      logger_or_default, positive, read_json, require_file, result, section, sha256, write_json)
from ..mesh import require_valid_mesh, signed_volume, write_off
from .._vendor.evolver_native.models import topology
from .material_manager import normalize_materials


def build_model(geometry: dict, parameters: dict, settings: dict):
    if geometry.get("units") != "mm" or geometry.get("model_family") != "rectangular_pin_circular_plated_hole":
        raise ComponentError("FE generation requires the extractor's millimeter rectangular-pin geometry contract")
    if geometry["pin"].get("cross_section") != "rectangle":
        raise ComponentError("Only rectangular pins are supported; no hidden circle substitution")
    radial = integer(settings.get("radial_segments", 5), "radial_segments", 2, 100)
    side_segments = integer(settings.get("segments_per_pin_side", 8), "segments_per_pin_side", 2, 128)
    n = 4 * side_segments
    hx = positive(geometry["pin"]["width_mm"], "pin.width_mm")/2
    hy = positive(geometry["pin"]["depth_mm"], "pin.depth_mm")/2
    px, py = map(float, geometry["pin"]["center_xy_mm"])
    if not np.isfinite([px, py]).all():
        raise ComponentError("Pin offsets must be finite")
    pad_r = positive(geometry["pad"]["outer_radius_mm"], "pad.outer_radius_mm")
    hole_r = positive(geometry["hole"]["radius_mm"], "hole.radius_mm")
    depth = positive(geometry["hole"]["depth_mm"], "hole.depth_mm")
    max_height = positive(geometry["pin"]["max_straight_height_mm"], "pin.max_straight_height_mm")
    if not hole_r < pad_r:
        raise ComponentError("Hole radius must be smaller than pad radius")
    # Equally subdivide each actual rectangle side, preserving all four corners.
    corners = np.array([[hx, -hy], [hx, hy], [-hx, hy], [-hx, -hy]], float)
    inner0 = np.array([(1-t)*corners[i]+t*corners[(i+1)%4]
                      for i in range(4) for t in np.arange(side_segments)/side_segments])
    inner = inner0 + [px, py]
    if np.linalg.norm(inner, axis=1).max() >= hole_r:
        raise ComponentError("Pin corner touches or crosses the plated bore")
    angle = np.unwrap(np.arctan2(inner0[:, 1], inner0[:, 0]))
    unit = np.column_stack([np.cos(angle), np.sin(angle)])
    delta = np.diff(np.r_[angle, angle[0]+2*np.pi])
    chord_error = pad_r * (1-math.cos(float(delta.max())/2))
    chord_tolerance = positive(settings.get("boundary_chord_tolerance_mm", 0.01), "boundary_chord_tolerance_mm")
    if chord_error > chord_tolerance:
        raise ComponentError(f"Boundary chord error {chord_error:.6g} mm exceeds {chord_tolerance}; increase segments_per_pin_side")
    points = []; constraints = []; fixed = []; rings = {}
    def wall_constraints(j):
        x, y = inner0[j]; ids = set()
        if abs(x-hx) < 1e-10: ids.add(1)
        if abs(y-hy) < 1e-10: ids.add(2)
        if abs(x+hx) < 1e-10: ids.add(3)
        if abs(y+hy) < 1e-10: ids.add(4)
        return ids
    def add_ring(name, xy, z, is_fixed, on_pin=False, above=False):
        ids = []
        for j, (x,y) in enumerate(xy):
            ids.append(len(points)); points.append([x,y,z])
            cons = wall_constraints(j) if on_pin else set()
            if above: cons |= {10,11,13}
            constraints.append(cons); fixed.append(is_fixed)
        rings[name] = ids
        return ids
    add_ring("pin_low", inner, -depth, True, on_pin=True)
    add_ring("hole_low", hole_r*unit, -depth, True)
    add_ring("hole_top", hole_r*unit, 0, True)
    add_ring("pad", pad_r*unit, 0, True, above=True)
    add_ring("pin_zero", inner, 0, True, on_pin=True, above=True)
    mobile = parameters["simulation"]["pin_contact_line"] == "mobile"
    free_rings = []
    for i, t in enumerate(np.linspace(0,1,radial+1)):
        if i == radial:
            free_rings.append(rings["pad"])
        else:
            xy = (1-t)*inner + t*pad_r*unit
            free_rings.append(add_ring(f"free_{i}", xy, 1-t, not mobile if i==0 else False,
                                       on_pin=i==0, above=True))
    faces = []; regions = []
    def connect(first, second, region, reverse=False):
        for j in range(n):
            k = (j+1)%n
            pair = [[first[j], second[j], second[k]], [first[j], second[k], first[k]]]
            for triangle in pair:
                faces.append(triangle[::-1] if reverse else triangle); regions.append(region)
    # region 1 free top; 2 wetted pin; 3 pad; 4 barrel; 5 bottom cap.
    for first, second in zip(free_rings, free_rings[1:]):
        connect(first, second, 1)
    connect(rings["pin_zero"], free_rings[0], 2)  # inward normal, lower->upper
    connect(rings["pin_low"], rings["pin_zero"], 4)
    connect(rings["hole_low"], rings["hole_top"], 4, reverse=True)
    connect(rings["hole_top"], rings["pad"], 3, reverse=True)
    connect(rings["pin_low"], rings["hole_low"], 5, reverse=True)
    v = np.array(points, float); f = np.array(faces, int)
    movable_z = v[:,2] > 0
    flat = v.copy(); flat[movable_z,2] = 0
    barrel_volume = signed_volume(flat, f)
    volume_per_height = signed_volume(v, f)-barrel_volume
    if barrel_volume <= 0 or volume_per_height <= 0:
        raise ComponentError("Generated shell has invalid orientation or volume")
    fillet_volume = positive(parameters["simulation"]["effective_fillet_volume_mm3"], "effective_fillet_volume_mm3")
    height = fillet_volume / volume_per_height
    if height >= max_height * 0.98:
        raise ComponentError(f"Initial fillet needs {height:.6g} mm pin height, but only {max_height:.6g} mm of straight pin is exposed. Reduce fillet volume; the beveled tip is not modeled.")
    v[movable_z,2] *= height
    perturbation = positive(settings.get("initial_perturbation_mm", 0), "initial_perturbation_mm", allow_zero=True)
    if perturbation:
        rng = np.random.default_rng(parameters["simulation"]["seed"])
        ids = [i for i in range(len(v)) if not fixed[i] and not (constraints[i] & {1,2,3,4})]
        v[ids,2] += rng.uniform(-perturbation, perturbation, len(ids))
        if np.any(v[ids,2] <= 0):
            raise ComponentError("Initial perturbation crosses the pad plane; reduce initial_perturbation_mm")
        current_fillet = signed_volume(v,f)-barrel_volume
        v[movable_z,2] *= fillet_volume/current_fillet
        if v[:,2].max() >= max_height*0.98:
            raise ComponentError("Initial perturbation reaches the pin bevel; reduce its amplitude")
    mesh_info = require_valid_mesh(v, f, closed=True)
    total_volume = barrel_volume + fillet_volume
    if not np.isclose(mesh_info["signed_volume_mm3"], total_volume, rtol=1e-10, atol=1e-12):
        raise ComponentError("Initial volume does not match the requested target")
    header = ["// PCBSim closed-shell rectangular-pin through-hole model.",
        "// Length: mm. Energy: gamma*(1 mm)^2. Fixed fully filled barrel.",
        "// Pinned circular pad perimeter; beveled tip and bottom meniscus excluded.",
        f"parameter volume_target = {total_volume:.17g}", f"parameter pin_half_x = {hx:.17g}",
        f"parameter pin_half_y = {hy:.17g}", f"parameter pin_cx = {px:.17g}", f"parameter pin_cy = {py:.17g}",
        f"parameter pad_radius = {pad_r:.17g}", f"parameter max_height = {max_height:.17g}",
        f"parameter theta_pin = {parameters['material']['effective_pin_contact_angle_deg']:.17g}",
        f"gravity_constant {parameters['scales']['gravity_coefficient']:.17g}",
        "define facet attribute pcbsim_region integer",
        "constraint 1", "formula: x = pin_cx + pin_half_x",
        "constraint 2", "formula: y = pin_cy + pin_half_y",
        "constraint 3", "formula: x = pin_cx - pin_half_x",
        "constraint 4", "formula: y = pin_cy - pin_half_y",
        "constraint 10 nonnegative", "formula: z",
        "constraint 11 nonpositive", "formula: x^2+y^2-pad_radius^2",
        "constraint 13 nonpositive", "formula: z-max_height"]
    edges, face_edges = topology(f)
    def attributes(ids):
        common = set.intersection(*(constraints[i] for i in ids))
        parts = ["fixed"] if all(fixed[i] for i in ids) else []
        if common: parts += ["constraints " + " ".join(map(str, sorted(common)))]
        return " ".join(parts)
    lines = header + ["", "vertices"]
    for i, vertex in enumerate(v):
        lines.append(f"{i+1} " + " ".join(f"{x:.17g}" for x in vertex) + " " + attributes([i]))
    lines += ["", "edges"]
    for i, (a,b) in enumerate(edges):
        lines.append(f"{i+1} {a+1} {b+1} {attributes([a,b])}")
    lines += ["", "faces"]
    for i, (triangle, edge_ids, region) in enumerate(zip(f, face_edges, regions)):
        tension = "1" if region==1 else ("(-cos(theta_pin*pi/180))" if region==2 else "0")
        lines.append(f"{i+1} " + " ".join(map(str, edge_ids)) + f" tension {tension} pcbsim_region {region} " + attributes(triangle))
    lines += ["", "bodies", "1 " + " ".join(str(i+1) for i in range(len(f))) + " volume volume_target density 1",
              "", "read", "target_tolerance := 1e-10", ""]
    metadata = {"schema_version": 1, "kind": "pcbsim_through_hole", "mesh_contract": "closed_shell",
        "body_id": 1, "body_volume_target": total_volume, "barrel_volume_mm3": barrel_volume,
        "analytic_barrel_volume_mm3": (math.pi*hole_r**2-4*hx*hy)*depth,
        "fillet_volume_mm3": fillet_volume, "initial_pin_contact_height_mm": height,
        "boundary_chord_error_bound_mm": chord_error,
        "seed": parameters["simulation"]["seed"], "parameters": parameters,
        "geometry": geometry, "initial_mesh": mesh_info, "has_pcbsim_region": True,
        "scope": ["One top-side fillet and one fully filled fixed barrel", "Exact rectangular pin cross-section",
                  "Circular hole and pad are inscribed polygons with the recorded chord error",
                  "No partial barrel fill, bottom meniscus, temperature field, oxidation, or solidification"],
        "contact_line_mode": parameters["simulation"]["pin_contact_line"],
        "native_syntax_checked": False, "physical_validation": False}
    return "\n".join(lines), metadata, v, f


def generate_fe(extracted_step_path, geometry_path, parameters_path, config, output_path, logger=None) -> dict:
    log = logger_or_default(logger, "fe_generator")
    extracted = require_file(extracted_step_path, "extracted STEP")
    gp = require_file(geometry_path, "geometry JSON"); pp = require_file(parameters_path, "normalized parameters")
    geometry, parameters = read_json(gp), read_json(pp)
    if geometry.get("extracted_step_sha256") != sha256(extracted):
        raise ComponentError("extracted.step does not match geometry.json; regenerate both from the same source")
    # Revalidate parameters, so editing a normalized JSON cannot bypass bounds checking.
    checked = normalize_materials({"material": parameters.get("material", {}), "simulation": parameters.get("simulation", {})})
    settings = section(config, "fe_generator")
    text, metadata, v, f = build_model(geometry, checked, settings)
    output = Path(output_path).resolve(); output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="ascii", newline="\n")
    metadata.update({"model_sha256": sha256(output), "geometry_sha256": sha256(gp), "parameters_sha256": sha256(pp),
                     "generator_settings": settings})
    meta_path = write_json(output.with_suffix(".json"), metadata)
    mesh_path = write_off(output.parent / "initial_mesh.off", v, f)
    log.info("Generated %d vertices / %d triangles; no simulation has been executed", len(v), len(f))
    return result("fe_generator", {"model": output, "model_metadata": meta_path, "initial_mesh": mesh_path},
                  native_executed=False, mesh_validation=metadata["initial_mesh"])


def main():
    parser = argparse.ArgumentParser(description=__doc__); config_arg(parser)
    parser.add_argument("--extracted-step", required=True, type=Path)
    parser.add_argument("--geometry", required=True, type=Path)
    parser.add_argument("--parameters", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    return generate_fe(args.extracted_step, args.geometry, args.parameters, load_config(args.config), args.output)

if __name__ == "__main__":
    cli_entry(main)
