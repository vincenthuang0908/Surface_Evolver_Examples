## Setup

In the `evolver_native_min` folder.

Setting up venv, dependencies, and generating .fe models:
```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe generate_models.py
```

Example of running .fe models and simulations:
```powershell
.\.venv\Scripts\python.exe run_native.py --model models/10_pin_fillet.fe --executable "C:\Evolver\evolver.exe"
```

General syntax:
```powershell
.\.venv\Scripts\python.exe run_native.py --model <model_path> --executable "<evolver_path>"
```

If model files already exist, the generation step is optional. The generator
replaces the `.fe` and `.json` files, so preserve any custom edits first.

Outputs are written to `results/native/<model_name>/`. Inspect `stdout.log`
and `manifest.json` for native errors and numerical acceptance checks.
