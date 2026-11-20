# Solder Joint Simulation Guide

## What it models

The pipeline predicts the equilibrium shape of one solder joint around a PCB through-hole pin. It extracts the actual pin, plated hole, and surrounding pad from a STEP assembly, then uses Surface Evolver to settle the solder into a shape that minimizes surface and wetting energy while preserving its volume.

1. **Extract the connection:** select one rectangular pin and its circular hole and pad from the PCB assembly.
2. **Define the solder:** specify the top-fillet volume and material properties: surface tension, density, and pin contact angle.
3. **Relax the surface:** allow the solder shape and pin contact line to move until volume, energy, and movement checks pass.
4. **Export the result:** save the solder alone and the original PCB assembly with the solder added as a separate solid. The input CAD file is unchanged.

The model assumes a fully filled, stationary barrel and one top-side fillet. Its limits matter when choosing measurements and interpreting results:

- The outer solder contact line is fixed at the pad perimeter; the pin contact line can move on the straight pin walls.
- Solder volume settings change the top fillet, not the filled barrel.
- The simulation does not predict heating, flow over time, cooling, solidification, or joint strength.
- The exported solder is a faceted solid, represented by triangular faces.
- With gravity disabled, density and surface tension do not affect shape. Surface tension still sets the energy and pressure scales. Volume and the pin Young contact angle affect shape when the pin contact line is mobile.
- Default material values are illustrative, not calibrated to a particular alloy or process.

## Dashboard workflow

### Run the supplied Pico sample

1. Start the Docker dashboard using the [setup guide](SETUP.md). Open **Experiments → Tutorial & Documentation** and select **Load Pico sample into Guided setup**.
2. Confirm **Supplied Pico example** and connection index **1** in **Inputs & Configuration**. The sample uses **0.025 mm³** of solder above the pad, **0 m/s²** gravity, a mobile pin contact line, and illustrative material inputs of **0.5 N/m**, **7400 kg/m³**, and **80°**. Keep **Export and validate STEP** checked.
3. Select **Run experiment** and follow the stage table. Open **Results** to view the assembly and download the selected outputs and STEP files. Runs are saved under `data/experiments/` with sequential names such as `run001` and `run002`.
4. To practice the comparison, select the completed run in **Evaluation & Calibration**. Enter a synthetic maximum height above pad of **0.060 mm** with an absolute tolerance of **0.005 mm**, then select **Use measurements**. Use observations from a matching joint for an experimental comparison.

### Configure your own run

1. **Configure.** Open **Inputs & Configuration → Guided setup**. Choose a STEP assembly and the geometric connection index. Use the illustrative material for an example run, or select SAC305, Sn63Pb37, or a custom material. Built-in alloy presets cite composition from the [Indium Corporation bar-solder data](https://www.indium.com/products/bar-solder/). Review or enter liquid surface tension in N/m, liquid density in kg/m³, and the Young angle through the liquid on the pin finish in degrees. For each value, choose its basis and record the reference, temperature, and relevant surface, flux, or atmosphere conditions.
2. **Simulate.** Set the top-fillet volume in mm³, downward gravity in m/s², and whether the pin contact line can slide. The volume multiplier and angle offset modify the base inputs. Under **Mesh and solver**, set resolution, relaxation steps, convergence tolerances, and timeout. Select the quantities to export under **Numerical outputs**. **Export and validate STEP** adds the CAD stage. **Run experiment** creates a new run. **Results** offers the selected output CSV and JSON, STEP files, solver logs, and the full numerical receipt.
3. **Evaluate.** Open **Evaluation & Calibration**, choose the run, and enter observations or load a JSON or CSV dataset. Each observation uses the units shown beside its quantity and includes a positive absolute tolerance. CSV uses the headers `metric,value,unit,absolute_tolerance`, with one row per metric. Use `mm`, `mm^2`, `mm^3`, or `deg` as appropriate. The comparison shows absolute error, absolute percentage error (blank when the measured value is zero), and signed error divided by tolerance.
4. **Calibrate and rerun.** Use **Edit settings and rerun** to load the reference experiment’s configuration and carry its dataset forward. To search automatically, select uncertain parameters and enter comma-separated values for each. The search runs every combination up to the limit you set. Candidates must pass numerical checks and any enabled STEP validation. The lowest mean squared tolerance-normalized error wins, even if some observations remain outside tolerance. Review the candidate history and select **Load best-fit settings for rerun**. Fitted inputs are labeled **Calibrated effective** and link to their study.
5. **Save and revisit.** Use **Save material preset**, **Save configuration**, **Save dataset**, and **Save comparison**. Their JSON records live under `data/materials/`, `data/configurations/`, `data/measurements/`, and `data/comparisons/`. Use the matching load controls or download the JSON. A calibration study in `data/calibrations/` saves its input snapshots, measurements, trial grid, ordered results, each candidate’s experiment, and its best-fit configuration. Saved dashboard configurations use absolute paths inside the container. Keep the experiment or study directories with their inputs, or rebase file paths before reusing them in a different environment.

**Advanced JSON** retains all stage and intermediate-artifact controls. It also accepts `steps.surface_evolver.outputs`, a list of metric keys. Omitting the list selects height, top-fillet volume, total volume, and liquid–air area by default. The pipeline still writes its existing `simulation/metrics.json` receipt, including all required solver diagnostics. The selected quantities are in `simulation/selected_outputs.json`.

To name a run configured in **Guided setup**, select **Copy to Advanced JSON**. This replaces the Advanced JSON draft with your current settings and opens the editor. Enter an **Experiment ID** and select **Run configured experiment** when ready. **Save configuration** stores a reusable copy on the server.

### SAC305 starter properties

Selecting **SAC305** fills in two editable literature values for molten solder at **250 °C**. The pin Young contact angle is entered separately for the actual pin finish and soldering conditions. Existing saved configurations keep their explicit values.

- **Liquid surface tension, 0.4337 N/m.** Published value for nominal SAC305, converted from 433.7 mN/m. [Caribe Couvertier et al., Table 3](https://doi.org/10.3390/electronicmat7030019)
- **Liquid density, about 7290 kg/m³.** Rounded from the published linear fit, using 7320 kg/m³ at 493 K and a decrease of 0.86 kg/m³ per kelvin up to 523.15 K. [Varanasi and Pal, Table 2](https://doi.org/10.1007/s11106-021-00262-w)

### Upload and reuse a material preset

1. Open **Tutorial & Documentation → Upload and reuse an example material** and select **Download example material JSON**. You can also get the file from the [repository](../dashboard/example_material.json). It uses the Pico sample’s illustrative values of **0.5 N/m** liquid surface tension, **7400 kg/m³** liquid density, and **80°** pin Young contact angle, all marked **Assumed**.
2. Open **Inputs & Configuration → Guided setup → Saved material presets**. Upload the file under **Material preset JSON** and select **Load material**. Check that the **Material** section displays **Pico tutorial solder**.
3. Select **Save material preset** to save it on the dashboard server. For future runs, clear any attached file from the uploader, choose **Pico tutorial solder** from **Saved material**, and select **Load material**. The **Alloy preset** dropdown contains the built-in alloy choices.

To create a preset file, copy the example JSON and edit the name and the three properties inside `material`. The keys are `surface_tension_N_per_m`, `density_kg_per_m3`, and `pin_contact_angle_deg`. Use the units given in the keys and update each property’s `provenance` to reflect where its value came from.

### How to interpret outputs and physical inputs

- **Comparable geometry:** height is measured above the top pad plane. Total solder volume includes the fixed barrel. The simulated top-fillet volume is prescribed, so agreement in volume primarily checks the solder amount and volume constraint. Match the definition of liquid–air area, wetted pin area, and total shell area to the measurement method.
- **Apparent contact angles:** the pin and pad values are edge-length-weighted estimates through the liquid, computed from adjacent free-surface and wall triangles. They depend on local geometry and mesh resolution. They are unavailable without labeled, shared contact edges. A microscopic, advancing, or receding contact angle requires different modeling or measurements. The input Young angle supplies the mobile pin’s wetting energy. The apparent pad angle can be estimated from the pinned boundary, but the pad angle cannot be prescribed independently or used to model pad spreading.
- **Derived model quantities:** liquid–air energy is `γ × A_liquid–air` with area in m². The solver’s total modeled energy adds the relative pin wetting energy and gravity, using its own energy reference. Body pressure is the volume constraint multiplier in pressure units. These quantities are exported separately from the directly comparable geometry and from numerical residuals.
- **Scaling and boundary conditions:** with millimeter coordinates, energy is scaled by `γ × (10⁻³ m)²`, pressure by `γ / (10⁻³ m)`, and the Evolver gravity coefficient is `ρ g (10⁻³ m)² / γ`. The normalized free-surface and wetted-pin facet tensions are `1` and `−cos(θ)`. A pinned pin line stays at the height calculated for the initial mesh and volume. The fixed pad edge, fully filled barrel, top-only fillet, and straight pin walls constrain all runs. See the [Surface Evolver energy documentation](https://kenbrakke.com/evolver/html/energies.htm) and [manual](https://kenbrakke.com/evolver/downloads/manual270.pdf).
- **Fitting limits:** shape alone at zero gravity cannot identify liquid density or surface tension. At nonzero gravity the geometry responds to their ratio with gravity, so varying all three together can produce indistinguishable shapes. Use independent property measurements and inspect ties and tolerance failures. Contact angle fitting requires a mobile pin line, and a result at the straight-pin height limit may be affected by the omitted bevel. Viscosity, temperature evolution, flux chemistry, pin-tip wetting, a bottom meniscus, and partial barrel fill are outside this equilibrium model.

## Run it

Use `pipeline.json` to select the geometry, material settings, and solver settings. Each execution creates a new experiment directory, preserving earlier results. Complete [SETUP.md](SETUP.md) first; the full pipeline needs the Python environment, CAD dependencies, and a real Surface Evolver executable.

1. **Choose the inputs** in `pcbsim_pipeline/pipeline.json`:
   - `inputs.step_file`: PCB STEP file. Relative input paths are resolved from the configuration file's folder.
   - `steps.cad_extractor.selection.pin_index`: connection to extract. This is a geometric catalog index, not an electrical pin number.
   - `steps.surface_evolver.executable`: leave at `auto` to use the solver supplied by the image.
2. **Set the solder properties** under `steps.material_manager`:
   - `material.pin_contact_angle_deg`: wetting condition on the pin.
   - `material.surface_tension_N_per_m` and `material.density_kg_per_m3`: material properties at the relevant temperature.
   - `simulation.fillet_volume_mm3`: top-fillet solder volume.
   - `simulation.gravity_m_per_s2`: gravity; zero disables it.
3. **Run the pipeline** from the repository root using Docker:

```sh
docker compose -f docker/compose.yaml run --rm pipeline python run_pipeline.py --config /app/pipeline.json
```

   The dashboard baseline config is mounted from the checkout. **Tutorial & Documentation** includes a runnable Run 6 example.

4. **Inspect the new run folder** under `data/experiments/`:
   - `exp_report.json`: overall outcome and any failed stage.
   - `output/pcb_with_solder.step`: original PCB assembly plus the solder joint.
   - `output/solder_only.step`: solder alone, including the filled barrel; no PCB or pin solid.
   - `simulation/metrics.json`: predicted quantities and convergence results.
   - `simulation/stdout.log`: solver details if the run fails.

For example, changing the existing `pin_contact_angle_deg` from `80` to `75` changes the wetting condition. Changing `fillet_volume_mm3` from `0.025` to `0.030` adds top-fillet solder. To understand each effect:

- Change one setting at a time and rerun.
- Compare the resulting height and shape with the previous run.
- Keep known geometry and measured solder amounts fixed during material calibration.
- Use the relaxed simulation output; `initial_mesh.off` is only the starting shape.

## Validate results

Validation asks whether the result is geometrically sound, numerically settled, and representative of a real joint. The pipeline checks numerical convergence and CAD consistency automatically. Mesh sensitivity, suitability of the physical assumptions, and agreement with real joints require additional comparisons.

1. **Confirm the geometry:** check the selected pin, hole, pad, dimensions, orientation, and assumed barrel fill. Make sure the solder does not penetrate the PCB or pin.
2. **Confirm convergence:** inspect `simulation/metrics.json` for `numerical_pass`, volume error, energy drift, and maximum movement. The solver requires consecutive passing checks before conversion. A completed solver process alone is insufficient.
3. **Check resolution sensitivity:** repeat with finer `radial_segments`, `segments_per_pin_side`, or `refinements`, changing one at a time. Important predictions such as fillet height should stabilize. Also try different small initial surface perturbations to check dependence on the starting shape.
4. **Check the export:** reopen the STEP. Confirm the solder is a valid solid, its shape matches the relaxed result, and the original PCB assembly is preserved.
5. **Compare with measurements:** use joints with matching geometry, solder amount, alloy, and process conditions. Choose tolerances based on measurement uncertainty and the accuracy needed.

The measurement interface compares numerical quantities supplied in JSON; it does not extract measurements from photographs or scans. To compare an existing run:

1. Save a file such as `data/my_measurements.json`. Replace the example numbers with actual measurements. Height is measured above the pad plane in millimeters.

```json
{
  "schema_version": 1,
  "observations": {
    "maximum_height_above_pad_mm": {
      "value": 0.060,
      "absolute_tolerance": 0.005
    }
  }
}
```

2. From the project root, evaluate a completed run. Replace `run001` with your run.

```sh
docker compose -f docker/compose.yaml run --rm pipeline python -m pcbsim.components.evaluation --config /app/pipeline.json evaluate --experiment /data/experiments/run001 --measurements /data/my_measurements.json
```

3. Read `evaluation/automated_test_results.json` inside that run. For the example, a prediction of `0.057 mm` differs by `0.003 mm`, so it passes the `0.005 mm` tolerance. Passing this comparison establishes agreement for that quantity, not every aspect of the joint.
4. Add supported geometry observations such as `fillet_volume_mm3`, `volume_mm3` (barrel plus fillet), or `free_surface_area_mm2`. Each observation needs a `value` and a positive `absolute_tolerance` in the named units. The CLI also accepts references for derived energy and pressure quantities when their definitions match. Full profile or scan comparisons require separate analysis.

## Calibrate materials

Calibration adjusts uncertain physical settings to reduce disagreement with measured joints. Start with known alloy properties and solder amounts, fit uncertain wetting behavior, then check the fitted settings against joints that were not used for fitting. Calibration does not add missing physics or guarantee accuracy outside the conditions represented by the data.

1. **Define the conditions:** record alloy, soldering temperature, surface finishes, flux conditions, and joint geometry. Contact angle reflects the interacting surfaces and process, not the alloy alone.
2. **Collect measurements:** measure suitable quantities, such as fillet height, with realistic uncertainty. Use the JSON format above. Keep measured solder volume and known material properties fixed where possible.
3. **Choose uncertain settings:** typically start with pin contact angle. Define plausible candidate values rather than changing unrelated settings to force a match.
4. **Run candidate simulations:** the calibration tool tries every combination in a bounded parameter grid. CLI studies require CAD validation by default. For a solver-only study, disable `steps.cad_converter.enabled` in the baseline and set `require_cad_validation: false` in the grid JSON. All studies require a passing numerical gate.
5. **Rank agreement:** differences are divided by the supplied tolerances, squared, and averaged. A smaller score means a closer match relative to those tolerances.
6. **Check acceptance:** the best candidate is only the best among the values tried. Confirm whether it actually meets the measurement tolerances; the tool can select a best candidate even when all candidates disagree too much.
7. **Verify independently:** apply the selected settings to separate measured joints without refitting. Compare additional geometries or solder amounts before treating the calibration as broadly applicable.

For example, with known solder volume, fit only the pin contact angle using three candidates. The following steps use the hypothetical measurement file above to illustrate operation; they do not constitute real calibration data.

1. Save `data/my_calibration_grid.json`.

```json
{
  "maximum_runs": 3,
  "parameters": {
    "steps.material_manager.material.pin_contact_angle_deg": [75, 80, 85]
  }
}
```

2. From the project root, run the study into a new or empty output directory.

```sh
docker compose -f docker/compose.yaml run --rm pipeline python -m pcbsim.components.calibration --config /app/pipeline.json --grid /data/my_calibration_grid.json --measurements /data/my_measurements.json --output-dir /data/calibration/study_001
```

3. Inspect `data/calibration/study_001/calibration_report.json` for candidate errors, eligibility, and measurement agreement. If an eligible candidate exists, `best_pipeline.json` contains its settings.
4. Review the selected settings before using them. To run the selected configuration separately:

```sh
docker compose -f docker/compose.yaml run --rm pipeline python run_pipeline.py --config /data/calibration/study_001/best_pipeline.json
```

5. If the closest candidate is still outside tolerance, refine the plausible parameter range or reconsider measurements and model assumptions. Do not loosen tolerances simply to declare success.

Some properties cannot be inferred from the current shape model. Keep these limits in mind:

- With gravity disabled, shape alone cannot identify surface tension or density; use independent property measurements or reliable property data.
- The fixed pad perimeter prevents fitting an independent pad contact angle or predicting unrestricted spreading across the pad.
- Partial barrel fill, bevel wetting, and thermal effects require an extended model, not just adjusted settings.

## Experiment 6: one simulated through-hole solder joint

Experiment `run_006`, completed on November 11, 2026, ran the full pipeline on one connection in the supplied Raspberry Pi Pico STEP assembly. It produced a numerically settled solder joint and valid CAD exports. The following settings and results come from that experiment's saved files, rather than the current configuration.

### What it modeled

This experiment modeled the equilibrium solder shape around a single rectangular header pin, with a full barrel and one top-side fillet. It retained the original PCB geometry and added the calculated solder as a separate solid.

- **Selected connection:** geometric catalog index `1` from `raspberry_pico_2H.step`; only this connection received simulated solder.
- **Pin:** `0.64 x 0.64 mm` rectangular cross-section, centered in the hole.
- **Plated bore:** `0.50 mm` radius and `1.10 mm` depth; the PCB drill radius before plating was `0.55 mm`.
- **Pad:** `0.70 mm` outer radius; extraction included a `3 mm` PCB section.
- **Contact boundaries:** fixed outer pad perimeter and a mobile contact line on the straight pin walls. The allowable straight-wall height was `0.15 mm` above the pad; bevel wetting was excluded.
- **Placement:** local coordinates measured height from the top pad plane. The pad center was at assembly coordinates `(-8.89, 24.13, 0.05) mm`.

### Inputs and configuration

The run used the extracted connection geometry, a specified solder amount, and illustrative material properties. Its saved configuration records both the physical assumptions and the numerical settings needed to understand or repeat the calculation.

- **Source CAD:** `inputs/raspberry_pico_2H.step`, containing `420` original solids; a copy was saved as `run_006/input/original.step`.
- **Material:** surface tension `0.5 N/m`, density `7,400 kg/m3`, and pin contact angle `80 degrees`. These were not calibrated alloy properties.
- **Solder amount:** `0.025 mm3` top-fillet volume, volume multiplier `1.0`, and a completely filled barrel. The discrete barrel volume was approximately `0.407190 mm3`.
- **Gravity:** `0 m/s2`, so density did not affect this run's shape.
- **Starting mesh:** `5` radial segments, `8` segments per pin side, and one subsequent refinement. Initial perturbation was `0 mm`; the saved seed was `0`.
- **Solver:** Surface Evolver `2.70` with conjugate-gradient minimization, `30` warmup steps, and `1,000` steps per relaxation batch.
- **Convergence:** fixed `30`-step measurement windows, up to `10` check attempts, and `2` consecutive passing checks. Volume and energy-drift tolerances were `1e-7`; maximum movement tolerance was `1e-5 mm`. The process timeout was `300 seconds`.
- **Mesh control:** free-surface mesh improvement was enabled. Edge swaps were restricted to the liquid-air region before retries; unrestricted edge swapping was disabled.
- **CAD export:** original geometry preservation and self-intersection checks were enabled, with `0.01 mm` mesh tolerance and `1e-7 mm` sewing tolerance.

### Outputs and results

Experiment 6 produced a solder solid with a filled barrel and a shallow top fillet around the selected pin. The result is available both on its own and in the original PCB assembly, so we can inspect the joint's shape, section it in CAD, and use its dimensions as a reference for later simulations or measured-joint comparisons.

- **Fillet shape:** the solder reached approximately `0.057084 mm` (`57.08 micrometers`) above the pad. This is below the `0.15 mm` straight-pin height limit, so the predicted joint did not reach the excluded beveled tip.
- **Solder amount:** the total was approximately `0.432190 mm3`: `0.407190 mm3` in the filled barrel and `0.025 mm3` in the top fillet. The relaxation redistributed the specified solder rather than adding or removing material.
- **Exposed surface:** the liquid-air surface area was approximately `1.132038 mm2`. This describes the exposed fillet, not all the contact surfaces enclosing the solder solid, and can be compared across solder amounts or wetting conditions.
- **Energy and pressure:** the calculated values were approximately `5.54516e-7 J` and `68.05 Pa`. These describe the modeled surface-energy state and volume-constrained equilibrium pressure; they are not joint-strength or applied-load predictions.
- **Usable geometry:** the export contains one separate solder solid, represented by `2,560` triangular faces. The combined model retains all `420` original solids and adds the solder as solid `421`. No volumetric overlap was reported with the nearby board, pad, or pin, allowing the joint to be inspected in its assembly context.

Experiment 5 predicted almost the same overall joint dimensions, but its mesh contained extremely small triangles and could not be converted into a usable solder CAD solid. The main improvement in Experiment 6 was the surface mesh representation, rather than a change to the intended solder amount or material behavior.

- **Nearly unchanged height:** Experiment 5 predicted `0.057039 mm`, compared with `0.057084 mm` in Experiment 6: a difference of approximately `0.0000454 mm`, or `0.08%`. Both used the same geometry, solder volume, contact angle, surface tension, density, and gravity.
- **Mesh improvement changed:** Experiment 6 enabled `improve_free_surface_mesh`, which rearranges triangle connections within the liquid-air surface before further relaxation. It preserves the boundaries between the free surface and contact regions. Both experiments actually used conjugate-gradient minimization; it was not newly introduced in Experiment 6.
- **Less extreme triangles:** the smallest triangle area increased from about `9.23e-9 mm2` to `5.26e-7 mm2`, approximately `57` times larger. Together with the usable export, this supports mesh improvement as the likely reason Experiment 6 avoided Experiment 5's CAD reconstruction problem.
- **Small numerical differences:** the altered triangulation and relaxation path can explain the slight differences in height, surface area, and pressure (`67.85 Pa` versus `68.05 Pa`). These are not evidence of a different alloy or a changed physical solder charge.
- **Meaning for us:** we now have an inspectable, exportable joint with dimensions close to the previous prediction. Establishing whether those dimensions match real solder joints still requires measured data and checking sensitivity to mesh resolution.

### Important files and potential uses

If the local archive is available, find the original files under `data/archive/pre-docker/pcbsim_pipeline/experiments/run_006/`. The CAD files support visual inspection and downstream geometry work, while the saved measurements and inputs make the result traceable and useful as a reference for later studies.

- **`output/pcb_with_solder.step`:** the original assembly with one added solder solid. Open it in CAD to inspect placement and clearance around the connection. The solder is separate, not fused into the PCB or pin.
- **`output/solder_only.step`:** only the solder, including the filled barrel and top fillet, positioned in assembly coordinates. Use it for isolated shape inspection, section views, or as input geometry for a separate analysis with its own physics and material definitions.
- **`simulation/solder_mesh.off`:** the final triangular solder surface in local pad coordinates. Use it to visualize the relaxed shape or compare meshes; pair it with the coordinate transform in `geometry/geometry.json` for assembly placement.
- **`simulation/metrics.json`:** predicted height, volume, surface area, energy, pressure, and convergence measures. Use these quantities to compare parameter changes or supported real-world measurements.
- **`geometry/extracted.step` and `geometry/geometry.json`:** the selected CAD connection and its dimensions and coordinate frame. Use them to verify what was extracted and how local results map into the original assembly.
- **`input/config.original.json` and `input/config.json`:** the original and expanded settings saved for this run. Use them to recover the exact parameters or prepare a controlled comparison without relying on a later-edited `pipeline.json`.
- **`fe/model.fe` and `simulation/run.cmd`:** the solver model and command sequence. Use them to inspect or investigate the native calculation. The initial mesh beside the model is not the final solder result.
- **`exp_report.json`, `simulation/runner_report.json`, and `simulation/stdout.log`:** overall execution, solver identity and outcome, and detailed native output. Use them to trace completion or diagnose differences in future runs.
- **`output/conversion_report.json` and `evaluation/automated_test_results.json`:** geometric preservation, export consistency, and numerical acceptance records. Use them to review why the result was accepted; they do not demonstrate experimental accuracy.

### How to build on this experiment

Use Experiment 6 as a reference case for understanding the workflow and comparing changes. A controlled follow-up should preserve known inputs, vary a clear assumption, and distinguish numerical differences from physical ones.

1. Open the solder-only export to inspect the fillet and barrel, then open the combined export to see their position around the pin and pad.
2. Compare a new run with these saved metrics after changing one parameter, such as solder volume or pin contact angle.
3. Refine the mesh and compare height and surface area before treating those predictions as independent of resolution.
4. Supply measurements from a matching real joint using the validation process above, then calibrate uncertain wetting parameters if needed. Do not use Experiment 6's predicted values as substitutes for measured data.
5. If geometry is reused in thermal or mechanical software, provide that analysis with its own loads, boundary conditions, and material properties. This exported equilibrium shape does not by itself predict temperature history or strength.
