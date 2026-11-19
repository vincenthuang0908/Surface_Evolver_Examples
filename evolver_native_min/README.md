# PCB solder experiments

Simulate the equilibrium shape of one top-side solder fillet on a through-hole PCB connection and export the resulting solder and PCB assembly as STEP files.

```text
pcbsim_pipeline/   Simulation package, CLI, configs, example inputs, and tests
dashboard/         Streamlit interface and process management
docker/            Dockerfile and Compose service
documentation/     Setup, workflow, model notes, and experiment write-ups
data/              Local uploads, experiments, and historical archive
```

From the project root, start the dashboard with Docker and the Compose plugin.

```sh
docker compose -f docker/compose.yaml up -d --build
```

Open [localhost:8501](http://localhost:8501), select the supplied Pico or upload a STEP assembly, choose a connection, and run an experiment. Reports and STEP exports are saved under `data/experiments/`. The project source and baseline configuration are mounted from the checkout.

Choose **Advanced JSON** in the dashboard to edit or load the full pipeline configuration, attach inputs, name the experiment, and select which stages to run. Paths use the container filesystem. The local `data/` directory is available as `/data`, so an output root such as `/data/custom_runs` stays on the host and can be opened in the **Experiments** tab.

Open **Tutorial & Documentation** for a guided Run 6 example, a loadable configuration, archived reference metrics, and a list of the files each stage produces.

Run the same pipeline from the command line without starting the dashboard.

```sh
docker compose -f docker/compose.yaml run --rm pipeline python run_pipeline.py --config /app/pipeline.json
```

The [setup guide](documentation/SETUP.md) covers Docker commands and data storage. The [pipeline guide](documentation/RUN_PIPELINE.md) covers inputs, calibration, evaluation, and model limits. The model assumes a fully filled plated barrel, a rectangular pin, a circular plated hole, and a top-side fillet at static equilibrium.

Git ignores `data/`, which holds local uploads, results, and optional archives. The tutorial includes the Run 6 preset for a fresh checkout.
