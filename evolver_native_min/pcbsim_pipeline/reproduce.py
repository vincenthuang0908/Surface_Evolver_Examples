#!/usr/bin/env python3
"""Rerun saved inputs, then compare numerical, mesh and STEP results."""
import argparse
from pathlib import Path
from pcbsim.common import cli_entry
from pcbsim.components.experiment_manager import reproduce_experiment

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", required=True, help="run_001, an integer such as 1, or an experiment directory")
    parser.add_argument("--experiments-dir", type=Path, default=Path("experiments"))
    parser.add_argument("--experiment-id")
    parser.add_argument("--allow-code-change", action="store_true")
    args = parser.parse_args()
    value = f"run_{int(args.run):03d}" if args.run.isdigit() else args.run
    path = Path(value)
    if not path.is_dir(): path = args.experiments_dir/value
    return reproduce_experiment(path, experiment_id=args.experiment_id, allow_code_change=args.allow_code_change)

if __name__ == "__main__":
    cli_entry(main)
