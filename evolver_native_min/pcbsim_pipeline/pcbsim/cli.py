"""Console-script adapters with consistent JSON output and exit codes."""
from .common import cli_entry

def run():
    from .components.experiment_manager import main
    cli_entry(main)

def doctor():
    from .doctor import main
    cli_entry(main)

def evaluate():
    from .components.evaluation import main
    cli_entry(main)
