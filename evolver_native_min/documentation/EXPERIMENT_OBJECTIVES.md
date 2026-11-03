# Short Report: Surface Evolver Simulation Experiments for PCB Soldering Research

## 1. Introduction

The `evolver_native_min` project contains 12 Surface Evolver experiments designed to investigate liquid-surface behavior, including surface tension, wetting, gravity, liquid bridges, and solder fillet formation.

The experiments progress from fundamental capillary-surface problems to geometries relevant to through-hole PCB soldering.

**The primary objective** is to determine how geometry, boundary conditions, and liquid volume affect the equilibrium shape of a liquid surface through energy minimization.

The descriptions below distinguish between what each experiment is intended to test and the results that can potentially be obtained. 

## 2. Overview of the 12 Experiments

| No. | Experiment | What it tests | Results we may be able to obtain |
|---|---|---|---|
| 01 | Catenoid | Minimum-area surface between circular boundaries | Equilibrium surface shape, area, energy, and convergence behavior |
| 02 | Droplet at 60° | Wetting behavior for a nominal 60° contact-angle case | Droplet height, footprint, curvature, and energy |
| 03 | Droplet at 120° | Reduced-wetting behavior for a nominal 120° contact-angle case | Droplet height, footprint, curvature, and energy |
| 04 | Cylindrical liquid bridge | Liquid surface spanning separated boundaries | Bridge profile, surface area, and energy |
| 05 | Stretched liquid bridge | Effect of increased separation on a liquid bridge | Necking, shape changes, and possible loss of stability |
| 06 | Droplet with gravity | Competition between gravity and surface tension | Equilibrium deformation, height, and energy |
| 07 | Patterned pad — nominal | Liquid behavior over a patterned wetting region | Equilibrium shape, spreading extent, and surface energy |
| 08 | Patterned pad — overfill | Effect of increased liquid volume on the patterned region | Changes in spreading, height, and surface shape |
| 09 | Hard pad | Effect of restricting the liquid to a pad boundary | Boundary-constrained equilibrium geometry and energy |
| 10 | Pin solder fillet | Formation of a solder surface around a centered pin | Fillet profile, height, volume, and surface energy |
| 11 | Offset pin | Effect of pin misalignment on the solder fillet | Surface asymmetry, height variation, and energy |
| 12 | Underfilled pin | Effect of reduced solder volume | Fillet height, shape, and volume-related changes |

The availability of each measurement depends on the model definitions and the quantities exported by the native runner.

## 3. Experiments Most Relevant to PCB Soldering

**Experiment 10 — Nominal pin fillet** provides a baseline solder-joint geometry. It can be used to investigate how molten solder forms a curved surface between a cylindrical pin and its surrounding pad.

**Experiment 11 — Offset pin** investigates the effects of pin misalignment. Comparing it with Experiment 10 can reveal whether the equilibrium solder surface becomes asymmetric and how the local fillet height varies around the pin.

**Experiment 12 — Underfilled pin** investigates reduced solder volume. Comparing it with the nominal case can reveal changes in fillet height, surface area, and equilibrium geometry.

Experiments 10, 11, and 12 compare how pin alignment and solder volume affect the shape of a solder fillet. Experiment 10 provides a baseline, Experiment 11 investigates pin misalignment, and Experiment 12 investigates reduced solder volume.

## 4. Numerical Outputs

Running the experiments can provide several categories of numerical output:

- **Geometry:** Final vertex positions and the equilibrium liquid-surface shape.
- **Surface properties:** Surface area and surface energy.
- **Volume:** Calculated liquid volume compared with the prescribed target.
- **Solver behavior:** Changes in energy during minimization, numerical errors, and convergence diagnostics.
- **Mesh exports:** Three-dimensional geometry that can be visualized or analyzed using other software.

These outputs allow comparisons between experiments. For example, Experiments 02 and 03 can be compared to study contact-angle effects, while Experiments 07 and 08 can be compared to investigate the influence of additional liquid volume.

## 5. Limitations

The surface evolver experiments represent simplified capillary-surface models. They do not, by themselves, reproduce the complete selective-soldering process, including transient heating, solder solidification, flux chemistry, or robotic nozzle motion.

## 6. Conclusion

The 12 experiments provide a progression from fundamental surface-tension problems to PCB solder-joint geometries.

Experiments 01–09 help investigate and understand the effects of surface energy, wetting, gravity, and geometric constraints. Experiments 10–12 are the most directly relevant to PCB soldering because they examine nominal fillet formation, pin misalignment, and reduced solder volume.

Succesful simulations could provide quantitative comparisons of solder surface geometry, energy, and volume. These results could support further research into solder-joint formation and process sensitivity, but the numerical models may need to be validated against real physical measurements to determine whether they accurately represent real-world soldering behavior.