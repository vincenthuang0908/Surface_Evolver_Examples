"""Optional bounded parameter-grid calibration using the experiment manager.

Requires user-supplied measurement data. Writes a best-candidate config without
editing pipeline.json. A numerical fit is not a physical-validation claim.
"""
from __future__ import annotations
import argparse
import copy
import itertools
from pathlib import Path
import shutil
from ..common import (ComponentError, cli_entry, integer, load_config, read_json, require_file,
                      resolve_path, sha256, utc_now, write_json)
from .evaluation import compare_measurements, validate_measurements
from .experiment_manager import ARTIFACTS, code_fingerprints, requested_stages, run_pipeline
from .material_manager import DEFAULTS, MATERIAL_PROPERTIES, normalize_materials

FIT_PARAMETERS = {
    "steps.material_manager.material.pin_contact_angle_deg": ("Pin Young contact angle (°)", "pin_contact_angle_deg"),
    "steps.material_manager.material.surface_tension_N_per_m": ("Liquid–air surface tension (N/m)", "surface_tension_N_per_m"),
    "steps.material_manager.material.density_kg_per_m3": ("Liquid density (kg/m³)", "density_kg_per_m3"),
    "steps.material_manager.simulation.fillet_volume_mm3": ("Top-fillet volume (mm³)", "fillet_volume_mm3"),
    "steps.material_manager.simulation.gravity_m_per_s2": ("Downward gravity (m/s²)", "gravity_m_per_s2"),
}
_FE_PARAMETERS = {"radial_segments", "segments_per_pin_side", "boundary_chord_tolerance_mm", "initial_perturbation_mm"}


def _set_existing(config, dotted, value):
    parts = dotted.split("."); node = config
    permitted = (
        len(parts) == 4 and parts[:2] == ["steps", "material_manager"] and (
            (parts[2] == "material" and parts[3] in MATERIAL_PROPERTIES)
            or (parts[2] == "simulation" and parts[3] in DEFAULTS["simulation"])
        )
    ) or (len(parts) == 3 and parts[:2] == ["steps", "fe_generator"] and parts[2] in _FE_PARAMETERS)
    if not permitted:
        raise ComponentError("Calibration may vary only explicit material_manager or fe_generator parameters")
    try:
        for key in parts[:-1]: node = node[key]
        if parts[-1] not in node: raise KeyError(parts[-1])
        node[parts[-1]] = value
    except (KeyError, TypeError) as exc:
        raise ComponentError(f"Unknown calibration parameter: {dotted}") from exc


def _mark_provenance(config, paths, study, *, fitted=False):
    for dotted in paths:
        if dotted.startswith("steps.material_manager."):
            _, _, section, key = dotted.split(".")
            config["steps"]["material_manager"][section].setdefault("provenance", {})[key] = {
                "basis": "calibrated_effective" if fitted else "assumed",
                "source": str(study / "calibration_report.json") if fitted else f"Trial value in {study.name}",
            }


def calibrate(config_path, grid_path, measurements_path, output_dir):
    source = require_file(config_path); base = load_config(source)
    grid = read_json(grid_path); measurements = validate_measurements(read_json(measurements_path))
    choices = grid.get("parameters", {})
    if not isinstance(choices, dict) or not choices or any(not isinstance(values,list) or not values for values in choices.values()):
        raise ComponentError("Calibration parameters must be nonempty lists of candidate values")
    choices = dict(sorted(choices.items()))
    total = 1
    for values in choices.values(): total *= len(values)
    limit = integer(grid.get("maximum_runs", 16), "maximum_runs", 1, 1000)
    if total > limit: raise ComponentError(f"Grid has {total} candidates, exceeding maximum_runs={limit}")
    require_cad = grid.get("require_cad_validation", True)
    if not isinstance(require_cad, bool):
        raise ComponentError("require_cad_validation must be a boolean")
    stages = requested_stages(base)
    required = {"fe_generator", "surface_evolver"}
    if require_cad:
        required.add("cad_converter")
    if any(key.startswith("steps.material_manager.") for key in choices):
        required.add("material_manager")
    if missing := required - set(stages):
        raise ComponentError(f"Calibration requires enabled stages: {', '.join(sorted(missing))}")
    for key, values in choices.items():
        _set_existing(copy.deepcopy(base), key, values[0])
    out = Path(output_dir).resolve()
    if out.exists() and any(out.iterdir()): raise ComponentError("Use an empty calibration output directory")
    out.mkdir(parents=True, exist_ok=True); (out/"configs").mkdir()
    inputs = out/"inputs"
    inputs.mkdir()
    for key,value in base.setdefault("inputs", {}).items():
        if key in {"model_dependencies", "measurements_file"}:
            continue
        file = require_file(resolve_path(value, source.parent), key)
        snapshot = inputs / Path(ARTIFACTS[key]).name
        shutil.copy2(file, snapshot)
        base["inputs"][key] = str(snapshot)
    measurement_snapshot = write_json(inputs/"measurements.json", measurements)
    base["inputs"]["measurements_file"] = str(measurement_snapshot)
    settings = base.setdefault("steps", {})
    executable = settings.setdefault("surface_evolver", {}).get("executable")
    if isinstance(executable, str) and ("/" in executable or "\\" in executable):
        settings["surface_evolver"]["executable"] = str(resolve_path(executable, source.parent))
    settings.setdefault("evaluation", {})["require_measurement_agreement"] = False
    base["experiments_dir"] = str(out/"experiments")
    write_json(out/"base_pipeline.json", base)
    write_json(out/"grid.json", grid)
    report = {"schema_version": 1, "status": "running", "candidates": [], "best": None,
              "started_at": utc_now(), "total_candidates": total, "require_cad_validation": require_cad,
              "input_sha256": {file.name: sha256(file) for file in inputs.iterdir()},
              "code_sha256": code_fingerprints(), "physical_validation": False,
              "method": "Exhaustive bounded grid search; no claim of a global optimum outside this grid"}
    path = out/"calibration_report.json"
    write_json(path, report)
    for index, combination in enumerate(itertools.product(*choices.values()),1):
        config = copy.deepcopy(base); selected = dict(zip(choices,combination))
        for key,value in selected.items(): _set_existing(config,key,value)
        _mark_provenance(config, selected, out)
        row = {"candidate": index, "parameters": selected}
        try:
            if "material_manager" in stages:
                normalize_materials(config)
            candidate_config = write_json(out/"configs"/f"candidate_{index:03d}.json", config)
            execution = run_pipeline(candidate_config, experiment_id=f"candidate_{index:03d}")
            run = Path(execution["experiment_dir"])
            row.update(experiment_dir=str(run), execution_status=execution["status"])
            if execution["status"] != "completed":
                raise ComponentError(execution.get("error", "Candidate pipeline failed"))
            metrics = read_json(run/"simulation/metrics.json")
            if not metrics.get("numerical_pass"): raise ComponentError("Numerical gate failed; candidate excluded")
            if require_cad and execution["components"].get("cad_converter", {}).get("status") != "success":
                raise ComponentError("CAD validation failed; candidate excluded")
            agreement = compare_measurements(metrics, measurements)
            row.update(eligible=True, score=agreement["mean_normalized_squared_error"],
                       measurement_agreement=agreement["status"], comparison=agreement)
            if report["best"] is None or row["score"] < report["best"]["score"]:
                _mark_provenance(config, selected, out, fitted=True)
                write_json(out/"best_pipeline.json", config)
                report["best"] = dict(row)
        except (ComponentError, KeyError, ValueError) as exc:
            row.update(eligible=False, reason=str(exc))
        report["candidates"].append(row)
        write_json(path, report)
    report.update(status="success" if report["best"] else "failed", ended_at=utc_now())
    write_json(path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--grid", required=True, type=Path)
    parser.add_argument("--measurements", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    args = parser.parse_args()
    return calibrate(args.config, args.grid, args.measurements, args.output_dir)

if __name__ == "__main__":
    cli_entry(main)
