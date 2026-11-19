# syntax=docker/dockerfile:1
# Build with the project root as context; docker/compose.yaml sets this up.
FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SURFACE_EVOLVER_EXE=/usr/bin/evolver-nox-d

# Debian supplies the real Surface Evolver 2.70 solver without a display server.
# The shared graphics libraries below are needed by CadQuery's VTK dependency.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        evolver-nox libgl1 libglib2.0-0 libxrender1 libxext6 libsm6 \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY pcbsim_pipeline/pyproject.toml ./
COPY pcbsim_pipeline/pcbsim ./pcbsim
# Optional build-only CA for hosts with HTTPS inspection (no TLS bypass).
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then \
        cat /etc/ssl/certs/ca-certificates.crt /run/secrets/build_ca > /tmp/build-ca.pem; \
        export PIP_CERT=/tmp/build-ca.pem; \
    fi; \
    python -m pip install --no-cache-dir \
        ".[cad,test]" "cadquery==2.8.0" "numpy==2.3.5" \
        "scipy==1.17.0" "pytest==9.0.2" "streamlit==1.67.0" "psutil==7.1.3" \
    && rm -f /tmp/build-ca.pem

COPY dashboard ./dashboard
COPY pcbsim_pipeline/run_pipeline.py pcbsim_pipeline/reproduce.py ./
COPY pcbsim_pipeline/tests ./tests
COPY pcbsim_pipeline/inputs ./inputs
COPY pcbsim_pipeline/config ./config
COPY pcbsim_pipeline/pipeline.json ./pipeline.json

CMD ["python", "run_pipeline.py", "--config", "/app/pipeline.json"]
