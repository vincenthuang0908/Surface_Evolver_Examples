"""Validate and normalize material/physical settings; no CAD or solver dependency."""
from __future__ import annotations
import argparse
import math
from pathlib import Path
from ..common import (ComponentError, cli_entry, config_arg, deep_merge, integer, load_config,
                      logger_or_default, positive, result, section, write_json)

# These are illustrative starting values, NOT measured properties of the supplied assembly.
DEFAULTS = {
    "material": {"name": "illustrative_solder_not_calibrated", "surface_tension_N_per_m": 0.5,
                 "density_kg_per_m3": 7400.0, "pin_contact_angle_deg": 80.0},
    "simulation": {"fillet_volume_mm3": 0.025, "volume_multiplier": 1.0,
                   "contact_angle_delta_deg": 0.0, "gravity_m_per_s2": 0.0,
                   "seed": 0, "barrel_fill": "full", "pin_contact_line": "mobile"}}


def normalize_materials(config: dict) -> dict:
    settings = section(config, "material_manager")
    # Top-level material/simulation are convenient when a component is used on its own.
    input_settings = {"material": config.get("material", {}), "simulation": config.get("simulation", {})}
    cfg = deep_merge(deep_merge(DEFAULTS, input_settings), settings)
    material, sim = cfg["material"], cfg["simulation"]
    if not isinstance(material, dict) or not isinstance(sim, dict):
        raise ComponentError("material and simulation must be JSON objects")
    unknown_material = set(material) - (set(DEFAULTS["material"]) | {"effective_pin_contact_angle_deg"})
    unknown_simulation = set(sim) - (set(DEFAULTS["simulation"]) | {"effective_fillet_volume_mm3"})
    if unknown_material or unknown_simulation:
        raise ComponentError(f"Unsupported physical settings: material={sorted(unknown_material)}, simulation={sorted(unknown_simulation)}")
    gamma = positive(material["surface_tension_N_per_m"], "surface_tension_N_per_m")
    rho = positive(material["density_kg_per_m3"], "density_kg_per_m3")
    try:
        theta = float(material["pin_contact_angle_deg"]) + float(sim["contact_angle_delta_deg"])
    except (ValueError, TypeError) as exc:
        raise ComponentError("Contact angles must be finite numbers") from exc
    if not math.isfinite(theta) or not 0 < theta < 180:
        raise ComponentError("Effective pin contact angle must be strictly between 0 and 180 degrees")
    gravity = positive(sim["gravity_m_per_s2"], "gravity_m_per_s2", allow_zero=True)
    base_volume = positive(sim["fillet_volume_mm3"], "fillet_volume_mm3")
    multiplier = positive(sim["volume_multiplier"], "volume_multiplier")
    seed = integer(sim["seed"], "seed", 0, 2147483647)
    if sim["barrel_fill"] != "full":
        raise ComponentError("v1 models a fully filled plated barrel; partial filling requires a different free-surface topology")
    if sim["pin_contact_line"] not in {"mobile", "pinned"}:
        raise ComponentError("pin_contact_line must be mobile or pinned")
    return {"schema_version": 1, "units": {"length": "mm", "volume": "mm^3", "energy": "gamma*(1 mm)^2"},
            "material": {**material, "surface_tension_N_per_m": gamma, "density_kg_per_m3": rho,
                         "effective_pin_contact_angle_deg": theta},
            "simulation": {**sim, "seed": seed, "effective_fillet_volume_mm3": base_volume * multiplier,
                           "gravity_m_per_s2": gravity},
            "scales": {"length_m": 0.001, "energy_J": gamma*1e-6,
                       "pressure_Pa": gamma/0.001,
                       "gravity_coefficient": rho*gravity*1e-6/gamma},
            "assumptions": ["Illustrative parameters; no real measurement calibration is claimed.",
                "Static capillary equilibrium, not transient reflow or solidification.",
                "Fully filled, fixed plated barrel; volume parameter denotes only solder ABOVE the top pad.",
                "Outer pad contact line is pinned; pad contact angle is not a fitted parameter."]}


def manage_materials(config, output_path, logger=None) -> dict:
    log = logger_or_default(logger, "material_manager")
    normalized = normalize_materials(config)
    path = write_json(output_path, normalized)
    log.info("Wrote normalized material and simulation settings")
    return result("material_manager", {"parameters": path}, physical_validation=False)


def main():
    parser = argparse.ArgumentParser(description=__doc__); config_arg(parser)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    return manage_materials(load_config(args.config), args.output)

if __name__ == "__main__":
    cli_entry(main)
