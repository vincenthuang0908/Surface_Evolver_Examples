"""Independent artifact, measurement, and reproducibility evaluation.

This module never runs the simulator. Re-execution belongs to the experiment
manager; compare_experiments() only compares already completed artifacts.
"""
from __future__ import annotations
import argparse
from collections import Counter
import csv
import io
from pathlib import Path
import math
import numpy as np
from scipy.spatial import cKDTree
from ..common import (ComponentError, cli_entry, config_arg, load_config, logger_or_default,
                      positive, read_json, require_file, result, section, sha256, write_json)
from ..mesh import read_off, require_valid_mesh
from .observables import OBSERVABLES

MEASURABLE = {key for key, metric in OBSERVABLES.items() if metric.category == "Geometry"}
# Keep support for existing CLI datasets comparing modeled energy or pressure.
_COMPARABLE = MEASURABLE | {"pressure_Pa", "energy_J", "liquid_air_surface_energy_J"}


def _step_exports(root):
    return (path for path in (root / "output").glob("*")
            if path.is_file() and path.suffix.lower() in {".step", ".stp"})


def validate_measurements(measurements: dict, *, allowed=None) -> dict:
    if not isinstance(measurements, dict) or measurements.get("schema_version", 1) != 1:
        raise ComponentError("Expected a schema version 1 measurement dataset")
    observations = measurements.get("observations")
    if not isinstance(observations, dict) or not observations:
        raise ComponentError("Measurement file must contain nonempty observations; the template is not real measurement data")
    if not isinstance(measurements.get("source", ""), str):
        raise ComponentError("Measurement source must be text")
    allowed = _COMPARABLE if allowed is None else allowed
    validated = {}
    for name, observation in observations.items():
        if name not in allowed:
            raise ComponentError(f"Unsupported or unselected observation {name!r}")
        if not isinstance(observation, dict):
            raise ComponentError(f"Observation {name} must provide a value and absolute_tolerance")
        unit = OBSERVABLES[name].unit
        aliases = {"mm³": "mm^3", "mm²": "mm^2", "°": "deg"}
        if observation.get("unit", unit) not in (unit, aliases.get(unit, unit)):
            raise ComponentError(f"Observation {name} must use {unit}")
        try:
            if isinstance(observation.get("value"), bool):
                raise ValueError
            measured = float(observation["value"])
        except (ValueError, TypeError, KeyError, OverflowError) as exc:
            raise ComponentError(f"Observation {name} needs a finite numeric value") from exc
        if (not math.isfinite(measured) or (name in MEASURABLE and measured < 0)
                or (unit == "°" and measured > 180)):
            raise ComponentError(f"Observation {name} is outside its physical range")
        tolerance = positive(observation.get("absolute_tolerance"), f"{name}.absolute_tolerance")
        validated[name] = {**observation, "value": measured, "absolute_tolerance": tolerance, "unit": unit}
    return {**measurements, "schema_version": 1, "observations": validated}


def measurements_from_csv(text):
    """Read one observation per metric, using the same contract as JSON."""
    reader = csv.DictReader(io.StringIO(text), strict=True)
    fields = {"metric", "value", "unit", "absolute_tolerance"}
    observations = {}
    try:
        if not fields.issubset(reader.fieldnames or []):
            raise ComponentError("CSV needs metric, value, unit, and absolute_tolerance columns")
        for row in reader:
            if None in row or any(row[field] is None for field in fields):
                raise ComponentError(f"Incorrect CSV column count on line {reader.line_num}")
            metric = row["metric"].strip()
            if not metric or metric in observations:
                raise ComponentError(f"CSV metric is blank or repeated on line {reader.line_num}")
            observations[metric] = {field: row[field] for field in fields - {"metric"}}
    except csv.Error as exc:
        raise ComponentError(f"Invalid CSV near line {reader.line_num}: {exc}") from exc
    return validate_measurements({"observations": observations})


def compare_measurements(metrics: dict, measurements: dict) -> dict:
    observations = validate_measurements(measurements)["observations"]
    rows = []; score = 0.0
    for name, observation in observations.items():
        if name not in metrics or metrics[name] is None:
            raise ComponentError(f"Simulation did not produce measured quantity {name}")
        measured = observation["value"]; prediction = float(metrics[name])
        tolerance = observation["absolute_tolerance"]
        if not math.isfinite(prediction):
            raise ComponentError(f"Prediction for {name} must be finite")
        difference = abs(prediction-measured)
        relative = difference/tolerance
        squared = relative * relative
        percentage = 100 * (difference / abs(measured)) if measured else None
        if not math.isfinite(squared) or (percentage is not None and not math.isfinite(percentage)):
            raise ComponentError(f"Errors for {name} exceed the supported numeric range")
        score += squared / len(observations)
        rows.append({"metric": name, "measured": measured, "predicted": prediction,
                     "unit": observation["unit"], "absolute_difference": difference,
                     "absolute_percentage_error": percentage, "absolute_tolerance": tolerance,
                     "signed_error_over_tolerance": (prediction-measured)/tolerance,
                     "passed": difference <= tolerance})
    return {"status": "passed" if all(row["passed"] for row in rows) else "failed",
            "observations": rows, "mean_normalized_squared_error": score,
            "scope": "Agreement for the supplied observables only; not general physical validation"}


def evaluate_experiment(experiment_dir, config=None, output_dir=None, logger=None, *, measurements_path=None) -> dict:
    root = Path(experiment_dir).resolve(); settings = section(config or {}, "evaluation")
    out = Path(output_dir).resolve() if output_dir else root / "evaluation"
    log = logger_or_default(logger, "evaluation"); tests = []
    execution = read_json(root/"exp_report.json") if (root/"exp_report.json").is_file() else {}
    components = execution.get("components", {})
    def expected(name):
        if components:
            return components.get(name, {}).get("status") not in {None, "skipped", "not_requested"}
        return True
    def check(identifier, name, operation):
        try:
            details = operation()
            tests.append({"id": identifier, "name": name, "passed": True, "details": details})
        except (ComponentError, OSError, ValueError, KeyError) as exc:
            tests.append({"id": identifier, "name": name, "passed": False, "error": str(exc)})
    if expected("cad_extractor"):
        def geometry_check():
            g = read_json(root/"geometry/geometry.json")
            extracted = require_file(root/"geometry/extracted.step")
            if g.get("extracted_step_sha256") != sha256(extracted) or not g.get("validation", {}).get("hole_preserved"):
                raise ComponentError("Geometry/extracted STEP receipt mismatch or missing hole check")
            return {"hole_preserved": True, "extracted_step_hash_verified": True}
        check("GEOM-T01", "Extracted geometry provenance and hole preservation", geometry_check)
    if expected("fe_generator"):
        def fe_check():
            meta = read_json(root/"fe/model.json")
            if meta.get("model_sha256") != sha256(require_file(root/"fe/model.fe")):
                raise ComponentError("Generated FE model no longer matches its sidecar")
            v,f = read_off(root/"fe/initial_mesh.off")
            return require_valid_mesh(v,f,closed=True)
        check("FE-T01", "Generated FE hash and closed initial topology", fe_check)
    metrics = None
    if expected("surface_evolver"):
        def simulation_check():
            nonlocal metrics
            metrics = read_json(root/"simulation/metrics.json")
            receipt = read_json(root/"simulation/runner_report.json")
            if receipt.get("status") != "success" or not receipt.get("native_evolver_executed"):
                raise ComponentError("No successful native execution receipt")
            if settings.get("require_numerical_pass", True) and not metrics.get("numerical_pass"):
                raise ComponentError("Numerical convergence checks did not pass")
            mesh_file = require_file(root/"simulation/solder_mesh.off")
            if metrics.get("mesh_sha256") != sha256(mesh_file):
                raise ComponentError("Solder mesh was changed after simulation")
            v,f = read_off(mesh_file)
            return {"mesh": require_valid_mesh(v,f,closed=True), "numerical_pass": metrics.get("numerical_pass"),
                    "physical_validation": False}
        check("SIM-T01", "Native execution, convergence and solder mesh", simulation_check)
    if expected("cad_converter"):
        def cad_check():
            receipt = read_json(root/"output/conversion_report.json")
            match = any(sha256(p) == receipt.get("output_sha256") for p in _step_exports(root))
            if not match or receipt.get("status") != "success":
                raise ComponentError("Combined STEP is missing, changed, or has no successful conversion receipt")
            if not receipt.get("step_reopened") or not receipt.get("original_geometry_preserved"):
                raise ComponentError("Missing round-trip or original-geometry preservation check")
            if receipt["output_solid_count"] != receipt["original_solid_count"]+1:
                raise ComponentError("Incorrect combined STEP solid count")
            return {"step_hash_verified": True, "roundtrip_receipt_verified": True,
                    "original_solid_count": receipt["original_solid_count"], "output_solid_count": receipt["output_solid_count"]}
        check("CAD-T09", "STEP round-trip receipt, hash and original-solid preservation", cad_check)
    measurement_report = {"status": "not_provided", "scope": "No agreement with real measurements has been established"}
    if measurements_path:
        def measurement_check():
            nonlocal measurement_report
            m = metrics if metrics is not None else read_json(root/"simulation/metrics.json")
            measurement_report = compare_measurements(m, read_json(measurements_path))
            if measurement_report["status"] != "passed":
                raise ComponentError("Simulation differs from supplied measurements beyond their tolerances")
            return measurement_report
        check("CAL-T01", "Agreement with supplied measurements", measurement_check)
        if measurement_report["status"] == "failed" and not settings.get("require_measurement_agreement", True):
            tests[-1]["required"] = False
    if not tests:
        raise ComponentError("No artifacts were requested or found for evaluation")
    passed = all(test["passed"] or not test.get("required", True) for test in tests)
    report = {"schema_version": 1, "component": "evaluation", "status": "success" if passed else "failed",
              "passed": passed, "tests": tests, "measurements": measurement_report,
              "physical_validation": False,
              "note": "Checks are scoped. Passing topology/numerical checks is not proof of physical correctness.",
              "outputs": {"evaluation": str(out/"automated_test_results.json")}}
    write_json(out/"automated_test_results.json", report)
    log.info("Evaluation: %s (%d checks)", "PASS" if passed else "FAIL", len(tests))
    return report


def _compare_meshes(path_a, path_b, tolerance):
    va,fa = read_off(path_a); vb,fb = read_off(path_b)
    require_valid_mesh(va,fa,closed=True); require_valid_mesh(vb,fb,closed=True)
    da, mapping = cKDTree(vb).query(va)
    db, _ = cKDTree(va).query(vb)
    distance = max(float(da.max()), float(db.max()))
    topological_match = False
    if len(va)==len(vb) and len(fa)==len(fb) and len(np.unique(mapping))==len(va):
        a = Counter(tuple(sorted(map(int, triangle))) for triangle in mapping[fa])
        b = Counter(tuple(sorted(map(int, triangle))) for triangle in fb)
        topological_match = a==b
    return {"passed": bool(distance <= tolerance and topological_match),
            "bidirectional_vertex_distance_mm": distance, "tolerance_mm": tolerance,
            "same_triangle_connectivity_under_vertex_mapping": topological_match,
            "method": "One-to-one vertex correspondence plus equal triangle connectivity; supports renumbering, not unrelated remeshing"}


def compare_experiments(reference_dir, candidate_dir, config=None, output_path=None) -> dict:
    a, b = Path(reference_dir).resolve(), Path(candidate_dir).resolve()
    settings = section(config or {}, "evaluation")
    rtol = positive(settings.get("relative_tolerance", 1e-6), "relative_tolerance", allow_zero=True)
    atol = positive(settings.get("absolute_tolerance", 1e-8), "absolute_tolerance", allow_zero=True)
    distance_tol = positive(settings.get("mesh_distance_tolerance_mm", 1e-6), "mesh_distance_tolerance_mm", allow_zero=True)
    checks = []
    try:
        for root in (a, b):
            receipt = root / "exp_report.json"
            if receipt.is_file() and read_json(receipt).get("status") != "completed":
                raise ComponentError(f"Experiment {root.name} did not complete successfully")
        ma, mb = read_json(a/"simulation/metrics.json"), read_json(b/"simulation/metrics.json")
        for key in ["model_sha256", "command_sha256"]:
            checks.append({"name": key, "passed": ma.get(key) is not None and ma.get(key)==mb.get(key)})
        checks.append({"name": "both_numerically_converged", "passed": bool(ma.get("numerical_pass") and mb.get("numerical_pass"))})
        for key in ["energy_scaled", "volume_mm3", "free_surface_area_mm2", "maximum_height_above_pad_mm", "pressure_Pa"]:
            if key not in ma and key not in mb: continue
            if ma.get(key) is None or mb.get(key) is None:
                checks.append({"name": key, "passed": False, "reason": "Missing metric"}); continue
            x,y = float(ma[key]),float(mb[key]); tolerance = settings.get("metric_tolerances", {}).get(key, {})
            absolute = positive(tolerance.get("absolute", atol), key+" absolute tolerance", allow_zero=True)
            relative = positive(tolerance.get("relative", rtol), key+" relative tolerance", allow_zero=True)
            bound = absolute+relative*max(abs(x),abs(y))
            checks.append({"name": key, "passed": bool(math.isfinite(x) and math.isfinite(y) and abs(x-y)<=bound),
                           "reference": x, "candidate": y, "absolute_difference": abs(x-y), "allowed_difference": bound})
        checks.append({"name": "solder_mesh", **_compare_meshes(a/"simulation/solder_mesh.off", b/"simulation/solder_mesh.off", distance_tol)})
        # Check the STEP reconstruction receipts against actual file hashes;
        # compare geometry, not timestamps or incidental STEP entity numbering.
        ca, cb = read_json(a/"output/conversion_report.json"), read_json(b/"output/conversion_report.json")
        def valid_step(root, receipt):
            return (receipt.get("status")=="success" and receipt.get("step_reopened")
                and any(sha256(p)==receipt.get("output_sha256") for p in _step_exports(root)))
        step_pass = (valid_step(a,ca) and valid_step(b,cb) and ca.get("source_sha256")==cb.get("source_sha256")
                     and ca.get("output_solid_count")==cb.get("output_solid_count")
                     and ca.get("original_geometry_preserved") and cb.get("original_geometry_preserved")
                     and np.allclose(ca["local_to_world"], cb["local_to_world"], atol=distance_tol, rtol=0)
                     and math.isclose(ca["solder_volume_mm3"], cb["solder_volume_mm3"], abs_tol=atol, rel_tol=rtol))
        checks.append({"name": "combined_step", "passed": bool(step_pass),
                       "method": "File-hash-verified round-trip receipts, common original geometry, solder volume and placement; solder shape is separately compared by the mesh check"})
    except (OSError, ValueError, KeyError, ComponentError) as exc:
        checks.append({"name": "required_artifacts", "passed": False, "error": str(exc)})
    passed = bool(checks) and all(c["passed"] for c in checks)
    report = {"schema_version": 1, "status": "success" if passed else "failed", "passed": passed,
              "reference_experiment": a.name, "candidate_experiment": b.name, "checks": checks}
    if output_path: write_json(output_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__); config_arg(parser)
    sub = parser.add_subparsers(dest="command", required=True)
    evaluate = sub.add_parser("evaluate")
    evaluate.add_argument("--experiment", required=True, type=Path)
    evaluate.add_argument("--output-dir", type=Path)
    evaluate.add_argument("--measurements", type=Path)
    compare = sub.add_parser("compare")
    compare.add_argument("--reference", required=True, type=Path)
    compare.add_argument("--candidate", required=True, type=Path)
    compare.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(); cfg = load_config(args.config)
    if args.command=="compare":
        return compare_experiments(args.reference, args.candidate, cfg, args.output)
    return evaluate_experiment(args.experiment, cfg, args.output_dir, measurements_path=args.measurements)

if __name__ == "__main__":
    cli_entry(main)
