"""Standalone native Surface Evolver adapter around the existing runner helpers.

Reuses the frozen commands()/parse_output() from evolver_native_min. Adds an
explicit model contract, OFF/JSON export, strict numerical gates, process-group
timeouts, persistent diagnostics, and physical unit conversion. No mock or
Python-solver fallback exists in this production component.
"""
from __future__ import annotations
import argparse
import importlib.metadata
import os
from pathlib import Path
import platform
import re
import shutil
import signal
import subprocess
import time
import numpy as np
from .._vendor.evolver_native import native as legacy
from ..common import (ComponentError, cli_entry, config_arg, integer, load_config,
                      logger_or_default, positive, read_json, require_file, section, sha256, utc_now, write_json)
from ..mesh import require_valid_mesh, write_off


def find_executable(requested=None) -> str | None:
    if requested in (None, "auto"):
        requested = os.environ.get("SURFACE_EVOLVER_EXE", "auto")
    candidates = ["evolver", "evolver-nox"] if requested == "auto" else [os.path.expandvars(str(requested))]
    for candidate in candidates:
        found = shutil.which(candidate)
        if found:
            return str(Path(found).resolve())
    return None


def build_commands(metadata: dict, settings: dict) -> str:
    refinements = integer(settings.get("refinements", 1), "refinements", 0, 5)
    steps = integer(settings.get("minimization_steps", 300), "minimization_steps", 1, 100000)
    warmup = integer(settings.get("warmup_steps", 30), "warmup_steps", 0, 100000)
    has_body = metadata.get("body_volume_target") is not None
    body_id = integer(metadata.get("body_id", 1), "body_id", 1)
    text = legacy.commands(has_body=has_body, refinements=refinements, steps=steps)
    text = text.replace("body[1]", f"body[{body_id}]").replace("g 30\n", f"g {warmup}\n", 1)
    if not settings.get("edge_swaps", False):
        text = text.replace("\nu\n", "\n")
    # Independent, fixed-length checks; increasing the relaxation budget must
    # not also increase the displacement measurement window.
    check_steps = integer(settings.get("convergence_check_steps", 30), "convergence_check_steps", 1, 10000)
    batches = integer(settings.get("max_convergence_batches", 10), "max_convergence_batches", 2, 100)
    required = integer(settings.get("consecutive_convergence_checks", 2), "consecutive_convergence_checks", 2, batches)
    drift_tol = positive(settings.get("energy_drift_tolerance", 1e-7), "energy_drift_tolerance")
    move_tol = positive(settings.get("max_move_tolerance_mm", 1e-5), "max_move_tolerance_mm")
    volume_tol = positive(settings.get("volume_relative_tolerance", 1e-7), "volume_relative_tolerance")
    if settings.get("conjugate_gradient", True):
        text = text.replace("recalc\n", "recalc\nconj_grad on\n", 1)
    start = text.index("set vertex lab_x x")
    end = text.index('printf "LAB_ENERGY ')
    block = ["lab_passes := 0", "lab_checks := 0"]
    condition = f"lab_drift <= {drift_tol:.17g} and lab_move <= {move_tol:.17g}"
    if has_body:
        target = positive(metadata["body_volume_target"], "body_volume_target")
        condition += f" and abs(body[{body_id}].volume-{target:.17g})/{target:.17g} <= {volume_tol:.17g}"
    relax = f"g {steps};"
    if metadata.get("has_pcbsim_region") and settings.get("improve_free_surface_mesh", True):
        # Swap only edges whose two adjacent facets are liquid-air facets.
        # Never swap across contact/barrel regions with different energies.
        reset = "conj_grad off; conj_grad on; " if settings.get("conjugate_gradient", True) else ""
        relax = ("{ equiangulate edge ee where min(ee.facet,pcbsim_region)==1 "
                 "and max(ee.facet,pcbsim_region)==1; " + reset + relax + " };")
    for batch in range(batches):
        block += [f"if lab_passes < {required} then {{"]
        # Passing checks are confirmed immediately; failing ones trigger more relaxation.
        if batch:
            block += [f"if lab_passes == 0 then {relax}"]
        elif refinements == 0:
            block += [f"g {steps};"]
        block += ["set vertex lab_x x;", "set vertex lab_y y;", "set vertex lab_z z;",
                  "lab_old_energy := total_energy;", f"g {check_steps};",
                  "lab_drift := abs(total_energy-lab_old_energy)/(1+abs(total_energy));",
                  "lab_move := max(vertex,sqrt((x-lab_x)^2+(y-lab_y)^2+(z-lab_z)^2));",
                  "lab_checks += 1;",
                  f"if {condition} then lab_passes += 1 else lab_passes := 0;",
                  'printf "PCS_CHECK %d %.17g %.17g %d\\n",lab_checks,lab_drift,lab_move,lab_passes;', "}"]
    block += ['printf "LAB_CONVERGENCE_CHECKS %.17g\\n",lab_checks',
              'printf "LAB_CONVERGENCE_PASSES %.17g\\n",lab_passes']
    text = text[:start] + "\n".join(block) + "\n" + text[end:]
    if metadata.get("has_pcbsim_region"):
        text = text.replace('dump "final.dmp"',
            'foreach facet ff do printf "PCS_REGION %d %d\\n",ff.id,ff.pcbsim_region\ndump "final.dmp"')
    return text


def _stop_process(process):
    if os.name == "posix":
        try: os.killpg(process.pid, signal.SIGKILL)
        except ProcessLookupError: pass
    else:
        process.kill()
    process.wait()


def run_surface_evolver(model_path, config, output_dir, logger=None, *, metadata_path=None) -> dict:
    log = logger_or_default(logger, "surface_evolver")
    settings = section(config, "surface_evolver")
    out = Path(output_dir).resolve(); out.mkdir(parents=True, exist_ok=True)
    manifest_path = out / "runner_report.json"
    if manifest_path.exists() or (out / "solder_mesh.off").exists() or (out / "metrics.json").exists():
        raise ComponentError(f"Refusing to reuse simulation output directory containing results: {out}. Use a fresh output directory.")
    report = {"schema_version": 1, "component": "surface_evolver", "status": "running",
              "started_at": utc_now(), "native_evolver_executed": False, "numerical_pass": False,
              "physical_validation": False, "outputs": {}, "warnings": []}
    started = time.perf_counter(); write_json(manifest_path, report)
    try:
        model = require_file(model_path, "Surface Evolver model")
        possible_meta = Path(metadata_path) if metadata_path else model.with_suffix(".json")
        if possible_meta.is_file():
            metadata = read_json(possible_meta)
            if metadata.get("model_sha256") and metadata["model_sha256"] != sha256(model):
                raise ComponentError("Model hash differs from its metadata; regenerate the model or supply correct metadata")
            shutil.copy2(possible_meta, out / "model_metadata.json")
        elif "body_volume_target" in settings:
            metadata = {"body_id": settings.get("body_id", 1), "body_volume_target": settings["body_volume_target"],
                        "mesh_contract": settings.get("mesh_contract", "open_surface")}
        else:
            raise ComponentError("Provide a model JSON sidecar, --metadata, or explicit body_volume_target (null for a bodyless model). The runner does not guess body semantics.")
        if metadata.get("body_volume_target") is not None:
            metadata["body_volume_target"] = positive(metadata["body_volume_target"], "body_volume_target")
        script = out / "run.cmd"; script.write_text(build_commands(metadata, settings), encoding="ascii", newline="\n")
        # Preserve the exact FE file too, while keeping its original parent on EVOLVERPATH for dependencies.
        shutil.copy2(model, out / "input_model.fe")
        executable = find_executable(settings.get("executable"))
        report.update({"model_sha256": sha256(model), "command_sha256": sha256(script),
                       "backend": "vendored_evolver_native_min_adapter",
                       "backend_source_sha256": sha256(legacy.__file__), "python_version": platform.python_version(),
                       "platform": platform.platform(), "numpy_version": np.__version__,
                       "seed": metadata.get("seed"), "outputs": {"commands": str(script), "model_snapshot": str(out/"input_model.fe")}})
        if executable is None:
            report.update(status="unavailable", error="Surface Evolver was not found. Install it or set steps.surface_evolver.executable / SURFACE_EVOLVER_EXE. No fallback simulation was performed.")
            return report
        command = [executable, "-x", f"-f{script}", str(model)]
        timeout = positive(settings.get("timeout_seconds", 180), "timeout_seconds")
        report.update({"command": command, "executable": executable, "executable_sha256": sha256(executable)})
        write_json(manifest_path, report)
        env = dict(os.environ); env["LC_ALL"] = "C"
        env["EVOLVERPATH"] = str(model.parent) + os.pathsep + env.get("EVOLVERPATH", "")
        stdout_path = out / "stdout.log"; report["outputs"]["stdout"] = str(stdout_path)
        log.info("Executing Surface Evolver: %s", executable)
        with stdout_path.open("w", encoding="utf-8", newline="\n") as stream:
            process = subprocess.Popen(command, cwd=out, env=env, stdin=subprocess.PIPE,
                                       stdout=stream, stderr=subprocess.STDOUT, text=True,
                                       start_new_session=(os.name == "posix"))
            report["native_evolver_executed"] = True
            try:
                process.communicate("quit 0\n", timeout=timeout)
            except subprocess.TimeoutExpired:
                _stop_process(process)
                report.update(status="timeout", error=f"Native process exceeded {timeout:g} seconds; terminated. Partial stdout is preserved.")
                return report
            except BaseException:
                _stop_process(process)
                raise
        text = stdout_path.read_text(encoding="utf-8", errors="replace")
        report["returncode"] = process.returncode
        banner = re.search(r"(?im)^.*Surface Evolver[^\n]*", text)
        report["solver_banner"] = banner.group(0) if banner else None
        warnings = re.findall(r"(?im)^.*\bWARNING\b[^\n]*", text)
        errors = re.findall(r"(?im)^.*\b(?:SYNTAX ERROR|DATAFILE ERROR|FATAL ERROR|RUNTIME ERROR|ERROR\s+\d+:)[^\n]*", text)
        report["warnings"] = warnings[:100]
        if process.returncode or errors or (warnings and not settings.get("allow_warnings", False)):
            raise ComponentError(f"Native solver returned {process.returncode}, {len(errors)} errors and {len(warnings)} warnings; inspect stdout.log")
        raw, v, f = legacy.parse_output(text)
        required = {"energy", "energy_drift", "max_move", "area", "facets", "convergence_checks", "convergence_passes"}
        if metadata.get("body_volume_target") is not None: required |= {"volume", "pressure"}
        missing = required - set(raw)
        if missing:
            raise ComponentError(f"Native output lacks required metrics: {sorted(missing)}")
        if raw["facets"] != len(f):
            raise ComponentError("Exported facet count does not match the solver's facet count")
        closed = metadata.get("mesh_contract") == "closed_shell"
        mesh_info = require_valid_mesh(v, f, closed=closed)
        target = metadata.get("body_volume_target")
        volume_error = abs(raw["volume"]-target)/target if target is not None else None
        volume_tol = positive(settings.get("volume_relative_tolerance", 1e-7), "volume_relative_tolerance")
        drift_tol = positive(settings.get("energy_drift_tolerance", 1e-7), "energy_drift_tolerance")
        move_tol = positive(settings.get("max_move_tolerance_mm", 1e-5), "max_move_tolerance_mm")
        gate = bool((volume_error is None or volume_error <= volume_tol) and raw["energy_drift"] <= drift_tol and raw["max_move"] <= move_tol)
        required_checks = integer(settings.get("consecutive_convergence_checks", 2), "consecutive_convergence_checks", 2, 100)
        gate = gate and raw["convergence_passes"] >= required_checks
        if closed and target is not None:
            mesh_volume_error = abs(mesh_info["signed_volume_mm3"]-raw["volume"])/target
            if mesh_volume_error > max(volume_tol, 1e-6):
                raise ComponentError("Exported closed mesh volume disagrees with the solver volume")
        mesh_path = write_off(out / "solder_mesh.off", v, f)
        np.savez_compressed(out / "mesh.npz", vertices=v, faces=f)
        metrics = {"schema_version": 1, "raw_evolver": raw,
            "volume_mm3": raw.get("volume"), "target_volume_mm3": target, "volume_relative_error": volume_error,
            "energy_scaled": raw["energy"], "energy_drift_relative": raw["energy_drift"],
            "convergence_check_steps": settings.get("convergence_check_steps", 30),
            "convergence_checks": raw.get("convergence_checks"),
            "consecutive_convergence_passes": raw.get("convergence_passes"),
            "max_move_mm": raw["max_move"], "total_shell_area_mm2": mesh_info["surface_area_mm2"],
            "maximum_height_above_pad_mm": float(v[:,2].max()),
            "mesh": mesh_info, "mesh_sha256": sha256(mesh_path), "model_sha256": sha256(model),
            "command_sha256": sha256(script), "numerical_pass": gate, "physical_validation": False,
            "numerical_gate_scope": "Volume, fixed-final-mesh energy drift and displacement only. Not a Hessian stability, mesh-convergence, or experimental validation test.",
            "tolerances": {"volume_relative": volume_tol, "energy_drift_relative": drift_tol, "max_move_mm": move_tol}}
        if metadata.get("has_pcbsim_region"):
            region_map = {int(i): int(r) for i,r in re.findall(r'(?m)(?<!["\w])PCS_REGION\s+(\d+)\s+(\d+)\s*$', text)}
            face_ids = [int(row[0]) for row in re.findall(r'(?m)(?<!["\w])LAB_FACE\s+(\d+)\s+(\d+)\s+(\d+)\s+(\d+)\s*$', text)]
            if len(face_ids) != len(f) or any(i not in region_map for i in face_ids):
                raise ComponentError("Generated model output is missing inherited surface-region labels")
            areas = np.linalg.norm(np.cross(v[f[:,1]]-v[f[:,0]], v[f[:,2]]-v[f[:,0]]), axis=1)/2
            metrics["free_surface_area_mm2"] = float(areas[[region_map[i]==1 for i in face_ids]].sum())
            metrics["barrel_volume_mm3"] = metadata["barrel_volume_mm3"]
            metrics["fillet_volume_mm3"] = raw["volume"]-metadata["barrel_volume_mm3"]
            geometry = metadata.get("geometry", {})
            if geometry:
                hmax = geometry["pin"]["max_straight_height_mm"]
                bound_hit = bool(v[:,2].max() >= hmax-1e-6)
                metrics["pin_height_limit_reached"] = bound_hit
                if bound_hit:
                    report["warnings"].append("The pin height bound is active; the excluded bevel may affect the result.")
        scales = metadata.get("parameters", {}).get("scales", {})
        if scales:
            metrics["energy_J"] = raw["energy"]*scales["energy_J"]
            if "pressure" in raw: metrics["pressure_Pa"] = raw["pressure"]*scales["pressure_Pa"]
        metrics_path = write_json(out / "metrics.json", metrics)
        report["outputs"].update(mesh=str(mesh_path), metrics=str(metrics_path), mesh_arrays=str(out / "mesh.npz"))
        report.update(numerical_pass=gate, status="success")
        if not gate:
            report["warnings"].append("Native execution completed, but numerical convergence checks failed.")
            if settings.get("require_numerical_pass", True):
                report.update(status="failed", error="Numerical gate failed; diagnostic mesh and metrics retained, CAD conversion blocked by default.")
        log.info("Native execution complete; numerical_pass=%s", gate)
        return report
    except (OSError, ValueError, KeyError, ComponentError) as exc:
        report.update(status="failed", error=str(exc))
        return report
    except BaseException as exc:
        report.update(status="failed", error=f"Interrupted: {type(exc).__name__}")
        raise
    finally:
        report.update(ended_at=utc_now(), duration_seconds=time.perf_counter()-started)
        write_json(manifest_path, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__); config_arg(parser)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--executable", help="Override the configured native executable")
    args = parser.parse_args(); config = load_config(args.config)
    settings = section(config, "surface_evolver")
    if args.executable: settings["executable"] = args.executable
    return run_surface_evolver(args.model, settings, args.output_dir, metadata_path=args.metadata)

if __name__ == "__main__":
    cli_entry(main)
