"""Exercise the separate FreeCAD runtime and the shared STEP contract."""

import os
from pathlib import Path
import subprocess

import pytest

from pcbsim.common import read_json, sha256


def test_freecad_debug_pico(tmp_path):
    python = os.getenv("PCBSIM_FREECAD_PYTHON")
    if not python:
        pytest.skip("The project's Docker image provides the headless FreeCAD runtime")
    root = Path(__file__).resolve().parents[2]
    pipeline = root / "pcbsim_pipeline" if (root / "pcbsim_pipeline").is_dir() else root
    source = pipeline / "inputs/raspberry_pico_2H.step"

    def run(mode, output, *options):
        subprocess.run([python, "-m", "dashboard.3d_visualize_cad.cad_debug", mode,
                        "--input-step", str(source), "--output-dir", str(output),
                        "--config", str(pipeline / "pipeline.json"), *options],
                       cwd=root, check=True, timeout=120, env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
        return read_json(output / "scene.json")

    original = run("inspect", tmp_path / "original")
    assert original["detection_error"] is None
    assert len(original["solids"]) == 420
    assert [row["pin_index"] for row in original["connections"]] == list(range(1, 41))
    assert {row["role"] for row in original["solids"]} == {"pad", "pcb", "pin", "other"}
    assert all(row["positions"] and row["indices"] for row in original["solids"])

    for pin in (5, 40):
        output = tmp_path / f"pin_{pin}"
        extracted = run("extract", output, "--pin-index", str(pin))
        assert extracted["pin_index"] == pin
        assert extracted["validation"]["passed"], extracted["validation"]
        assert {row["role"] for row in extracted["solids"]} == {"pad", "pcb", "pin"}
        geometry = read_json(output / "geometry.json")
        assert geometry["selection"] == original["connections"][pin - 1]
        assert geometry["source"]["sha256"] == original["source_sha256"] == sha256(source)
        assert geometry["extracted_step_sha256"] == sha256(output / "extracted.step")
