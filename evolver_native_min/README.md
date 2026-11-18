# PCB solder experiments

Simulate the equilibrium shape of one top-side solder fillet on a through-hole PCB connection and export the resulting solder and PCB assembly as STEP files.

```text
pcbsim_pipeline/   Simulation package, CLI, configs, example inputs, and tests
dashboard/         Streamlit interface and process management
docker/            Dockerfile and Compose service
documentation/     Setup, workflow, model notes, and experiment write-ups
data/              Local uploads, experiments, and historical archive
```

From the project root, start the dashboard with Docker Desktop running in Linux container mode.

```powershell
docker compose -f docker/compose.yaml up -d --build
```

Open [localhost:8501](http://localhost:8501), select the supplied Pico or upload a STEP assembly, choose a connection, and run an experiment. Reports and STEP exports are saved under `data/experiments/`. Python edits are visible through the live source mounts.

Run the same pipeline from the command line without starting the dashboard.

```powershell
docker compose -f docker/compose.yaml run --rm pipeline python run_pipeline.py --config /app/pipeline.docker.json
```

For a native Python setup or a clean build on a machine with HTTPS inspection, see [Setup](documentation/SETUP.md). The [pipeline guide](documentation/RUN_PIPELINE.md) covers inputs, calibration, evaluation, and model limits. The model assumes a fully filled plated barrel, a rectangular pin, a circular plated hole, and a top-side fillet at static equilibrium.

Historical files kept in this checkout:

- `data/archive/pre-docker/pcbsim_pipeline/experiments/` contains the original PCB runs, including Windows baseline `run_006`.
- `data/archive/pre-docker/results/` contains the standalone experiments' generated results. Their model files, source, and entry points are in the same archive.
- `data/archive/docker-validation/` contains the earlier Docker validation records.

Git ignores `data/`. The pre-Docker files that were tracked are available in commit `fce6c938`. Keep a separate backup of local runs and other archive files.
