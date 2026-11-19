"""In-app pipeline reference and a runnable preset from the Run 6 archive."""
import json
from pathlib import Path

import streamlit as st

from pcbsim.common import read_json

import job_runner as runner


def load_run_six(config_text: str) -> None:
    st.session_state.update(
        config_mode="Advanced JSON",
        config_editor=config_text,
        config_base=str(runner.base_config_path().parent),
        config_experiment_id="",
        config_stop_after=None,
        config_only=[],
        config_upload_keys=[],
    )
    st.session_state.pop("config_upload_error", None)
    st.toast("Run 6 loaded. Open Run experiment to review and start it.")


def show_tutorial() -> None:
    config = read_json(Path(__file__).with_name("run_006.json"))
    config["inputs"]["step_file"] = str(runner.app_dir().resolve() / "inputs/raspberry_pico_2H.step")
    config["experiments_dir"] = str(runner.data_dir().resolve() / "experiments")
    config_text = json.dumps(config, indent=2) + "\n"
    st.subheader("Recreate Experiment Run 6")
    st.markdown("""
The archived run simulated one top-side solder joint on connection **1**
of the supplied Raspberry Pi Pico assembly. The example uses the archived
settings with the input path, run directory, and solver discovery adapted for Docker.

1. Select **Load Run 6 into Advanced JSON**, then open **Run experiment**.
2. Leave **Stop after** at **Last enabled stage** and **Run only these stages**
   empty. Optionally enter a fresh experiment ID, such as `run_006_docker`.
3. Select **Run configured experiment**. When all six stages finish, download
   the PCB assembly with solder, or use **Show intermediate files and reports**
   to download the solver metrics and evaluation report.
""")
    st.button("Load Run 6 into Advanced JSON", on_click=load_run_six, args=(config_text,),
              type="primary", help="Replaces the Advanced JSON draft with the example.")
    st.download_button("Download Run 6 JSON", config_text, file_name="pipeline.run_006.json",
                       mime="application/json", on_click="ignore")
    with st.expander("View Run 6 settings"):
        st.markdown("""
| Setting | Run 6 |
| --- | --- |
| Source and selection | Pico STEP, geometric connection 1, 3 mm crop |
| Solder | 0.025 mm³ above the pad, full barrel, mobile pin contact line |
| Material | 80° pin contact angle, 0.5 N/m surface tension, 7,400 kg/m³ density |
| Initial mesh | 5 radial segments, 8 segments per pin side, zero perturbation |
| Solver | Zero gravity, one refinement, 30 warmup steps, 1,000 steps per relaxation batch |
| Convergence | 30-step checks with two consecutive passes, up to ten checks |
""")
        st.code(config_text, language="json")

    with st.expander("Check your result against the archived run", expanded=True):
        st.markdown("""
| Check | Archived Run 6 |
| --- | ---: |
| Maximum height above pad | 0.057084 mm |
| Top-fillet volume | 0.025000 mm³ |
| Total solder volume | 0.432190 mm³ |
| Free-surface area | 1.132038 mm² |
| Pressure | 68.05 Pa |
| Solids in combined STEP | 421 (420 original solids and one solder solid) |

Check for a passing numerical gate in **Solver metrics** and passing checks in
**Evaluation report**. These values are equilibrium predictions. Expect small
numerical differences between solver builds.

If your checkout contains the archive, open **Experiments**, enter
`/data/archive/pre-docker/pcbsim_pipeline/experiments` as the experiment
directory, and select `run_006` to inspect the original outputs.
""")

    with st.expander("Try a shorter run or change one parameter"):
        st.markdown("""
- **Build the initial model.** Load Run 6 and set **Stop after** to
  **Generate model**. Run it, then download the **Surface Evolver model** and
  **Initial mesh**. This ends before relaxation and STEP export.
- **Compare solder charges.** Load Run 6 and change
  `steps.material_manager.simulation.fillet_volume_mm3` from `0.025` to
  `0.020`. Run all six stages with a fresh experiment ID. Compare the height
  above the pad and free-surface area with your baseline.
""")

    st.subheader("Pipeline reference")
    with st.expander("Inputs, paths, and run controls"):
        st.markdown("""
- **Quick setup** lets you choose a STEP assembly, connection index,
  top-fillet volume, and contact angle.
- **Advanced JSON** exposes the full config. `inputs` contains source and
  intermediate files. `steps` contains each stage’s settings, including its
  `enabled` flag. **Attach input files** replaces the selected `inputs` paths
  with uploads.
- **Stop after** ends at a stage. **Run only these stages** runs the selected
  enabled stages in pipeline order. Supply any needed intermediate files
  when skipping the stage that would produce them.
- The **Base directory for relative paths** applies to paths in the editor.
  `/data` maps to the host’s `data/` folder. `experiments_dir` sets the
  output root, and **Experiment ID** names a new folder within it.
- Set `steps.cad_converter.output_filename` to name the combined STEP within
  `output/`. The pipeline assigns its other artifact names.
""")
    with st.expander("Stages and their outputs"):
        st.markdown("""
| Stage | Main outputs |
| --- | --- |
| Extract connection | Connection catalog, extracted STEP, and geometry with the placement transform |
| Set solder properties | Normalized materials and simulation parameters |
| Generate model | Surface Evolver data file, metadata, and initial mesh |
| Relax solder surface | Relaxed mesh, solver metrics, and native log |
| Export STEP | Combined PCB assembly, solder-only solid, and conversion report |
| Evaluate result | Automated checks and optional comparison with measured observations |

`exp_report.json` records stage status and output paths. `input/config.json`
records the effective settings. If a run fails, open **Logs and settings**
and start with the failed stage. For extraction errors, confirm the index is
from the geometric catalog and the STEP contains a compatible plated hole and
rectangular pin.
""")
