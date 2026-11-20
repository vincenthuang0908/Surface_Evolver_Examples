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


class CadQueryBackend:
    """Geometry operations used by the shared connection extractor."""

    load = staticmethod(load_shape)
    bounds = staticmethod(bounds)
    signature = staticmethod(solid_signature)

    def solids(self, shape):
        return shape.Solids()

    def volume(self, shape):
        return shape.Volume()

    def cylindrical_faces(self, shape):
        from OCP.BRepAdaptor import BRepAdaptor_Surface

        for face in shape.Faces():
            if face.geomType() == "CYLINDER":
                cylinder = BRepAdaptor_Surface(face.wrapped).Cylinder()
                axis = cylinder.Axis().Direction()
                center = cylinder.Location()
                yield axis.Z(), (center.X(), center.Y()), cylinder.Radius(), bounds(face)

    def planar_faces(self, shape):
        for face in shape.Faces():
            if face.geomType() == "PLANE":
                yield face.normalAt().toTuple(), bounds(face)

    def box(self, size, origin):
        cq = cq_module()
        return cq.Solid.makeBox(*size, cq.Vector(*origin))

    def cylinder(self, radius, height, origin):
        cq = cq_module()
        return cq.Solid.makeCylinder(radius, height, cq.Vector(*origin))

    def intersect(self, first, second):
        return first.intersect(second)

    def valid(self, shape):
        return shape.isValid()

    def export_step(self, solids, path):
        cq = cq_module()
        cq.exporters.export(cq.Compound.makeCompound(solids), str(path))
