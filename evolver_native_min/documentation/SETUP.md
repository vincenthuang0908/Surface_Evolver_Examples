# Setup

Use Docker with the Compose plugin and support for Linux containers. Run the
same commands from the project root on macOS, Windows, or Linux. Compose selects
the platform supplied by Docker.

```sh
docker compose -f docker/compose.yaml up -d --build
```

Open [localhost:8501](http://localhost:8501). The image includes Python, CadQuery,
and headless Surface Evolver.

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
