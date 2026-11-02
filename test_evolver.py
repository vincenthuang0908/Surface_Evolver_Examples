
import subprocess
import csv
from pathlib import Path

# Your Surface Evolver paths
EVOLVER = Path(r"C:\Evolver\evolver.exe")
DATAFILE = Path(r"C:\Evolver\fe\cube.fe")

# Check that both files exist
if not EVOLVER.is_file():
    raise FileNotFoundError(f"Evolver not found: {EVOLVER}")

if not DATAFILE.is_file():
    raise FileNotFoundError(f"Datafile not found: {DATAFILE}")

# Different numbers of evolution steps
steps_list = [5, 10, 20, 50, 100]

results = []

for steps in steps_list:
    print(f"\nRunning simulation with {steps} steps...")

    # Commands sent to Surface Evolver
    commands = f"""g {steps}
print total_energy
q
"""

    try:
        result = subprocess.run(
            [str(EVOLVER), "-x", str(DATAFILE)],
            input=commands,
            text=True,
            capture_output=True,
            timeout=120
        )

        results.append({
            "steps": steps,
            "exit_code": result.returncode,
            "output": result.stdout,
            "errors": result.stderr
        })

        print(f"Completed {steps} steps.")
        print(f"Exit code: {result.returncode}")

        if result.returncode != 0:
            print("Error:", result.stderr)

    except subprocess.TimeoutExpired:
        print(f"Simulation timed out at {steps} steps.")

        results.append({
            "steps": steps,
            "exit_code": "TIMEOUT",
            "output": "",
            "errors": "Simulation exceeded 120 seconds"
        })

# Save results to CSV
output_file = Path("evolver_results.csv")

with output_file.open(
    "w", newline="", encoding="utf-8"
) as f:
    writer = csv.DictWriter(
        f,
        fieldnames=["steps", "exit_code", "output", "errors"]
    )
    writer.writeheader()
    writer.writerows(results)

print("\nAll simulations finished!")
print(f"Results saved to: {output_file.resolve()}")
