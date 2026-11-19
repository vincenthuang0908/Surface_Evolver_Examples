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
- With gravity disabled, density does not affect shape; surface tension sets energy and pressure scales. Volume and pin contact angle influence the equilibrium shape.
- Default material values are illustrative, not calibrated to a particular alloy or process.

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

   Use the dashboard to change the STEP, connection index, volume, or contact angle interactively. The baseline config is mounted from the checkout. **Advanced JSON** exposes all stage settings and **Tutorial & Documentation** includes a runnable Run 6 preset.

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

2. From the project root, evaluate a completed run. Replace `run_001` with your run.

```sh
docker compose -f docker/compose.yaml run --rm pipeline python -m pcbsim.components.evaluation --config /app/pipeline.json evaluate --experiment /data/experiments/run_001 --measurements /data/my_measurements.json
```

3. Read `evaluation/automated_test_results.json` inside that run. For the example, a prediction of `0.057 mm` differs by `0.003 mm`, so it passes the `0.005 mm` tolerance. Passing this comparison establishes agreement for that quantity, not every aspect of the joint.
4. Add other supported quantities when measured: `fillet_volume_mm3`, `volume_mm3` (barrel plus fillet), `free_surface_area_mm2`, `pressure_Pa`, or `energy_J`. Each observation needs a `value` and a positive `absolute_tolerance` in the named units. Full profile or scan comparisons require separate analysis.

## Calibrate materials

Calibration adjusts uncertain physical settings to reduce disagreement with measured joints. Start with known alloy properties and solder amounts, fit uncertain wetting behavior, then check the fitted settings against joints that were not used for fitting. Calibration does not add missing physics or guarantee accuracy outside the conditions represented by the data.

1. **Define the conditions:** record alloy, soldering temperature, surface finishes, flux conditions, and joint geometry. Contact angle reflects the interacting surfaces and process, not the alloy alone.
2. **Collect measurements:** measure suitable quantities, such as fillet height, with realistic uncertainty. Use the JSON format above. Keep measured solder volume and known material properties fixed where possible.
3. **Choose uncertain settings:** typically start with pin contact angle. Define plausible candidate values rather than changing unrelated settings to force a match.
4. **Run candidate simulations:** the calibration tool tries every combination in a bounded parameter grid, excluding candidates that fail numerical convergence or CAD validation.
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
