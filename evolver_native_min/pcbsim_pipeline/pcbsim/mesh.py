"""Strict triangle OFF I/O and deterministic geometric/topological checks."""
from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
import numpy as np
from .common import ComponentError


def arrays(vertices, faces):
    v = np.asarray(vertices, dtype=float)
    raw = np.asarray(faces)
    if v.ndim != 2 or v.shape[1] != 3 or not len(v) or not np.isfinite(v).all():
        raise ComponentError("Mesh vertices must be a nonempty finite N x 3 array")
    if raw.ndim != 2 or raw.shape[1] != 3 or not len(raw):
        raise ComponentError("Mesh faces must be a nonempty M x 3 triangle array")
    try:
        if not np.isfinite(raw).all() or not np.equal(raw, np.floor(raw)).all():
            raise ComponentError("Mesh indices must be integers")
        f = raw.astype(np.int64)
    except (TypeError, ValueError, OverflowError) as exc:
        raise ComponentError("Invalid mesh indices") from exc
    if f.min() < 0 or f.max() >= len(v):
        raise ComponentError("Mesh contains an out-of-range vertex index")
    return v, f


def read_off(path: str | Path):
    try:
        lines = [line.split("#", 1)[0].strip() for line in Path(path).read_text(encoding="utf-8-sig").splitlines()]
        lines = [line for line in lines if line]
        if not lines or not lines[0].startswith("OFF"):
            raise ComponentError("Expected an ASCII OFF file")
        if lines[0] == "OFF":
            counts = lines[1].split(); pos = 2
        else:
            counts = lines[0][3:].split(); pos = 1
        if len(counts) != 3:
            raise ComponentError("OFF header must contain vertex, face and edge counts")
        nv, nf, ne = map(int, counts)
        if not 0 < nv <= 10000000 or not 0 < nf <= 20000000 or ne < 0:
            raise ComponentError("Invalid OFF counts")
        if len(lines) != pos + nv + nf:
            raise ComponentError("OFF counts do not match its records")
        v = []
        for line in lines[pos:pos + nv]:
            values = line.split()
            if len(values) != 3:
                raise ComponentError("Only uncolored 3D OFF vertices are supported")
            v.append([float(x) for x in values])
        f = []
        for line in lines[pos + nv:]:
            values = [int(x) for x in line.split()]
            if len(values) != 4 or values[0] != 3:
                raise ComponentError("OFF faces must be triangles; polygons are not silently triangulated")
            f.append(values[1:])
        return arrays(v, f)
    except (OSError, IndexError, ValueError) as exc:
        raise ComponentError(f"Cannot read OFF {path}: {exc}") from exc


def write_off(path: str | Path, vertices, faces) -> Path:
    v, f = arrays(vertices, faces)
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="ascii", newline="\n") as stream:
        stream.write(f"OFF\n{len(v)} {len(f)} 0\n")
        for row in v:
            stream.write(" ".join(f"{x:.17g}" for x in row) + "\n")
        for row in f:
            stream.write("3 " + " ".join(map(str, row)) + "\n")
    return path


def signed_volume(vertices, faces) -> float:
    v, f = arrays(vertices, faces)
    # Translation improves numerical conditioning for globally placed meshes.
    v = v - v.mean(axis=0)
    t = v[f]
    return float(np.einsum("ij,ij->i", t[:, 0], np.cross(t[:, 1], t[:, 2])).sum() / 6)


def inspect_mesh(vertices, faces, *, area_epsilon: float = 1e-14) -> dict:
    v, f = arrays(vertices, faces)
    t = v[f]
    areas = np.linalg.norm(np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0]), axis=1) / 2
    incidences = defaultdict(list)
    for i, triangle in enumerate(f):
        for a, b in zip(triangle, np.roll(triangle, -1)):
            a, b = int(a), int(b)
            incidences[tuple(sorted((a, b)))].append((i, 1 if a < b else -1))
    boundary = [edge for edge, refs in incidences.items() if len(refs) == 1]
    nonmanifold = sum(len(refs) > 2 for refs in incidences.values())
    bad_orientation = sum(len(refs) == 2 and sum(sign for _, sign in refs) != 0 for refs in incidences.values())
    duplicate = sum(count - 1 for count in Counter(tuple(sorted(map(int, tri))) for tri in f).values())
    adjacency = defaultdict(set)
    for refs in incidences.values():
        ids = [i for i, _ in refs]
        for i in ids:
            adjacency[i].update(j for j in ids if j != i)
    unseen = set(range(len(f))); components = 0
    while unseen:
        components += 1; stack = [unseen.pop()]
        while stack:
            for other in adjacency[stack.pop()]:
                if other in unseen:
                    unseen.remove(other); stack.append(other)
    degenerate = int(np.count_nonzero(areas <= area_epsilon))
    topological_pass = not (degenerate or duplicate or nonmanifold or bad_orientation)
    closed = len(boundary) == 0 and topological_pass
    return {"vertex_count": len(v), "face_count": len(f), "edge_count": len(incidences),
            "boundary_edge_count": len(boundary), "nonmanifold_edge_count": nonmanifold,
            "inconsistent_orientation_edges": bad_orientation, "duplicate_faces": duplicate,
            "degenerate_faces": degenerate, "connected_components": components,
            "unused_vertices": len(v) - len(np.unique(f)), "minimum_triangle_area_mm2": float(areas.min()),
            "surface_area_mm2": float(areas.sum()), "closed": closed,
            "signed_volume_mm3": signed_volume(v, f) if closed else None,
            "topological_pass": topological_pass, "self_intersections_checked": False,
            "bounds_mm": [v.min(axis=0).tolist(), v.max(axis=0).tolist()]}


def require_valid_mesh(vertices, faces, *, closed: bool = False) -> dict:
    info = inspect_mesh(vertices, faces)
    if not info["topological_pass"]:
        raise ComponentError(f"Invalid mesh topology: {info}")
    if info["connected_components"] != 1:
        raise ComponentError("Expected one connected solder joint")
    if closed and (not info["closed"] or info["signed_volume_mm3"] <= 0):
        raise ComponentError("Expected a closed, consistently outward-oriented positive-volume solder mesh")
    return info


def rigid_transform(vertices, matrix):
    v = np.asarray(vertices, dtype=float); t = np.asarray(matrix, dtype=float)
    if t.shape != (4, 4) or not np.isfinite(t).all() or not np.allclose(t[3], [0, 0, 0, 1], atol=1e-12):
        raise ComponentError("local_to_world must be a finite 4 x 4 rigid transform")
    r = t[:3, :3]
    if not np.allclose(r.T @ r, np.eye(3), atol=1e-8) or not np.isclose(np.linalg.det(r), 1, atol=1e-8):
        raise ComponentError("local_to_world must be a proper rotation (no scale/reflection)")
    return v @ r.T + t[:3, 3]
