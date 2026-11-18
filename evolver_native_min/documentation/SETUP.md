# Setup

From the repository root, with Docker Desktop running in Linux container mode:

```powershell
docker compose -f docker/compose.yaml up -d --build
```

Open [localhost:8501](http://localhost:8501). The image includes Python, CadQuery, and native Surface Evolver. Compose saves uploads and experiments in `data/` on the host.

If a clean build fails because this PC's HTTPS inspection certificate is missing from the container, use the archived public CA as a Docker build secret:

```powershell
docker build -f docker/Dockerfile --secret id=build_ca,src=data/archive/docker-validation/build-ca.pem -t pcbsim-pipeline:local .
docker compose -f docker/compose.yaml up -d --no-build
```

To run the pipeline directly on Windows, install Python 3.12 and Surface Evolver, then run from the repository root:

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e './pcbsim_pipeline[cad,test]'
```

Set `steps.surface_evolver.executable` in `pcbsim_pipeline/pipeline.json` to the installed Windows executable path. Relative paths in that file resolve from its directory.

```powershell
.\.venv\Scripts\python.exe pcbsim_pipeline/run_pipeline.py --config pcbsim_pipeline/pipeline.json
```

See [RUN_PIPELINE.md](RUN_PIPELINE.md) for inputs, expected outputs, and validation. The original standalone experiments and their Windows support files are preserved under `data/archive/pre-docker/`.
