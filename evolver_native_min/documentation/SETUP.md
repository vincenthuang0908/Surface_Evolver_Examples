# Setup

Use Docker with the Compose plugin and support for Linux containers. Run the
same commands from the project root on macOS, Windows, or Linux. Compose selects
the platform supplied by Docker.

```sh
docker compose -f docker/compose.yaml up -d --build
```

Open [localhost:8501](http://localhost:8501). The image includes Python, CadQuery,
headless FreeCAD, and headless Surface Evolver. Rebuild the image to install the
FreeCAD worker and the browser's Three.js assets.

## CAD debug workspace

The viewer, FreeCAD worker, and integration test live in
`dashboard/3d_visualize_cad/`.

1. Open **CAD Debug**. Choose the supplied Pico example or upload a STEP assembly,
   then click **Load STEP**.
2. Rotate, zoom, or pan the original assembly. Use the connection list, click a
   pin label, or click a pin or pad in the model. **Focus pin** zooms to the
   current connection. Toggle **Other solids** to reveal pins obscured by
   housings or components.
3. Inspect the selected solid's bounding box, dimensions, volume, and center of
   mass below the viewer. Open the connection metadata to see the matching
   board and pad solids, bore radius, and pin sidewall range. Pin indices are
   geometric (increasing world X, then decreasing world Y).
4. Click **Extract pin #…** to reopen the exported STEP in FreeCAD and compare
   both views at the same world position. The geometry checks compare pin and
   pad bounding boxes, center of mass, and volume and verify the cropped PCB
   dimensions, volume, and through-hole. Download the exact STEP and its geometry JSON
   together for downstream use.
5. Select another pin and repeat. The browser uses tessellated meshes for display.
   FreeCAD measures and exports the underlying STEP geometry.

The workspace uses the CAD extractor settings in `pipeline.json`. The current
detector expects a horizontal PCB with vertical round plated holes and
axis-aligned rectangular pins. If detection fails after a successful import,
the viewer still opens the assembly and shows the detection error.

The worker translates empty STEP rendering-property lists in a temporary copy
for compatibility with Debian's OpenCASCADE. It stores the uploaded STEP
verbatim and uses the source file's hash in the extraction metadata.

## Files and configuration

- The project's `data/` directory maps to `/data` inside the container. Use
  this directory for uploads, custom configuration files, and results you want
  to keep on the host.
- The dashboard and CLI use the same baseline, `pcbsim_pipeline/pipeline.json`,
  mounted at `/app/pipeline.json`. Relative JSON paths resolve against the
  directory containing that configuration. Surface Evolver is selected
  automatically from the container environment.
- To use a custom config stored in `data/`, refer to it as
  `/data/your_config.json` and use container paths for its inputs. The supplied
  Pico STEP is at `/app/inputs/raspberry_pico_2H.step`.

## Command-line use

```sh
docker compose -f docker/compose.yaml run --rm pipeline python run_pipeline.py --config /app/pipeline.json
docker compose -f docker/compose.yaml run --rm pipeline python run_pipeline.py --config /data/your_config.json
docker compose -f docker/compose.yaml run --rm pipeline python -m pytest dashboard tests
docker compose -f docker/compose.yaml down
```
