"""Definitions shared by native exports, measurement comparison, and the dashboard."""
from dataclasses import dataclass

import numpy as np

from ..common import ComponentError


@dataclass(frozen=True)
class Observable:
    label: str
    unit: str
    category: str


OBSERVABLES = {
    "maximum_height_above_pad_mm": Observable("Maximum height above pad", "mm", "Geometry"),
    "fillet_volume_mm3": Observable("Top-fillet volume", "mm³", "Geometry"),
    "volume_mm3": Observable("Total solder volume", "mm³", "Geometry"),
    "free_surface_area_mm2": Observable("Liquid–air surface area", "mm²", "Geometry"),
    "wetted_pin_area_mm2": Observable("Wetted pin area above pad", "mm²", "Geometry"),
    "pin_apparent_contact_angle_deg": Observable("Mean apparent pin contact angle", "°", "Geometry"),
    "pad_apparent_contact_angle_deg": Observable("Mean apparent pad contact angle", "°", "Geometry"),
    "barrel_volume_mm3": Observable("Barrel volume", "mm³", "Geometry"),
    "total_shell_area_mm2": Observable("Total solder shell area", "mm²", "Geometry"),
    "liquid_air_surface_energy_J": Observable("Liquid–air surface energy", "J", "Derived model quantity"),
    "energy_J": Observable("Total modeled energy", "J", "Derived model quantity"),
    "pressure_Pa": Observable("Volume constraint pressure multiplier", "Pa", "Derived model quantity"),
    "volume_relative_error": Observable("Relative volume constraint residual", "1", "Solver diagnostic"),
    "energy_drift_relative": Observable("Scaled energy drift", "1", "Solver diagnostic"),
    "max_move_mm": Observable("Maximum vertex movement in check window", "mm", "Solver diagnostic"),
    "convergence_checks": Observable("Convergence checks", "count", "Solver diagnostic"),
}
DEFAULT_OUTPUTS = ("maximum_height_above_pad_mm", "fillet_volume_mm3", "volume_mm3", "free_surface_area_mm2")
ANGLE_REGIONS = {"pin_apparent_contact_angle_deg": 2, "pad_apparent_contact_angle_deg": 3}


def selected_outputs(settings):
    selection = settings.get("outputs", list(DEFAULT_OUTPUTS))
    if (not isinstance(selection, list)
            or any(not isinstance(key, str) or key not in OBSERVABLES for key in selection)
            or len(set(selection)) != len(selection)):
        raise ComponentError("Surface Evolver outputs must be a list of distinct supported metric keys")
    return selection


def mesh_contact_angles(vertices, faces, regions, cross_products, requested):
    """Estimate angles through the liquid along edges shared with a solid facet.

    Both normals point out of the liquid. The solid normal directed into the
    liquid is therefore the negative of the wall facet normal.
    """
    by_edge = {}
    for index, face in enumerate(faces):
        for a, b in zip(face, np.roll(face, -1)):
            by_edge.setdefault(tuple(sorted((a, b))), []).append(index)
    region_to_key = {ANGLE_REGIONS[key]: key for key in requested}
    samples = {key: [] for key in requested}
    for (a, b), adjacent in by_edge.items():
        if len(adjacent) != 2:
            continue
        free, wall = adjacent
        if regions[wall] == 1:
            free, wall = wall, free
        key = region_to_key.get(regions[wall])
        if regions[free] != 1 or key is None:
            continue
        u, w = cross_products[free], cross_products[wall]
        cosine = -np.dot(u, w) / (np.linalg.norm(u) * np.linalg.norm(w))
        angle = np.degrees(np.arccos(np.clip(cosine, -1, 1)))
        samples[key].append((float(angle), float(np.linalg.norm(vertices[a] - vertices[b]))))
    result = {}
    for key, values in samples.items():
        if values:
            angles, lengths = zip(*values)
            result[key] = float(np.average(angles, weights=lengths))
    return result
