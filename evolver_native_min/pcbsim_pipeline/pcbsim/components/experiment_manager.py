"""Orchestrator only: snapshot inputs, call independent component APIs, log.

Paths in a pipeline configuration resolve relative to that configuration file,
not the working directory. Disabled stages can consume explicitly supplied
upstream artifacts. No stage is silently faked or re-used from an old run.
"""
from __future__ import annotations
import argparse
import copy
import importlib.metadata
import logging
from pathlib import Path
import platform
import re
import shutil
import time
import traceback
from ..common import (ComponentError, cli_entry, load_config, read_json, require_file,
                      resolve_path, sha256, utc_now, write_json)

STAGES = ("cad_extractor", "material_manager", "fe_generator", "surface_evolver", "cad_converter", "evaluation")
ARTIFACTS = {"step_file": "input/original.step", "extracted_step": "geometry/extracted.step",
             "geometry_file": "geometry/geometry.json", "parameters_file": "parameters/materials.json",
             "model_file": "fe/model.fe", "model_metadata_file": "fe/model.json",
             "solder_mesh_file": "simulation/solder_mesh.off", "metrics_file": "simulation/metrics.json",
             "measurements_file": "input/measurements.json"}
PRODUCED_BY = {"extracted_step": "cad_extractor", "geometry_file": "cad_extractor", "parameters_file": "material_manager",
               "model_file": "fe_generator", "model_metadata_file": "fe_generator", "solder_mesh_file": "surface_evolver", "metrics_file": "surface_evolver"}


class ComponentLog(logging.LoggerAdapter):
    def process(self, msg, kwargs):
        return f"[{self.extra['component']}] {msg}", kwargs


def code_fingerprints() -> dict:
    package = Path(__file__).resolve().parents[1]
    return {str(path.relative_to(package)): sha256(path) for path in sorted(package.rglob("*.py"))}


def environment_info() -> dict:
    versions = {}
    for name in ("numpy", "scipy", "cadquery", "cadquery-ocp", "pytest"):
        try: versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: versions[name] = None
    return {"python": platform.python_version(), "platform": platform.platform(), "packages": versions}


def validate_experiment_id(identifier):
    if identifier and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,100}", identifier):
        raise ComponentError("Experiment ID may contain only letters, numbers, underscores and hyphens")


def _create_run(root, identifier=None):
    validate_experiment_id(identifier)
    root.mkdir(parents=True, exist_ok=True)
    if identifier:
        run = root/identifier
        try: run.mkdir()
        except FileExistsError as exc: raise ComponentError(f"Experiment already exists: {identifier}") from exc
        return run
    for i in range(1,1000000):
        run = root/f"run_{i:03d}"
        try: run.mkdir(); return run
        except FileExistsError: continue
    raise ComponentError("No experiment IDs available")


def _save_report(run, report):
    # The SDD uses two names for the report and log. Keep aliases with identical
    # content instead of silently picking one interpretation.
    write_json(run/"exp_report.json", report)
    write_json(run/"experiment.json", report)


def _validate_config(config):
    if config.get("schema_version", 1) != 1:
        raise ComponentError("Unsupported pipeline schema_version")
    if not isinstance(config.get("inputs", {}), dict) or not isinstance(config.get("steps", {}), dict):
        raise ComponentError("inputs and steps must be objects")
    unknown = set(config.get("steps", {}))-set(STAGES)
    if unknown: raise ComponentError(f"Unknown pipeline steps: {sorted(unknown)}")
    unknown_inputs = set(config.get("inputs", {})) - (set(ARTIFACTS) | {"model_dependencies"})
    if unknown_inputs: raise ComponentError(f"Unknown input keys: {sorted(unknown_inputs)}")
    for name, settings in config.get("steps", {}).items():
        if not isinstance(settings, dict) or not isinstance(settings.get("enabled", True), bool):
            raise ComponentError(f"steps.{name}.enabled must be a boolean")
    for key, value in config.get("inputs", {}).items():
        if key != "model_dependencies" and not isinstance(value, str):
            raise ComponentError(f"inputs.{key} must be a path string")


def requested_stages(config, *, stop_after=None, only=None):
    _validate_config(config)
    if stop_after is not None and stop_after not in STAGES:
        raise ComponentError(f"Unknown stop_after: {stop_after}")
    only_set = set(only) if only else None
    if only_set and not only_set.issubset(STAGES):
        raise ComponentError(f"Unknown stage selection: {sorted(only_set-set(STAGES))}")
    requested = [name for name in STAGES if config.get("steps", {}).get(name, {}).get("enabled", True)
                 and (only_set is None or name in only_set)
                 and (stop_after is None or STAGES.index(name)<=STAGES.index(stop_after))]
    if not requested: raise ComponentError("No enabled stages requested")
    for key, producer in PRODUCED_BY.items():
        if key in config.get("inputs", {}) and producer in requested:
            raise ComponentError(f"inputs.{key} conflicts with enabled producer {producer}; disable it or remove the supplied artifact")
    return requested


def run_pipeline(config_path, *, experiment_id=None, experiments_dir=None, stop_after=None,
                 only=None, input_overrides=None) -> dict:
    path = require_file(config_path, "pipeline configuration")
    original_config = read_json(path); config = load_config(path)
    if input_overrides:
        config.setdefault("inputs", {}).update(input_overrides)
    requested = requested_stages(config, stop_after=stop_after, only=only)
    root = resolve_path(experiments_dir or config.get("experiments_dir", "experiments"), path.parent)
    run = _create_run(root, experiment_id)
    for folder in ("input", "geometry", "parameters", "fe", "simulation", "output", "evaluation"):
        (run/folder).mkdir()
    logger = logging.getLogger(f"pcbsim.experiment.{run}"); logger.setLevel(logging.INFO); logger.propagate = False
    formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%dT%H:%M:%S")
    for name in ("exp_execution_steps.log", "experiment.log"):
        handler = logging.FileHandler(run/name, encoding="utf-8"); handler.setFormatter(formatter); logger.addHandler(handler)
    console = logging.StreamHandler(); console.setFormatter(formatter); logger.addHandler(console)
    log = ComponentLog(logger, {"component": "Experiment Manager"})
    started = time.perf_counter()
    report = {"schema_version": 1, "experiment_id": run.name, "experiment_dir": str(run),
        "status": "running", "start_time": utc_now(), "requested_steps": requested,
        "execution_scope": "full" if requested==list(STAGES) else "selected_stages",
        "components": {name: {"status": "pending" if name in requested else "skipped"} for name in STAGES},
        "saved_inputs": {}, "environment": environment_info(), "code_sha256": code_fingerprints()}
    _save_report(run, report)
    current = None
    try:
        log.info("Experiment %s started", run.name)
        shutil.copy2(path, run/"input/config.original.json")
        effective = copy.deepcopy(config); effective.setdefault("inputs", {})
        effective.setdefault("steps", {})
        for name in STAGES:
            effective["steps"].setdefault(name, {})["enabled"] = name in requested
        effective["experiments_dir"] = "../.."
        for key, relative in ARTIFACTS.items():
            if key not in config.get("inputs", {}): continue
            source = require_file(resolve_path(config["inputs"][key], path.parent), key)
            destination = run/relative
            shutil.copy2(source, destination)
            effective["inputs"][key] = str(Path("..")/relative) if not relative.startswith("input/") else Path(relative).name
            report["saved_inputs"][relative] = sha256(destination)
        if "model_file" in config.get("inputs", {}) and "model_metadata_file" not in config["inputs"]:
            original_model = resolve_path(config["inputs"]["model_file"], path.parent)
            sidecar = original_model.with_suffix(".json")
            if sidecar.is_file():
                shutil.copy2(sidecar, run/"fe/model.json")
                effective["inputs"]["model_metadata_file"] = "../fe/model.json"
                report["saved_inputs"]["fe/model.json"] = sha256(sidecar)
        dependencies = config.get("inputs", {}).get("model_dependencies", [])
        if dependencies:
            if "model_file" not in config["inputs"] or not isinstance(dependencies, list):
                raise ComponentError("model_dependencies must be a list relative to an explicitly supplied model_file")
            model_parent = resolve_path(config["inputs"]["model_file"], path.parent).parent
            for dependency in dependencies:
                relative = Path(dependency)
                if relative.is_absolute() or ".." in relative.parts or str(relative) in {"model.fe", "model.json"}:
                    raise ComponentError("Model dependency paths must stay within the model folder and not overwrite model.fe/model.json")
                source = require_file(model_parent/relative, "FE dependency")
                target = run/"fe"/relative; target.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, target)
                report["saved_inputs"][str(target.relative_to(run))] = sha256(target)
        # Save the original external component configurations as audit inputs,
        # while the runnable snapshot contains their fully expanded values.
        for name, settings in original_config.get("steps", {}).items():
            if "config_file" in settings:
                source = require_file(resolve_path(settings["config_file"], path.parent))
                target = run/"input"/f"{name}.source.json"; shutil.copy2(source, target)
                report["saved_inputs"][str(target.relative_to(run))] = sha256(target)
        executable = effective["steps"]["surface_evolver"].get("executable")
        if executable and ("/" in executable or "\\" in executable):
            effective["steps"]["surface_evolver"]["executable"] = str(resolve_path(executable, path.parent))
        write_json(run/"input/config.json", effective)
        report["saved_inputs"]["input/config.json"] = sha256(run/"input/config.json")
        report["saved_inputs"]["input/config.original.json"] = sha256(run/"input/config.original.json")
        write_json(run/"input/environment.json", report["environment"])
        _save_report(run, report)
        # Imports are local: even the manager can run just the solver without
        # loading CadQuery, and all components remain separately invokable.
        for name in STAGES:
            if name not in requested: continue
            current = name; start = time.perf_counter()
            component_log = ComponentLog(logger, {"component": name})
            report["components"][name] = {"status": "running", "start_time": utc_now()}
            _save_report(run, report); component_log.info("Started")
            if name == "cad_extractor":
                from .cad_extractor import extract_cad
                stage = extract_cad(run/"input/original.step", effective, run/"geometry", component_log)
            elif name == "material_manager":
                from .material_manager import manage_materials
                stage = manage_materials(effective, run/"parameters/materials.json", component_log)
            elif name == "fe_generator":
                from .fe_generator import generate_fe
                stage = generate_fe(run/"geometry/extracted.step", run/"geometry/geometry.json", run/"parameters/materials.json", effective, run/"fe/model.fe", component_log)
            elif name == "surface_evolver":
                from .surface_evolver_runner import run_surface_evolver
                stage = run_surface_evolver(run/"fe/model.fe", effective, run/"simulation", component_log)
            elif name == "cad_converter":
                from .cad_converter import convert_cad
                filename = effective["steps"][name].get("output_filename", "pcb_with_solder.step")
                if Path(filename).name != filename or Path(filename).suffix.lower() not in {".step", ".stp"}:
                    raise ComponentError("CAD output_filename must be a plain STEP filename")
                stage = convert_cad(run/"simulation/solder_mesh.off", run/"input/original.step", run/"geometry/geometry.json", effective, run/"output"/filename, component_log)
            else:
                from .evaluation import evaluate_experiment
                measurements = run/"input/measurements.json"
                stage = evaluate_experiment(run, effective, run/"evaluation", component_log,
                    measurements_path=measurements if measurements.is_file() else None)
            record = report["components"][name]
            record.update({k:v for k,v in stage.items() if k != "outputs"})
            record.update(end_time=utc_now(), duration_seconds=time.perf_counter()-start)
            record["outputs"] = {}; record["output_sha256"] = {}
            for key, value in stage.get("outputs", {}).items():
                artifact = Path(value)
                try: relative = str(artifact.relative_to(run))
                except ValueError: relative = str(artifact)
                record["outputs"][key] = relative
                if artifact.is_file(): record["output_sha256"][key] = sha256(artifact)
            _save_report(run, report)
            if stage.get("status") != "success":
                raise ComponentError(stage.get("error", f"{name} did not pass; inspect its component report"))
            component_log.info("Completed successfully")
        report["status"] = "completed"; log.info("Experiment %s completed", run.name)
    except (Exception, KeyboardInterrupt) as exc:
        report.update(status="failed", error=str(exc) or type(exc).__name__, failed_component=current or "input_snapshot")
        if current:
            report["components"][current].update(status="failed", error=report["error"], end_time=utc_now())
        log.error("Experiment failed in %s: %s", report["failed_component"], report["error"])
        logger.error(traceback.format_exc())
    finally:
        report.update(end_time=utc_now(), duration_seconds=time.perf_counter()-started)
        _save_report(run, report)
        for handler in list(logger.handlers):
            handler.flush(); handler.close(); logger.removeHandler(handler)
    return report


def reproduce_experiment(reference_dir, *, experiment_id=None, allow_code_change=False) -> dict:
    from .evaluation import compare_experiments
    source = Path(reference_dir).resolve(); original = read_json(source/"exp_report.json")
    if original.get("status") != "completed" or original.get("components", {}).get("cad_converter", {}).get("status") != "success":
        raise ComponentError("Reproduction comparison requires a completed reference run including native simulation and CAD conversion")
    for relative, expected in original.get("saved_inputs", {}).items():
        if sha256(require_file(source/relative, "saved experiment input")) != expected:
            raise ComponentError(f"Saved input was modified: {relative}")
    changed = original.get("code_sha256") != code_fingerprints()
    if changed and not allow_code_change:
        raise ComponentError("Pipeline source code differs from the reference run. Restore its code snapshot or explicitly use --allow-code-change.")
    config = source/"input/config.json"
    candidate = run_pipeline(config, experiment_id=experiment_id, experiments_dir=source.parent)
    new_run = Path(candidate["experiment_dir"])
    comparison = compare_experiments(source, new_run, load_config(config))
    comparison.update(reference_run=str(source), candidate_run=str(new_run), code_changed=changed)
    write_json(new_run/"evaluation/reproducibility.json", comparison)
    write_json(source/"evaluation"/f"reproducibility_{new_run.name}.json", comparison)
    return comparison


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("pipeline.json"))
    parser.add_argument("--experiment-id")
    parser.add_argument("--experiments-dir", type=Path)
    parser.add_argument("--stop-after", choices=STAGES)
    parser.add_argument("--only", nargs="+", choices=STAGES)
    args = parser.parse_args()
    return run_pipeline(args.config, experiment_id=args.experiment_id, experiments_dir=args.experiments_dir,
                        stop_after=args.stop_after, only=args.only)

if __name__ == "__main__":
    cli_entry(main)
