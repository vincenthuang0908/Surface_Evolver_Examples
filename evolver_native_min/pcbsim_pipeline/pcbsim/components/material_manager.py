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

MATERIAL_PROPERTIES = {
    "surface_tension_N_per_m": ("Liquid–air surface tension", "N/m"),
    "density_kg_per_m3": ("Liquid density", "kg/m³"),
    "pin_contact_angle_deg": ("Young contact angle on the pin finish", "°"),
}
PROPERTY_BASES = ("assumed", "measured", "literature", "calibrated_effective")
_ALLOY_SOURCE = "https://www.indium.com/products/bar-solder/"
ALLOY_PRESETS = {
    "SAC305": {"composition": "96.5 wt% Sn, 3.0 wt% Ag, 0.5 wt% Cu", "source": _ALLOY_SOURCE},
    "Sn63Pb37": {"composition": "63 wt% Sn, 37 wt% Pb", "source": _ALLOY_SOURCE},
}

# Starter values for the dashboard. Saved configurations carry explicit values.
ALLOY_PROPERTY_DEFAULTS = {
    "SAC305": {
        "surface_tension_N_per_m": {
            "value": 0.4337,
            "basis": "literature",
            "source": "Caribe Couvertier et al., Table 3, nominal SAC305 at 250 °C. "
                      "https://doi.org/10.3390/electronicmat7030019",
        },
        "density_kg_per_m3": {
            "value": 7290.0,
            "basis": "literature",
            "source": "Approximate liquid density at 250 °C, rounded from the linear fit in "
                      "Varanasi and Pal, Table 2. https://doi.org/10.1007/s11106-021-00262-w",
        },
    },
}


def validate_provenance(provenance, keys):
    if not isinstance(provenance, dict) or set(provenance) - set(keys):
        raise ComponentError("Property provenance must be keyed by supported property names")
    for key, entry in provenance.items():
        if (not isinstance(entry, dict) or entry.get("basis") not in PROPERTY_BASES
                or not isinstance(entry.get("source", ""), str)):
            raise ComponentError(f"Invalid provenance for {key}")
        if entry["basis"] != "assumed" and not entry.get("source", "").strip():
            raise ComponentError(f"Provide a source or study ID for {key}")
    return provenance


def normalize_materials(config: dict) -> dict:
    settings = section(config, "material_manager")
    # Top-level material/simulation are convenient when a component is used on its own.
    input_settings = {"material": config.get("material", {}), "simulation": config.get("simulation", {})}
    supplied = deep_merge(input_settings, settings)
    cfg = deep_merge(DEFAULTS, supplied)
    material, sim = cfg["material"], cfg["simulation"]
    if not isinstance(material, dict) or not isinstance(sim, dict):
        raise ComponentError("material and simulation must be JSON objects")
    unknown_material = set(material) - (set(DEFAULTS["material"]) | {"effective_pin_contact_angle_deg", "provenance", "alloy"})
    unknown_simulation = set(sim) - (set(DEFAULTS["simulation"]) | {"effective_fillet_volume_mm3", "provenance"})
    if unknown_material or unknown_simulation:
        raise ComponentError(f"Unsupported physical settings: material={sorted(unknown_material)}, simulation={sorted(unknown_simulation)}")
    alloy = material.get("alloy")
    if alloy is not None:
        if not isinstance(alloy, str) or alloy not in ALLOY_PRESETS:
            raise ComponentError("Unknown alloy preset")
        if MATERIAL_PROPERTIES.keys() - supplied["material"].keys():
            raise ComponentError(f"Enter the liquid surface tension, density, and pin contact angle for {alloy}")
    gamma = positive(material["surface_tension_N_per_m"], "surface_tension_N_per_m")
    rho = positive(material["density_kg_per_m3"], "density_kg_per_m3")
    try:
        if isinstance(material["pin_contact_angle_deg"], bool) or isinstance(sim["contact_angle_delta_deg"], bool):
            raise ValueError
        base_angle = float(material["pin_contact_angle_deg"])
        delta = float(sim["contact_angle_delta_deg"])
        theta = base_angle + delta
    except (ValueError, TypeError, OverflowError) as exc:
        raise ComponentError("Contact angles must be finite numbers") from exc
    if not 0 < base_angle < 180 or not math.isfinite(theta) or not 0 < theta < 180:
        raise ComponentError("Base and effective pin contact angles must be strictly between 0 and 180 degrees")
    gravity = positive(sim["gravity_m_per_s2"], "gravity_m_per_s2", allow_zero=True)
    base_volume = positive(sim["fillet_volume_mm3"], "fillet_volume_mm3")
    multiplier = positive(sim["volume_multiplier"], "volume_multiplier")
    volume = positive(base_volume * multiplier, "effective_fillet_volume_mm3")
    gravity_coefficient = positive(rho * gravity * 1e-6 / gamma, "gravity coefficient", allow_zero=True)
    if not isinstance(material["name"], str) or not material["name"].strip():
        raise ComponentError("Material name must be nonempty")
    validate_provenance(material.get("provenance", {}), MATERIAL_PROPERTIES)
    validate_provenance(sim.get("provenance", {}), DEFAULTS["simulation"])
    seed = integer(sim["seed"], "seed", 0, 2147483647)
    if sim["barrel_fill"] != "full":
        raise ComponentError("v1 models a fully filled plated barrel; partial filling requires a different free-surface topology")
    if sim["pin_contact_line"] not in ("mobile", "pinned"):
        raise ComponentError("pin_contact_line must be mobile or pinned")
    return {"schema_version": 1, "units": {"length": "mm", "volume": "mm^3", "energy": "gamma*(1 mm)^2"},
            "alloy_reference": ALLOY_PRESETS.get(alloy),
            "material": {**material, "surface_tension_N_per_m": gamma, "density_kg_per_m3": rho,
                         "pin_contact_angle_deg": base_angle, "effective_pin_contact_angle_deg": theta},
            "simulation": {**sim, "seed": seed, "effective_fillet_volume_mm3": volume,
                           "fillet_volume_mm3": base_volume, "volume_multiplier": multiplier,
                           "contact_angle_delta_deg": delta,
                           "gravity_m_per_s2": gravity},
            "scales": {"length_m": 0.001, "energy_J": gamma*1e-6,
                       "pressure_Pa": positive(gamma/0.001, "pressure scale"),
                       "gravity_coefficient": gravity_coefficient},
            "assumptions": ["Properties without explicit provenance are assumed model inputs.",
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
