"""Check the local installation without claiming that a simulation ran."""
from __future__ import annotations
import argparse
from pathlib import Path
from .common import cli_entry, load_config, section, resolve_path
from .components.experiment_manager import environment_info
from .components.surface_evolver_runner import find_executable


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", default=None)
    parser.add_argument("--config", type=Path, default=Path("pipeline.json"))
    parser.add_argument("--without-native", action="store_true", help="Check CAD/Python setup only")
    args = parser.parse_args(); environment = environment_info(); packages = environment["packages"]
    missing = [name for name in ("numpy", "scipy", "cadquery") if not packages[name]]
    if packages.get("cadquery") and tuple(map(int, packages["cadquery"].split(".")[:2])) < (2,8):
        missing.append("cadquery>=2.8")
    requested = args.executable
    if requested is None and args.config.is_file():
        requested = section(load_config(args.config), "surface_evolver").get("executable")
        if requested and ("/" in requested or "\\" in requested):
            requested = str(resolve_path(requested, args.config.resolve().parent))
    executable = find_executable(requested)
    if executable is None and not args.without_native: missing.append("Surface Evolver executable")
    return {"status": "success" if not missing else "failed", "environment": environment,
            "surface_evolver_executable": executable, "missing": missing,
            "native_simulation_executed": False,
            "hint": 'Install Python/CAD dependencies with python -m pip install -e ".[cad,test]"; install Surface Evolver separately and configure its executable.'}

if __name__ == "__main__":
    cli_entry(main)
