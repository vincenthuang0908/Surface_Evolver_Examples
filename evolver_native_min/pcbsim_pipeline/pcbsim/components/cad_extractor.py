"""Extract a selected, Z-aligned rectangular-pin through-hole connection.

Independent CLI: python -m pcbsim.components.cad_extractor --help
The hole is preserved as a void, never invented as a solid.
"""
from __future__ import annotations
import argparse
from pathlib import Path
import numpy as np
from ..cad import CadQueryBackend
from ..common import (ComponentError, cli_entry, config_arg, integer, load_config,
                      logger_or_default, positive, require_file, result, section, sha256, write_json)


def vertical_cylinders(shape, backend=None) -> list[dict]:
    backend = backend or CadQueryBackend()
    cylinders = []
    for axis_z, center, radius, box in backend.cylindrical_faces(shape):
        if abs(abs(axis_z) - 1) > 1e-7:
            continue
        cylinders.append({"center_xy_mm": list(center), "radius_mm": radius, "bounds_mm": box})
    return cylinders


def _center_xy(bb):
    return np.array([(bb[0] + bb[3]) / 2, (bb[1] + bb[4]) / 2])


def detect_connections(shape, settings: dict, *, backend=None) -> tuple[int, list[dict]]:
    backend = backend or CadQueryBackend()
    solids = backend.solids(shape)
    boxes = [backend.bounds(solid) for solid in solids]
    if "board_solid_index" in settings:
        board_index = integer(settings["board_solid_index"], "board_solid_index", 0, len(solids)-1)
    else:
        boards = [i for i, b in enumerate(boxes)
                  if b[3]-b[0] > 5 and b[4]-b[1] > 5 and 0.1 < b[5]-b[2] < min(b[3]-b[0], b[4]-b[1])/5]
        if not boards:
            raise ComponentError("No horizontal PCB slab found; v1 requires the PCB in the XY plane. Set board_solid_index for ambiguous assemblies.")
        board_index = max(boards, key=lambda i: backend.volume(solids[i]))
    board_bb = boxes[board_index]
    holes = {}
    for cylinder in vertical_cylinders(solids[board_index], backend):
        center = cylinder["center_xy_mm"]; radius = cylinder["radius_mm"]; bb = cylinder["bounds_mm"]
        if bb[2] <= board_bb[2] + 1e-5 and bb[5] >= board_bb[5] - 1e-5:
            holes[(round(center[0], 7), round(center[1], 7), round(radius, 7))] = cylinder
    if not holes:
        raise ComponentError("No Z-aligned cylindrical through-holes found in the selected PCB")
    tolerance = positive(settings.get("matching_tolerance_mm", 0.02), "matching_tolerance_mm")
    connections = []
    for (cx, cy, drill_r), hole in holes.items():
        center = np.array([cx, cy]); pins = []; pads = []
        for i, bb in enumerate(boxes):
            if i == board_index or np.linalg.norm(_center_xy(bb) - center) > tolerance:
                continue
            dx, dy, dz = np.array(bb[3:]) - np.array(bb[:3])
            spans_board = bb[2] < board_bb[2] and bb[5] > board_bb[5]
            if not spans_board:
                continue
            if max(dx, dy) < drill_r*2 and dz > 2*max(dx, dy):
                pins.append(i)
            elif drill_r*2 < max(dx, dy) < settings.get("maximum_pad_diameter_mm", 4.0):
                pads.append(i)
        if not pins:
            continue  # mounting holes, not header connections
        if len(pins) != 1 or len(pads) != 1:
            raise ComponentError(f"Ambiguous pin/pad at ({cx}, {cy}): pins={pins}, pads={pads}")
        pin_i, pad_i = pins[0], pads[0]
        pin, pad = solids[pin_i], solids[pad_i]
        pb, ab = boxes[pin_i], boxes[pad_i]
        pin_center = _center_xy(pb)
        pin_w, pin_h = pb[3]-pb[0], pb[4]-pb[1]
        # Four long axis-aligned planar walls must exist; chamfered ends are allowed.
        side_faces = []
        normals = set()
        for n, face_bounds in backend.planar_faces(pin):
            if abs(n[2]) < 1e-7 and (abs(abs(n[0])-1) < 1e-7 or abs(abs(n[1])-1) < 1e-7):
                side_faces.append(face_bounds); normals.add(tuple(round(x) for x in n))
        if len(normals) != 4:
            raise ComponentError(f"Pin solid {pin_i} is not an axis-aligned rectangular pin; no circular approximation is made")
        straight_low = max(b[2] for b in side_faces)
        straight_high = min(b[5] for b in side_faces)
        cylindrical_pad = [c for c in vertical_cylinders(pad, backend)
                           if np.linalg.norm(np.array(c["center_xy_mm"])-center) < tolerance]
        if not cylindrical_pad:
            raise ComponentError(f"Pad solid {pad_i} has no concentric cylindrical boundary")
        pad_r = max(c["radius_mm"] for c in cylindrical_pad)
        opening = min(c["radius_mm"] for c in cylindrical_pad)
        if not opening <= drill_r + 1e-5 or not pad_r > drill_r:
            raise ComponentError("Pad/plating radii are inconsistent with the PCB drilled hole")
        # The cylindrical plated bore must cover the full pad-to-pad depth.
        bore_faces = [c for c in cylindrical_pad if abs(c["radius_mm"]-opening) < 1e-6]
        bore_low = min(c["bounds_mm"][2] for c in bore_faces)
        bore_high = max(c["bounds_mm"][5] for c in bore_faces)
        if bore_low > ab[2]+1e-5 or bore_high < ab[5]-1e-5:
            raise ComponentError("The plated bore is not constant through the pad stack; stepped holes are unsupported")
        corners = np.array([[x,y] for x in [pb[0],pb[3]] for y in [pb[1],pb[4]]])
        if np.max(np.linalg.norm(corners-center, axis=1)) >= opening:
            raise ComponentError("Pin does not fit inside the plated hole")
        connections.append({"center_xy_mm": [cx, cy], "board_solid_index": board_index,
            "pin_solid_index": pin_i, "pad_solid_index": pad_i,
            "pcb_drill_radius_mm": drill_r, "hole_radius_mm": opening,
            "pad_radius_mm": pad_r, "pad_top_z_mm": round(ab[5], 6),
            "pad_bottom_z_mm": round(ab[2], 6),
            "pin_width_mm": pin_w, "pin_depth_mm": pin_h,
            "pin_center_xy_mm": pin_center.tolist(),
            "pin_straight_z_range_mm": [straight_low, straight_high]})
    connections.sort(key=lambda row: (round(row["center_xy_mm"][0], 6), -round(row["center_xy_mm"][1], 6)))
    for i, row in enumerate(connections, 1):
        row["pin_index"] = i
    if not connections:
        raise ComponentError("No matched rectangular header pins, pads and through-holes were found")
    return board_index, connections


def extract_cad(input_step, config, output_dir, logger=None, *, list_only=False, backend=None) -> dict:
    log = logger_or_default(logger, "cad_extractor")
    settings = section(config, "cad_extractor")
    source = require_file(input_step, "original STEP")
    out = Path(output_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    log.info("Loading STEP and detecting connections: %s", source)
    backend = backend or CadQueryBackend()
    shape = backend.load(source)
    solids = backend.solids(shape)
    board_i, connections = detect_connections(shape, settings, backend=backend)
    source_hash = sha256(source)
    catalog_path = write_json(out / "connections.json", {
        "schema_version": 1, "source_sha256": source_hash, "units": "mm",
        "ordering": "1-based geometric order: increasing world X, then decreasing world Y; not electrical pin numbering",
        "original_solid_count": len(solids), "board_solid_index": board_i, "connections": connections})
    if list_only:
        return result("cad_extractor", {"connections": catalog_path}, connection_count=len(connections))
    selection = settings.get("selection", {})
    if selection.get("type", "through_hole_connection") != "through_hole_connection":
        raise ComponentError("Only selection.type=through_hole_connection is supported")
    includes = selection.get("include", ["pad", "hole", "pin", "pcb_section"])
    if set(includes) != {"pad", "hole", "pin", "pcb_section"}:
        raise ComponentError("The v1 FE contract requires pad, hole, pin and pcb_section together")
    index = integer(selection.get("pin_index", settings.get("pin_index", 1)), "selection.pin_index", 1, len(connections))
    selected = connections[index - 1]
    if settings.get("solder_side", "top") != "top":
        raise ComponentError("v1 supports the exposed top side only; bottom-side housing clearance must be modeled explicitly")
    cx, cy = selected["center_xy_mm"]; z0 = selected["pad_top_z_mm"]
    size = positive(settings.get("pcb_section_size_mm", 3.0), "pcb_section_size_mm")
    if size <= selected["pad_radius_mm"]*2:
        raise ComponentError("pcb_section_size_mm must exceed the pad diameter")
    bb = backend.bounds(solids[board_i])
    crop = backend.box((size, size, bb[5]-bb[2]+0.2), (cx-size/2, cy-size/2, bb[2]-0.1))
    pcb_section = backend.intersect(solids[board_i], crop)
    board_sections = backend.solids(pcb_section)
    if not board_sections or not backend.valid(pcb_section):
        raise ComponentError("PCB crop is empty or invalid")
    # Verify that clipping did not accidentally seal the source hole.
    probe = backend.cylinder(selected["pcb_drill_radius_mm"]*0.99, bb[5]-bb[2], (cx, cy, bb[2]))
    void_overlap = backend.volume(backend.intersect(pcb_section, probe))
    if abs(void_overlap) > 1e-7:
        raise ComponentError("Extracted PCB section no longer preserves its through-hole")
    pad, pin = solids[selected["pad_solid_index"]], solids[selected["pin_solid_index"]]
    extracted_path = out / "extracted.step"
    backend.export_step([pcb_section, pad, pin], extracted_path)
    reopened = backend.load(extracted_path)
    if len(backend.solids(reopened)) != len(board_sections) + 2:
        raise ComponentError("Extracted STEP round-trip changed the solid count")
    max_height = selected["pin_straight_z_range_mm"][1] - z0
    if max_height <= 0:
        raise ComponentError("No straight pin sidewall is exposed above the selected pad")
    transform = np.eye(4); transform[:3, 3] = [cx, cy, z0]
    geometry = {"schema_version": 1, "units": "mm", "model_family": "rectangular_pin_circular_plated_hole",
        "source": {"filename": source.name, "sha256": source_hash, "solid_count": len(solids)},
        "extracted_step_sha256": sha256(extracted_path), "selection": selected,
        "coordinate_system": {"frame": "local_pad_top", "local_to_world": transform.tolist(),
            "description": "Origin at pad/hole center on top copper; local +Z points away from board"},
        "pad": {"outer_radius_mm": selected["pad_radius_mm"], "top_z_mm": 0.0,
            "provenance": "Concentric cylindrical outer boundary of matched source pad solid"},
        "hole": {"radius_mm": selected["hole_radius_mm"], "pcb_drill_radius_mm": selected["pcb_drill_radius_mm"],
            "depth_mm": z0-selected["pad_bottom_z_mm"], "provenance": "Inner plated bore; PCB drill is separately recorded"},
        "pin": {"cross_section": "rectangle", "width_mm": selected["pin_width_mm"],
            "depth_mm": selected["pin_depth_mm"], "center_xy_mm": (np.array(selected["pin_center_xy_mm"])-[cx,cy]).tolist(),
            "max_straight_height_mm": max_height,
            "provenance": "Bounding box and four planar sidewalls; beveled tip excluded from allowable wetting height"},
        "pcb": {"thickness_mm": bb[5]-bb[2], "section_size_mm": size,
                "world_z_range_mm": [bb[2], bb[5]], "section_bounds_mm": backend.bounds(pcb_section),
                "section_volume_mm3": backend.volume(pcb_section)},
        "validation": {"hole_preserved": True, "void_overlap_mm3": float(void_overlap), "step_reopened": True},
        "original_selected_solids": {"pin": backend.signature(pin), "pad": backend.signature(pad)}}
    geometry_path = write_json(out / "geometry.json", geometry)
    report = result("cad_extractor", {"extracted_step": extracted_path, "geometry": geometry_path, "connections": catalog_path},
                    connection_count=len(connections), selected_pin_index=index)
    write_json(out / "extraction_report.json", report)
    log.info("Extracted connection %s of %s", index, len(connections))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-step", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--list-connections", action="store_true")
    config_arg(parser); args = parser.parse_args()
    return extract_cad(args.input_step, load_config(args.config), args.output_dir, list_only=args.list_connections)

if __name__ == "__main__":
    cli_entry(main)
