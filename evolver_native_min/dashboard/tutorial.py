"""In-app walkthrough for the supplied Pico example and pipeline reference."""
import json
from pathlib import Path

import streamlit as st

from pcbsim.common import read_json, resolve_path
from pcbsim.components.observables import DEFAULT_OUTPUTS, OBSERVABLES

import job_runner as runner
from configuration import load_advanced_draft


def load_run_six(config_text: str) -> None:
    load_advanced_draft(config_text, runner.base_config_path().parent)
    st.toast("Run 6 loaded in Inputs & Configuration.")


def load_pico_sample(config: dict) -> None:
    st.session_state["pending_guided_config"] = (config, runner.base_config_path().parent)


def show_simulation_reference() -> None:
    with st.expander("Mesh and solver settings"):
        st.markdown("""
The **mesh** is the set of triangles that represents the solder surface. The **solver**
moves the triangles’ vertices to find a lower-energy shape at the specified volume.

| Initial mesh input | What it does |
| --- | --- |
| **Initial radial segments** | Sets the number of divisions from the pin toward the pad edge. More divisions give a finer starting mesh across the fillet. |
| **Initial segments per pin side** | Sets the number of divisions along each side of the rectangular pin. This also sets the sampling around the circular pad and hole. |
| **Maximum pad chord error (mm)** | Limits the gap between the circular pad edge and its straight mesh segments. If generation fails this check, increase **Initial segments per pin side**. |
| **Initial perturbation amplitude (mm)** | Sets the maximum random vertical offset applied to free interior vertices before the starting volume is restored. Enter **0** for the regular starting mesh. |
| **Initial perturbation seed** | Repeats the same random offsets when the amplitude and other mesh settings are the same. Try a different seed to test sensitivity to the starting shape. |

| Relaxation input | What it does |
| --- | --- |
| **Mesh refinements** | Counts the rounds of triangle subdivision during relaxation. Enter **0** to keep the initial resolution. More refinements increase the number of triangles and runtime. |
| **Initial relaxation steps** | Sets the number of warmup steps before refinement or convergence testing. Enter **0** to skip warmup. |
| **Minimization steps per pass** | Sets the number of energy-lowering steps in each relaxation pass. Passes occur after refinement, before the first check when refinements are zero, and between failed check batches. |
| **Conjugate gradient** | Uses previous steps to help choose the next direction of movement during energy minimization. |
| **Improve free-surface mesh between retries** | Rearranges edges shared by two exposed solder triangles before retrying relaxation. This can improve triangle shapes while preserving the contact boundaries. |
| **Solver timeout (s)** | Sets the time limit for the native Surface Evolver process. The partial solver log is kept if it times out. |

| Convergence input | What it does |
| --- | --- |
| **Convergence window steps** | Sets how many steps the solver watches for changes in energy and vertex position during each check. |
| **Maximum check batches** | Caps the number of convergence checks, including retries. |
| **Consecutive passing checks** | Sets how many checks must pass in a row. Use at least **2**, up to the maximum number of check batches. |
| **Relative volume tolerance** | Sets the allowed volume difference divided by the target volume. For example, `1e-7` is a fraction, equivalent to `0.00001%`. |
| **Scaled energy drift tolerance** | Sets the allowed energy change over a check window, divided by one plus the magnitude of the final scaled energy. |
| **Maximum movement tolerance (mm)** | Limits how far any mesh vertex may move from the start to the end of a check window. |

Start with the Pico settings. To check mesh sensitivity, increase the mesh
resolution and compare quantities such as height or contact angle between runs.
Convergence checks how much the result is still changing on the current mesh.
""")

    descriptions = {
        "maximum_height_above_pad_mm": "Height of the highest point above the top pad plane.",
        "fillet_volume_mm3": "Final volume above the pad. The solver constrains it through the specified solder volume.",
        "volume_mm3": "Final volume of the top fillet and the fully filled barrel together.",
        "free_surface_area_mm2": "Area of the exposed solder surface in contact with air.",
        "wetted_pin_area_mm2": "Area of the pin wall covered by solder above the pad.",
        "pin_apparent_contact_angle_deg": "Average angle through the solder where its exposed surface meets the pin.",
        "pad_apparent_contact_angle_deg": "Average angle through the solder at the fixed outer pad edge.",
        "barrel_volume_mm3": "Volume of solder inside the fixed plated hole around the pin.",
        "total_shell_area_mm2": "Area of the entire solder boundary, including enclosed contact surfaces.",
        "liquid_air_surface_energy_J": "Liquid surface tension multiplied by the exposed area in square meters.",
        "energy_J": "The modeled energy Surface Evolver minimizes, including exposed surface, pin wetting, and gravity when enabled.",
        "pressure_Pa": "How much the modeled energy changes per small increase in allowed solder volume at equilibrium.",
        "volume_relative_error": "Absolute difference between final and target volume, divided by target volume.",
        "energy_drift_relative": "Scaled change in energy during the final convergence check.",
        "max_move_mm": "Largest vertex displacement from the start to the end of the final check.",
        "convergence_checks": "Total convergence checks attempted, including passing and failed checks.",
    }
    categories = {
        "Geometry": "Dimensions and angles of the predicted joint. Apparent contact angles are estimated from the mesh.",
        "Derived model quantity": "Energy and pressure values calculated from the simulation and its physical inputs.",
        "Solver diagnostic": "Numbers that show how closely the solver met its volume and convergence criteria.",
    }
    with st.expander("Numerical output options"):
        defaults = ", ".join(OBSERVABLES[key].label.lower() for key in DEFAULT_OUTPUTS)
        st.markdown(f"Choose any combination for the **Results** table and CSV or JSON downloads. "
                    f"The default selection is {defaults}. The solver retains its required diagnostics in every run.")
        for category, meaning in categories.items():
            st.markdown(f"**{category}**  \n{meaning}")
            rows = [
                f"| {metric.label} | {'unitless' if metric.unit == '1' else metric.unit} | {descriptions[key]} |"
                for key, metric in OBSERVABLES.items() if metric.category == category
            ]
            st.markdown("\n".join(["| Option | Unit | What it tells you |", "| --- | --- | --- |", *rows]))


def show_tutorial() -> None:
    config = read_json(Path(__file__).with_name("run_006.json"))
    config["inputs"]["step_file"] = str(runner.app_dir().resolve() / "inputs/raspberry_pico_2H.step")
    config["experiments_dir"] = str(runner.data_dir().resolve() / "experiments")
    config_text = json.dumps(config, indent=2) + "\n"
    sample = json.loads(config_text)
    sample["inputs"]["step_file"] = str(resolve_path(
        runner.base_config()["inputs"]["step_file"], runner.base_config_path().parent))
    sample["steps"]["surface_evolver"]["outputs"] = [
        *DEFAULT_OUTPUTS, "pin_apparent_contact_angle_deg", "liquid_air_surface_energy_J",
    ]

    st.subheader("Run your first experiment")
    st.markdown("""
This sample simulates one top-side solder joint on connection **1** of the supplied
Raspberry Pi Pico assembly. It uses illustrative material values. The geometry,
solver, and STEP export all run inside the project’s Docker container.
""")
    st.button("Load Pico sample into Guided setup", on_click=load_pico_sample, args=(sample,),
              type="primary", help="Replaces the Guided setup draft with the sample settings.")
    st.markdown("""
1. Select **Load Pico sample into Guided setup** to open **Inputs & Configuration**
   with the sample filled in. You can also enter the values below manually.
2. Review the selected quantities under **Numerical outputs**. Keep **Export and
   validate STEP** checked to produce the solder-only and combined PCB STEP files.
3. Select **Run experiment**. The stage table shows progress. If a stage fails,
   open **Logs and settings** for the error and native solver output.
4. In **Results**, select the run to inspect the predictions, view the assembly,
   or download the selected outputs as CSV or JSON. The run folder is saved under
   `data/experiments/` on the host.
""")
    with st.expander("Enter the sample settings manually"):
        st.markdown("""
| Guided setup section | Sample setting |
| --- | --- |
| PCB source | **Supplied Pico example**, connection index **1** |
| Material | **Custom / illustrative**, surface tension **0.5 N/m**, liquid density **7400 kg/m³**, pin Young angle **80°**. Set each basis to **Assumed**. |
| Simulation physics and boundaries | Top-fillet volume **0.025 mm³**, gravity **0 m/s²**, volume multiplier **1**, pin angle offset **0°**, pin contact line **mobile** |
| Mesh and solver | **5** radial segments, **8** segments per pin side, **1** refinement, **1000** minimization steps per pass. Keep the other supplied defaults. |
| Numerical outputs | Choose height above pad, top-fillet volume, total solder volume, liquid–air surface area, and optionally mean apparent pin contact angle and liquid–air surface energy. |
""")
    with st.expander("Upload and reuse an example material"):
        st.markdown("""
This JSON contains the Pico sample’s illustrative liquid surface tension, liquid
density, and pin Young contact angle. Each value is labeled **Assumed**.
""")
        example = Path(__file__).with_name("example_material.json")
        st.download_button("Download example material JSON", example.read_bytes(),
                           file_name=example.name, mime="application/json", on_click="ignore")
        st.markdown("""
1. Download the example JSON above. Go to **Inputs & Configuration → Guided setup**
   and expand **Saved material presets**.
2. Under **Material preset JSON**, upload `example_material.json` and select
   **Load material**. The **Material** section will show **Pico tutorial solder**
   with the three properties filled in.
3. Select **Save material preset** to keep a copy. Clear the uploaded file using
   its **×** button, then choose **Pico tutorial solder** from **Saved material**
   and select **Load material** to reuse it.

Use **Saved material** for your saved presets. **Alloy preset** lists the built-in
alloy choices.
""")
    with st.expander("Compare a measurement and rerun"):
        st.markdown("""
1. Open **Evaluation & Calibration** and choose the completed Pico run.
2. Under **Enter or load measurements**, select **Enter values** and choose
   **Maximum height above pad (mm)** under **Observed quantities**. For a practice
   comparison, enter a synthetic height of **0.060 mm** and an absolute tolerance
   of **0.005 mm**. Record the source as **Synthetic tutorial example** and select
   **Use measurements**. Use actual observations from a matching joint for an
   experimental comparison.
3. Review the prediction, absolute and percentage errors, and error relative to
   tolerance. Select **Edit settings and rerun** to carry the comparison dataset
   into a new run.
""")
    with st.expander("Start the dashboard with Docker"):
        st.markdown("From the repository root, run the command below and open [the dashboard](http://localhost:8501). "
                    "Compose mounts the host’s `data/` folder at `/data` and supplies the native solver.")
        st.code("docker compose -f docker/compose.yaml up -d --build", language="bash")

    st.subheader("Recreate archived Experiment Run 6")
    st.markdown("""
The archived run simulated one top-side solder joint on connection **1**
of the supplied Raspberry Pi Pico assembly. The example uses the archived
settings with the input path, run directory, and solver discovery adapted for Docker.

1. Select **Load Run 6 into Advanced JSON**.
2. Leave **Stop after** at **Last enabled stage** and **Run only these stages**
   empty. Optionally enter a fresh experiment ID, such as `run_006_docker`.
3. Select **Run configured experiment**. When all six stages finish, download
   the PCB assembly with solder, or use **Show intermediate files and reports**
   to download the solver metrics and evaluation report.
""")
    st.button("Load Run 6 into Advanced JSON", on_click=load_run_six, args=(config_text,),
              help="Replaces the Advanced JSON draft with the example.")
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

If your checkout contains the archive, open **Results**, enter
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
    show_simulation_reference()
    with st.expander("Inputs, paths, and run controls"):
        st.markdown("""
- **Guided setup** lets you choose a STEP assembly and connection, edit material
  properties and their sources, set boundaries and solver parameters, and choose outputs.
- **Copy to Advanced JSON** opens the current Guided setup settings in the JSON
  editor. Enter an **Experiment ID** there to name the run, then select
  **Run configured experiment** when ready.
- **Evaluation & Calibration** compares geometry predictions with manual or
  uploaded measurements. Load a previous configuration for a manual rerun or
  run a bounded grid search and load the best eligible settings.
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
