"""Lazy CAD dependency loading; simulation/evaluation do not require CadQuery."""
from __future__ import annotations
from .common import ComponentError


def cq_module():
    try:
        import cadquery as cq
    except ImportError as exc:
        raise ComponentError('CAD operations need CadQuery. Run: python -m pip install -e ".[cad]"') from exc
    return cq


def bounds(shape) -> list[float]:
    b = shape.BoundingBox()
    return [b.xmin, b.ymin, b.zmin, b.xmax, b.ymax, b.zmax]


def solid_signature(shape) -> dict:
    return {"volume_mm3": float(shape.Volume()), "bounds_mm": bounds(shape),
            "center_mm": list(shape.Center().toTuple()), "face_count": len(shape.Faces())}


def load_shape(path):
    cq = cq_module()
    try:
        shape = cq.importers.importStep(str(path)).val()
    except Exception as exc:
        raise ComponentError(f"Unable to read STEP {path}: {exc}") from exc
    if not shape.Solids():
        raise ComponentError(f"STEP file contains no solids: {path}")
    return shape
