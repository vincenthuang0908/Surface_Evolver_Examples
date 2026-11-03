
# Surface Evolver Numerical Experiment Summary (At the moment, may be updated)

## 1. Introduction

This report summarizes the numerical results of 12 experiments conducted using Surface Evolver. The actual experiment results are in `/results/native`.

The experiments investigate liquid surface behavior, surface-energy minimization, wetting conditions, capillary bridges, gravity, patterned solder pads, and solder fillet formation around PCB through-hole pins.

The primary outputs examined are:

- Final energy
- Surface area
- Final liquid volume
- Differences between experimental configurations

The main objective is to understand how changes in geometry, wetting conditions, and solder volume influence the liquid configurations calculated by Surface Evolver.

---

## 2. Numerical Results

The following table presents the numerical outputs obtained from the 12 experiments.

| Experiment | Final Energy | Surface Area | Final Volume |
|---|---:|---:|---:|
| 01 - Catenoid | 5.9907 | 5.9907 | Not reported |
| 02 - Droplet (60°) | 0.8932 | 1.4057 | 0.2000 |
| 03 - Droplet (120°) | 1.5648 | 1.3748 | 0.2000 |
| 04 - Cylindrical Bridge | 20.8894 | 20.8894 | 3.1416 |
| 05 - Stretched Bridge | 21.5726 | 21.5726 | 3.1416 |
| 06 - Droplet with Gravity | 0.8965 | 1.4072 | 0.2000 |
| 07 - Patterned Pad (Nominal) | 0.9426 | 1.3353 | 0.2000 |
| 08 - Patterned Pad (Overfill) | 3.8089 | 4.1993 | 0.9000 |
| 09 - Hard Pad Constraint | 0.9325 | 1.3250 | 0.2000 |
| 10 - Nominal Pin Fillet | 1.5983 | 1.8245 | 0.2000 |
| 11 - Offset Pin Fillet | 1.6186 | 1.8393 | 0.2000 |
| 12 - Underfilled Pin | 1.5391 | 1.7129 | 0.1400 |

**Note:** Values are rounded to four decimal places. Energy, area, and volume are expressed in the units used by the models.

Experiment 01 does not report a final volume because the catenoid experiment investigates a minimal surface between fixed boundaries rather than a prescribed-volume liquid body.

---

## 3. Interpretation of Experimental Results

### 3.1 Experiment 01: Catenoid

The catenoid experiment investigates surface-area minimization between two circular boundaries.

**Numerical results:**

- Final energy: 5.9907
- Surface area: 5.9907
- Final volume: Not reported

The equality between energy and surface area is consistent with a surface-energy coefficient of 1 and an energy formulation based on surface area.

The experiment provides a useful mathematical benchmark because catenoids have known analytical solutions.

### 3.2 Experiments 02–03: Droplet Wetting Conditions

These experiments investigate the influence of different nominal contact angles on droplet configurations.

| Measurement | 60° Droplet | 120° Droplet |
|---|---:|---:|
| Final energy | 0.8932 | 1.5648 |
| Surface area | 1.4057 | 1.3748 |
| Final volume | 0.2000 | 0.2000 |

Both experiments used the same prescribed liquid volume.

The 120° droplet produced approximately 75% higher final energy than the 60° droplet, while its surface area was approximately 2.2% smaller.

This demonstrates that changing wetting conditions can alter the total energy without producing a proportional change in liquid surface area.

The difference in energy should be interpreted using the complete energy formulation, including any wetting-energy contributions.

### 3.3 Experiments 04–05: Liquid Bridges

These experiments examine liquid bridges between boundaries under different geometric configurations.

| Measurement | Cylindrical Bridge | Stretched Bridge |
|---|---:|---:|
| Final energy | 20.8894 | 21.5726 |
| Surface area | 20.8894 | 21.5726 |
| Final volume | 3.1416 | 3.1416 |

The stretched bridge produced approximately 3.3% higher energy and surface area than the cylindrical bridge.

Both configurations maintained the same final liquid volume.

The results indicate that changing the bridge geometry affects the resulting liquid surface.

Further examination of the final meshes would be required to quantify necking, curvature, and geometric stability.

### 3.4 Experiment 06: Gravity Effects

Experiment 06 investigates the effect of gravity on a liquid droplet.

**Numerical results:**

- Final energy: 0.8965
- Surface area: 1.4072
- Final volume: 0.2000

Compared with the 60° droplet in Experiment 02:

- Final energy increased from 0.8932 to 0.8965.
- Surface area increased from 1.4057 to 1.4072.
- Final volume remained 0.2000.

The reported changes are relatively small.

This suggests that the gravitational contribution produces a modest change in the modeled configuration under the chosen conditions.

A detailed comparison of the final droplet shapes would be needed to quantify the deformation.

### 3.5 Experiments 07–09: Patterned Pad and Boundary Conditions

These experiments investigate how patterned wetting regions, solder volume, and boundary restrictions affect liquid surface configurations.

| Measurement | Nominal Pad | Overfill | Hard Pad |
|---|---:|---:|---:|
| Final energy | 0.9426 | 3.8089 | 0.9325 |
| Surface area | 1.3353 | 4.1993 | 1.3250 |
| Final volume | 0.2000 | 0.9000 | 0.2000 |

The overfill experiment increased the liquid volume from 0.20 to 0.90.

This was accompanied by substantial increases in surface area and final energy.

The hard-pad configuration produced slightly lower energy and surface area than the nominal patterned-pad configuration.

These differences reflect the influence of prescribed liquid quantity and boundary conditions on the computed liquid surface.

---

## 4. PCB Solder Fillet Experiments

Experiments 10–12 are the most directly relevant to PCB through-hole selective soldering.

They investigate how pin position and solder volume influence the predicted solder fillet configuration.

### 4.1 Experiment 10: Nominal Pin Fillet

Experiment 10 represents the baseline configuration, with a centered pin and prescribed solder volume of 0.20.

**Numerical results:**

- Final energy: 1.5983
- Surface area: 1.8245
- Final volume: 0.2000

This experiment provides the reference configuration for comparing the effects of pin misalignment and reduced solder volume.

### 4.2 Experiment 11: Offset Pin Fillet

Experiment 11 introduces pin misalignment while maintaining the same prescribed solder volume as Experiment 10.

**Numerical results:**

- Final energy: 1.6186
- Surface area: 1.8393
- Final volume: 0.2000

Compared with the nominal configuration:

- Final energy increased by approximately 1.3%.
- Surface area increased by approximately 0.8%.
- Final volume remained unchanged.

These differences suggest that pin offset alters the computed solder surface configuration.

Further analysis of the final mesh is needed to determine the degree of fillet asymmetry and whether solder coverage differs around the pin.

### 4.3 Experiment 12: Underfilled Pin

Experiment 12 investigates the effect of reducing the prescribed solder volume by 30%.

**Numerical results:**

- Final energy: 1.5391
- Surface area: 1.7129
- Final volume: 0.1400

Compared with the nominal configuration:

- Solder volume decreased by 30%.
- Final energy decreased by approximately 3.7%.
- Surface area decreased by approximately 6.1%.

The reduced volume was accompanied by lower total energy and surface area.

However, lower energy does not necessarily indicate a better solder joint, especially when comparing configurations with different liquid volumes.

The final surface geometry must be examined to determine whether reduced solder quantity affects fillet height, wetting coverage, or solder distribution.

---

## 5. Comparison of PCB Solder Fillet Results

| Measurement | Nominal Pin | Offset Pin | Underfilled Pin |
|---|---:|---:|---:|
| Final energy | 1.5983 | 1.6186 | 1.5391 |
| Surface area | 1.8245 | 1.8393 | 1.7129 |
| Final volume | 0.2000 | 0.2000 | 0.1400 |

### 5.1 Influence of Pin Offset

At constant solder volume, introducing pin offset resulted in slightly higher surface area and total energy.

This suggests that pin alignment influences the geometry of the modeled solder surface.

To characterize the effect more precisely, the final mesh should be analyzed for:

- Fillet height around the pin
- Differences between opposite sides of the pin
- Local surface curvature
- Solder coverage and contact geometry

### 5.2 Influence of Solder Underfill

Reducing solder volume produced lower total energy and surface area.

The results indicate that solder quantity is an important parameter affecting the modeled fillet configuration.

Further geometric analysis is necessary to determine how underfill changes the fillet profile and whether those changes correspond to undesirable solder-joint characteristics.

### 5.3 Interpretation of Energy Differences

Total energy should not be treated as a direct measure of solder-joint quality.

Energy values depend on the model's geometry, liquid volume, material properties, and energy formulation.

Therefore, comparing energies is most meaningful when the models use consistent physical definitions and differ by a controlled parameter.

For evaluating solder-joint quality, geometric measurements and experimental validation are more informative.

---

## 6. Overall Findings

The numerical experiments demonstrate that changes in wetting conditions, geometry, gravity, boundary constraints, and liquid volume influence the configurations calculated by Surface Evolver.

The main observations are:

1. Changing nominal droplet contact angle produced substantial differences in total energy at constant volume.
2. Stretching a liquid bridge increased its computed surface area and energy.
3. Adding gravity produced relatively small changes in the droplet's numerical outputs.
4. Increasing liquid volume on a patterned pad substantially increased surface area and total energy.
5. Introducing pin offset produced slightly higher energy and surface area at constant solder volume.
6. Reducing solder volume in the PCB pin model resulted in lower energy and surface area.

These observations provide a quantitative basis for studying how different physical and geometric parameters influence liquid surface configurations.

---

## 7. Limitations and Future Analysis

The reported numerical values describe the solutions produced by the specified Surface Evolver models.

They do not, by themselves, establish whether the simulated solder configurations accurately reproduce real PCB selective-soldering behavior.

Further analysis should include:

- Visualization of the final three-dimensional meshes
- Measurement of solder fillet height
- Quantification of fillet asymmetry
- Examination of wetting and contact geometry
- Comparison against analytical solutions where available
- Comparison against experimentally measured solder-joint profiles
- Evaluation of model assumptions and physical parameter values

In particular, Experiments 10–12 would benefit from extracting geometric measurements from the final meshes rather than relying only on total energy and surface area.

---

## 8. Future Improvements and Additional Measurements

Although the current Surface Evolver simulations provide final energy, surface area, volume, and exported mesh geometry, additional post-processing is needed to obtain all the measurements identified in the experiment objectives.

Future improvements will focus on the following areas:

Geometric analysis: Extend the Python scripts to calculate droplet height, footprint radius, surface curvature, liquid-bridge profiles, and minimum neck radius directly from the exported meshes.

Solder fillet characterization: Develop measurements for fillet height, surface profile, and circumferential asymmetry around PCB pins. These measurements will support quantitative comparisons between the nominal, offset, and underfilled pin configurations.

Wetting and boundary analysis: Extract apparent contact angles, spreading extent, and contact-line geometry to evaluate how different wetting conditions and pad constraints affect the simulated liquid surfaces.

Convergence and stability analysis: Record more detailed energy and geometry histories during minimization, perform mesh-refinement studies, and investigate liquid-bridge stability through additional simulations.

Analytical and physical validation: Compare simplified experiments against known mathematical solutions, such as catenoids and spherical caps. For the PCB solder-fillet experiments, incorporate realistic material properties, solder quantities, and experimental measurements to evaluate physical accuracy.

Most geometric measurements can be obtained through additional analysis of the existing mesh.obj and mesh.npz files without rerunning the simulations. However, stability investigations, mesh-independence studies, and physical validation may require additional simulation runs or experimental data.

These improvements will allow the project to move beyond basic numerical outputs toward a more complete quantitative characterization of liquid-surface behavior and PCB solder-fillet formation.

## 9. Conclusion

The 12 Surface Evolver experiments provide numerical results illustrating how different physical conditions and geometric configurations influence liquid surface behavior.

For the PCB solder-fillet models, pin misalignment was associated with a modest increase in surface area and energy, while reducing solder volume produced lower values for both quantities.
