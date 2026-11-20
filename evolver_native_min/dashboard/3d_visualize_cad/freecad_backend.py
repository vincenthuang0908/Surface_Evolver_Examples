"""Headless FreeCAD geometry operations. Import under FreeCAD's Python."""

from pathlib import Path
import re
from tempfile import TemporaryDirectory

import FreeCAD
import Part

from pcbsim.common import ComponentError


# OpenCASCADE 7.6 crashes on empty rendering-property lists. The equivalent
# presentation entity without properties keeps the color and the STEP references.
# Match strings and comments first so record-like text inside them is left alone.
_STEP_PRESENTATION = re.compile(
    rb"'(?:[^']|'')*'|/\*.*?\*/|"
    rb"(#[0-9]+\s*=\s*)SURFACE_STYLE_RENDERING_WITH_PROPERTIES"
    rb"\s*\(\s*(\.[A-Z_]+\.)\s*,\s*(#[0-9]+)\s*,\s*\(\s*\)\s*\)\s*;",
    re.DOTALL | re.IGNORECASE,
)


def _read_step(path):
    source = Path(path)
    data = source.read_bytes()
    if b"SURFACE_STYLE_RENDERING_WITH_PROPERTIES" in data.upper():
        def replace(match):
            if match.group(1) is None:
                return match.group()
            prefix, method, color = match.groups()
            return prefix + b"SURFACE_STYLE_RENDERING(" + method + b"," + color + b");"

        compatible = _STEP_PRESENTATION.sub(replace, data)
        if compatible != data:
            with TemporaryDirectory(prefix="pcbsim-step-") as temp:
                temporary_step = Path(temp) / "import.step"
                temporary_step.write_bytes(compatible)
                return Part.read(str(temporary_step))
    return Part.read(str(source))


class FreeCADBackend:
    def load(self, path):
        try:
            shape = _read_step(path)
        except (RuntimeError, OSError) as exc:
            raise ComponentError(f"FreeCAD could not read {path}: {exc}") from exc
        if not shape.Solids:
            raise ComponentError(f"STEP file contains no solids: {path}")
        return shape

    def solids(self, shape):
        return shape.Solids

    def bounds(self, shape):
        # FreeCAD 0.20's Python binding only handles the no-argument form safely.
        # Exact measurements happen before tessellation.
        box = shape.optimalBoundingBox()
        return [box.XMin, box.YMin, box.ZMin, box.XMax, box.YMax, box.ZMax]

    def volume(self, shape):
        return shape.Volume

    def signature(self, shape):
        return {"volume_mm3": self.volume(shape), "bounds_mm": self.bounds(shape),
                "center_mm": list(shape.CenterOfMass), "face_count": len(shape.Faces)}

    def cylindrical_faces(self, shape):
        for face in shape.Faces:
            surface = face.Surface
            if isinstance(surface, Part.Cylinder):
                yield surface.Axis.z, (surface.Center.x, surface.Center.y), surface.Radius, self.bounds(face)

    def planar_faces(self, shape):
        for face in shape.Faces:
            if isinstance(face.Surface, Part.Plane):
                u_min, u_max, v_min, v_max = face.ParameterRange
                normal = face.normalAt((u_min + u_max) / 2, (v_min + v_max) / 2)
                yield tuple(normal), self.bounds(face)

    def box(self, size, origin):
        return Part.makeBox(*size, FreeCAD.Vector(*origin))

    def cylinder(self, radius, height, origin):
        return Part.makeCylinder(radius, height, FreeCAD.Vector(*origin))

    def intersect(self, first, second):
        return first.common(second)

    def valid(self, shape):
        return shape.isValid()

    def export_step(self, solids, path):
        Part.makeCompound(solids).exportStep(str(path))
