from pathlib import Path

import numpy as np
import pytest

from pcbsim.common import ComponentError, read_json, write_json
from pcbsim.components.calibration import calibrate
from pcbsim.components.evaluation import compare_measurements, measurements_from_csv
from pcbsim.components.fe_generator import build_model
from pcbsim.components.material_manager import normalize_materials
from pcbsim.components.observables import mesh_contact_angles
from pcbsim.components.surface_evolver_runner import find_executable, run_surface_evolver


HEIGHT = "maximum_height_above_pad_mm"
FILLET = "fillet_volume_mm3"
PIN_ANGLE = "pin_apparent_contact_angle_deg"
PAD_ANGLE = "pad_apparent_contact_angle_deg"
LIQUID_ENERGY = "liquid_air_surface_energy_J"


def test_measurement_units_zero_and_percentage_error():
    data = measurements_from_csv(f"metric,value,unit,absolute_tolerance\n{HEIGHT},0,mm,.02\n{PIN_ANGLE},60,deg,5\n")
    comparison = compare_measurements({HEIGHT: .01, PIN_ANGLE: 66}, data)
    height, angle = comparison["observations"]
    assert height["absolute_percentage_error"] is None
    assert angle["absolute_percentage_error"] == pytest.approx(10)
    assert angle["absolute_difference"] == 6
    assert comparison["status"] == "failed"
    assert comparison["mean_normalized_squared_error"] == pytest.approx((.5**2 + 1.2**2)/2)
    with pytest.raises(ComponentError, match="must use mm"):
        measurements_from_csv(f"metric,value,unit,absolute_tolerance\n{HEIGHT},1,cm,.02\n")
    with pytest.raises(ComponentError, match="repeated"):
        measurements_from_csv(f"metric,value,unit,absolute_tolerance\n{HEIGHT},1,mm,.02\n{HEIGHT},2,mm,.02\n")


def test_contact_angle_measured_through_liquid_on_pad():
    vertices = np.array([[0, 0, 0], [0, 1, 0], [-np.sqrt(3), 0, 1], [-1, 0, 0]])
    faces = np.array([[0, 1, 2], [1, 0, 3]])
    normals = np.cross(vertices[faces[:, 1]] - vertices[faces[:, 0]],
                       vertices[faces[:, 2]] - vertices[faces[:, 0]])
    result = mesh_contact_angles(vertices, faces, np.array([1, 3]), normals, [PAD_ANGLE, PIN_ANGLE])
    assert result == {PAD_ANGLE: pytest.approx(30)}


def test_material_provenance_and_scaled_model(geometry_contract):
    props = {"surface_tension_N_per_m": .4, "density_kg_per_m3": 7500, "pin_contact_angle_deg": 75,
             "alloy": "SAC305", "provenance": {"surface_tension_N_per_m": {
                 "basis": "measured", "source": "TEST ONLY reference at test temperature"}}}
    parameters = normalize_materials({"material": props, "simulation": {
        "fillet_volume_mm3": .03, "volume_multiplier": .5, "gravity_m_per_s2": 10,
        "pin_contact_line": "pinned", "contact_angle_delta_deg": 10}})
    model, metadata, *_ = build_model(geometry_contract, parameters, {})
    assert metadata["contact_line_mode"] == "pinned"
    assert metadata["fillet_volume_mm3"] == pytest.approx(.015)
    assert metadata["parameters"]["material"]["provenance"] == props["provenance"]
    assert "parameter theta_pin = 85\n" in model
    gravity = next(line for line in model.splitlines() if line.startswith("gravity_constant"))
    assert float(gravity.split()[1]) == pytest.approx(7500 * 10 * 1e-6 / .4)
    props["provenance"]["surface_tension_N_per_m"].pop("source")
    with pytest.raises(ComponentError, match="Provide a source"):
        normalize_materials({"material": props})


@pytest.mark.protocol
def test_calibration_snapshots_inputs_and_finds_best_even_outside_tolerance(
        tmp_path, synthetic_step, fake_native_process):
    path = write_json(tmp_path / "pipeline.json", {
        "inputs": {"step_file": str(synthetic_step)},
        "steps": {"material_manager": {"simulation": {FILLET: .025}},
                  "cad_converter": {"enabled": False},
                  "surface_evolver": {"outputs": [FILLET, PIN_ANGLE, PAD_ANGLE, LIQUID_ENERGY]}},
    })
    param = f"steps.material_manager.simulation.{FILLET}"
    grid = write_json(tmp_path / "grid.json", {"require_cad_validation": False,
                      "parameters": {param: [0, .02, .03]}})
    data = write_json(tmp_path / "measurements.json", {"observations": {
        FILLET: {"value": .032, "unit": "mm^3", "absolute_tolerance": .0001},
    }})
    study = tmp_path / "study"
    report = calibrate(path, grid, data, study)
    assert report["status"] == "success"
    assert report["total_candidates"] == 3
    assert report["candidates"][0]["eligible"] is False
    assert report["best"]["parameters"] == {param: .03}
    assert report["best"]["measurement_agreement"] == "failed"
    assert (study / "inputs/original.step").read_bytes() == synthetic_step.read_bytes()
    config = read_json(study / "best_pipeline.json")
    assert config["steps"]["material_manager"]["simulation"]["provenance"][FILLET]["basis"] == "calibrated_effective"
    run = Path(report["best"]["experiment_dir"])
    selected = read_json(run / "simulation/selected_outputs.json")["outputs"]
    assert {row["metric"] for row in selected} == {FILLET, PIN_ANGLE, PAD_ANGLE, LIQUID_ENERGY}
    assert all(row["value"] is not None for row in selected)
    metrics = read_json(run / "simulation/metrics.json")
    assert metrics[LIQUID_ENERGY] == pytest.approx(.5e-6 * metrics["free_surface_area_mm2"])
    assert metrics["numerical_pass"]
    evaluation = read_json(run / "evaluation/automated_test_results.json")
    assert evaluation["passed"] and evaluation["measurements"]["status"] == "failed"
    assert evaluation["tests"][-1]["passed"] is False and evaluation["tests"][-1]["required"] is False
    assert config["inputs"]["measurements_file"] != str(data)


@pytest.mark.native
def test_native_selected_angles_and_gravity(geometry_contract, tmp_path):
    executable = find_executable()
    if executable is None:
        pytest.skip("A native Surface Evolver executable is required")
    results = []
    for index, gravity in enumerate((0, 980.0)):
        parameters = normalize_materials({"simulation": {"gravity_m_per_s2": gravity}})
        model, metadata, *_ = build_model(geometry_contract, parameters, {})
        path = tmp_path / f"gravity_{index}.fe"
        path.write_text(model, encoding="ascii")
        write_json(path.with_suffix(".json"), metadata)
        report = run_surface_evolver(path, {"executable": executable, "minimization_steps": 300,
                                     "outputs": [HEIGHT, PIN_ANGLE, PAD_ANGLE, LIQUID_ENERGY, FILLET],
                                     "require_numerical_pass": False}, tmp_path / f"solver_{index}")
        assert report["status"] == "success", report
        selected = read_json(report["outputs"]["selected_outputs"])
        outputs = {row["metric"]: row["value"] for row in selected["outputs"]}
        assert outputs[FILLET] == pytest.approx(.025, abs=2e-7)
        assert 0 < outputs[PIN_ANGLE] < 180
        assert 0 < outputs[PAD_ANGLE] < 180
        assert outputs[LIQUID_ENERGY] > 0
        results.append(outputs)
    assert results[1][HEIGHT] < results[0][HEIGHT] - .001


@pytest.mark.native
@pytest.mark.cad
def test_native_calibration_selects_best_fit(synthetic_step, tmp_path):
    if find_executable() is None:
        pytest.skip("A native Surface Evolver executable is required")
    config = write_json(tmp_path / "pipeline.json", {
        "inputs": {"step_file": str(synthetic_step)},
        "steps": {"material_manager": {"simulation": {FILLET: .025}}, "cad_converter": {"enabled": False},
                  "surface_evolver": {"minimization_steps": 500, "max_move_tolerance_mm": 1e-4,
                                      "outputs": [HEIGHT, FILLET]}},
    })
    parameter = f"steps.material_manager.simulation.{FILLET}"
    grid = write_json(tmp_path / "grid.json", {"require_cad_validation": False,
                      "parameters": {parameter: [.021, .025]}})
    data = write_json(tmp_path / "measurements.json", {"source": "Synthetic regression target", "observations": {
        FILLET: {"value": .024, "unit": "mm^3", "absolute_tolerance": .002},
    }})
    report = calibrate(config, grid, data, tmp_path / "study")
    assert [row["eligible"] for row in report["candidates"]] == [True, True], report
    assert report["best"]["parameters"] == {parameter: .025}
    assert report["best"]["measurement_agreement"] == "passed"
