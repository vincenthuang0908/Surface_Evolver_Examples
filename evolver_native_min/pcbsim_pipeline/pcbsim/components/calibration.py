"""Optional bounded parameter-grid calibration using the experiment manager.

Requires user-supplied measurement data. Writes a best-candidate config without
editing pipeline.json. A numerical fit is not a physical-validation claim.
"""
from __future__ import annotations
import argparse
import copy
import itertools
from pathlib import Path
from ..common import (ComponentError, cli_entry, integer, load_config, read_json, require_file,
                      resolve_path, write_json)
from .evaluation import compare_measurements
from .experiment_manager import run_pipeline


def _set_existing(config, dotted, value):
    parts = dotted.split("."); node = config
    if not dotted.startswith("steps.material_manager.") and not dotted.startswith("steps.fe_generator."):
        raise ComponentError("Calibration may vary only explicit material_manager or fe_generator parameters")
    try:
        for key in parts[:-1]: node = node[key]
        if parts[-1] not in node: raise KeyError(parts[-1])
        node[parts[-1]] = value
    except (KeyError, TypeError) as exc:
        raise ComponentError(f"Unknown calibration parameter: {dotted}") from exc


def calibrate(config_path, grid_path, measurements_path, output_dir):
    source = require_file(config_path); base = load_config(source)
    grid = read_json(grid_path); measurements = read_json(measurements_path)
    if not measurements.get("observations"):
        raise ComponentError("Calibration requires real populated measurements; the empty template is not data")
    choices = grid.get("parameters", {})
    if not choices or any(not isinstance(values,list) or not values for values in choices.values()):
        raise ComponentError("Calibration parameters must be nonempty lists of candidate values")
    total = 1
    for values in choices.values(): total *= len(values)
    limit = integer(grid.get("maximum_runs", 16), "maximum_runs", 1, 1000)
    if total > limit: raise ComponentError(f"Grid has {total} candidates, exceeding maximum_runs={limit}")
    out = Path(output_dir).resolve()
    if out.exists() and any(out.iterdir()): raise ComponentError("Use an empty calibration output directory")
    out.mkdir(parents=True, exist_ok=True); (out/"configs").mkdir(exist_ok=True)
    for key,value in base.get("inputs", {}).items():
        if key != "model_dependencies": base["inputs"][key] = str(resolve_path(value,source.parent))
    base.setdefault("inputs", {})["measurements_file"] = str(require_file(measurements_path))
    base["experiments_dir"] = str(out/"experiments")
    rows = []; best = None
    for index, combination in enumerate(itertools.product(*choices.values()),1):
        config = copy.deepcopy(base); selected = dict(zip(choices,combination))
        for key,value in selected.items(): _set_existing(config,key,value)
        candidate_config = write_json(out/"configs"/f"candidate_{index:03d}.json", config)
        execution = run_pipeline(candidate_config)
        run = Path(execution["experiment_dir"])
        row = {"candidate": index, "parameters": selected, "experiment_dir": str(run), "execution_status": execution["status"]}
        try:
            metrics = read_json(run/"simulation/metrics.json")
            if not metrics.get("numerical_pass"): raise ComponentError("Numerical gate failed; candidate excluded")
            if execution["components"]["cad_converter"].get("status") != "success":
                raise ComponentError("CAD validation failed; candidate excluded")
            agreement = compare_measurements(metrics, measurements)
            row.update(eligible=True, score=agreement["mean_normalized_squared_error"], measurement_agreement=agreement["status"])
            if best is None or row["score"] < best["score"]:
                best = dict(row); write_json(out/"best_pipeline.json", config)
        except (ComponentError, KeyError) as exc:
            row.update(eligible=False, reason=str(exc))
        rows.append(row)
        write_json(out/"calibration_report.json", {"status": "running", "candidates": rows, "best": best})
    report = {"schema_version": 1, "status": "success" if best else "failed", "candidates": rows, "best": best,
              "physical_validation": False, "method": "Exhaustive bounded grid search; no claim of a global optimum outside this grid"}
    write_json(out/"calibration_report.json", report)
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
