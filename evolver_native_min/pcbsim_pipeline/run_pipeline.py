#!/usr/bin/env python3
"""Convenience launcher; the manager is also independently importable."""
from pcbsim.common import cli_entry
from pcbsim.components.experiment_manager import main
if __name__ == "__main__":
    cli_entry(main)
