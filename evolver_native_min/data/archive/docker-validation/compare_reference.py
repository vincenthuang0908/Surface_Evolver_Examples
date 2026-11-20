"""One-off validation artifact: compare Docker baseline with saved Windows run_006."""
import json
from pathlib import Path

import numpy as np
from scipy.spatial import cKDTree

from pcbsim.cad import load_shape
from pcbsim.common import read_json, sha256, write_json
from pcbsim.mesh import read_off

reference = Path("/reference")
candidate = Path("/data/experiments/docker_baseline")
checks = []


def check(name, passed, **details):
    checks.append({"name": name, "passed": bool(passed), **details})


report = read_json(candidate / "exp_report.json")
check("all_six_stages", report["status"] == "completed" and
      len(report["components"]) == 6 and
      all(item["status"] == "success" for item in report["components"].values()))
check("same_input_step", sha256(reference / "input/original.step") ==
      sha256(candidate / "input/original.step"))

configs = [read_json(root / "input/config.original.json")
           for root in (reference, candidate)]
for config in configs:
    config.pop("experiments_dir", None)
    config["inputs"].pop("step_file", None)
    config["steps"]["surface_evolver"].pop("executable", None)
check("same_settings_except_paths", configs[0] == configs[1])

runner = read_json(candidate / "simulation/runner_report.json")
check("real_native_solver", runner["native_evolver_executed"] and
      runner["status"] == "success", banner=runner.get("solver_banner"))
evaluation = read_json(candidate / "evaluation/automated_test_results.json")
check("evaluation", evaluation["passed"])

a, b = [read_json(root / "simulation/metrics.json")
        for root in (reference, candidate)]
check("numerical_convergence", a["numerical_pass"] and b["numerical_pass"])
# Cross-platform comparison thresholds chosen before reading candidate results.
# These do not replace the solver's unchanged, stricter convergence checks.
for metric in ("maximum_height_above_pad_mm", "free_surface_area_mm2",
               "energy_J", "pressure_Pa", "fillet_volume_mm3", "volume_mm3"):
    x, y = a[metric], b[metric]
    relative_difference = abs(y - x) / abs(x)
    tolerance = 1e-7 if "volume" in metric else 0.01
    check(metric, relative_difference <= tolerance, reference=x, candidate=y,
          relative_difference=relative_difference, relative_tolerance=tolerance)

va, _ = read_off(reference / "simulation/solder_mesh.off")
vb, _ = read_off(candidate / "simulation/solder_mesh.off")
distance = max(float(cKDTree(va).query(vb)[0].max()),
               float(cKDTree(vb).query(va)[0].max()))
check("mesh_nearest_vertex_distance", distance <= 0.001,
      maximum_distance_mm=distance, tolerance_mm=0.001,
      note="Symmetric nearest-vertex distance, not a full surface Hausdorff bound")

conversion = read_json(candidate / "output/conversion_report.json")
check("original_geometry_preserved", conversion["original_geometry_preserved"] and
      conversion["original_solid_count"] == 420 and
      conversion["output_solid_count"] == 421)
for filename, count in (("solder_only.step", 1), ("pcb_with_solder.step", 421)):
    shape = load_shape(candidate / "output" / filename)
    solids = shape.Solids()
    check("reopen_" + filename, len(solids) == count and
          all(solid.isValid() for solid in solids), solid_count=len(solids))

result = {"passed": all(item["passed"] for item in checks),
          "reference": "pcbsim_pipeline/experiments/run_006",
          "candidate": str(candidate), "checks": checks,
          "scope": "Software/numerical/CAD comparison; not experimental validation"}
write_json("/data/validation/windows_reference_comparison.json", result)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result["passed"] else 1)
