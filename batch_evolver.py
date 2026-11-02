
import subprocess
import csv
from pathlib import Path

# Replace these with your working paths
EVOLVER = Path(r"C:\Evolver\evolver.exe")
DATAFILE = Path(r"C:\Evolver\fe\cube.fe")

steps_list = [5, 10, 20, 50, 100]
results = []

for steps in steps_list:
    commands = f"""g {steps}
print total_energy
q
"""

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

    print(
        f"Steps: {steps}, "
        f"Exit code: {result.returncode}"
    )

with open("evolver_results.csv", "w",
          newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(
        f, fieldnames=results[0].keys()
    )
    writer.writeheader()
    writer.writerows(results)

print("Results saved to evolver_results.csv")
