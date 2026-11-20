"""Supplemental shape check when mesh vertices move along a similar surface."""
import json
from pathlib import Path

import numpy as np

from pcbsim.common import write_json
from pcbsim.mesh import read_off


def distances(points, triangles):
    a, b, c = (triangles[:, i] for i in range(3))
    ab, ac = b - a, c - a
    normal = np.cross(ab, ac)
    normal2 = np.sum(normal * normal, axis=1)
    d00, d01, d11 = (np.sum(x * y, axis=1)
                     for x, y in ((ab, ab), (ab, ac), (ac, ac)))
    determinant = d00 * d11 - d01 * d01
    assert np.all(normal2 > 0) and np.all(determinant > 0)
    output = []
    for start in range(0, len(points), 32):
        p = points[start:start + 32, None, :]
        ap = p - a
        d20 = np.sum(ap * ab, axis=2)
        d21 = np.sum(ap * ac, axis=2)
        v = (d11 * d20 - d01 * d21) / determinant
        w = (d00 * d21 - d01 * d20) / determinant
        inside = (v >= 0) & (w >= 0) & (v + w <= 1)
        plane2 = np.sum(ap * normal, axis=2) ** 2 / normal2
        edge2 = np.full(plane2.shape, np.inf)
        for first, last in ((a, b), (b, c), (c, a)):
            edge = last - first
            offset = p - first
            t = np.clip(np.sum(offset * edge, axis=2) /
                        np.sum(edge * edge, axis=1), 0, 1)
            delta = offset - t[..., None] * edge
            edge2 = np.minimum(edge2, np.sum(delta * delta, axis=2))
        output.extend(np.sqrt(np.min(np.where(inside, plane2, edge2), axis=1)))
    return np.array(output)


# Analytic checks: plane projection, closest edge, closest vertex, interior.
tri = np.array([[[0., 0., 0.], [1., 0., 0.], [0., 1., 0.]]])
assert np.allclose(distances(np.array([[.2, .2, 1.], [.5, -.5, 0.],
                                      [2., 0., 0.], [.2, .2, 0.]]), tri),
                   [1., .5, 1., 0.])
paths = [Path('/reference/simulation/solder_mesh.off'),
         Path('/data/experiments/docker_baseline/simulation/solder_mesh.off')]
meshes = [read_off(path) for path in paths]
directions = []
for (vertices, faces), (other_vertices, other_faces) in (meshes, meshes[::-1]):
    samples = np.vstack((vertices, vertices[faces].mean(axis=1)))
    values = distances(samples, other_vertices[other_faces])
    directions.append({'sample_count': len(samples),
                       'maximum_distance_mm': float(values.max()),
                       'mean_distance_mm': float(values.mean())})
maximum = max(row['maximum_distance_mm'] for row in directions)
result = {'passed': maximum <= .001, 'tolerance_mm': .001,
          'maximum_sampled_surface_distance_mm': maximum,
          'directions': directions,
          'method': 'Both meshes: every vertex and facet centroid to all triangles of the other mesh',
          'scope': 'Sampled surface agreement; not a certified continuous Hausdorff bound. Does not establish vertex/triangulation identity.'}
write_json('/data/validation/sampled_surface_comparison.json', result)
print(json.dumps(result, indent=2))
raise SystemExit(0 if result['passed'] else 1)
