"""Small shared contracts; no component imports the experiment manager."""
from __future__ import annotations
import argparse
import hashlib
import json
import logging
import math
import os
from pathlib import Path
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any

class ComponentError(RuntimeError):
    """An actionable, expected component failure."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def read_json(path: str | Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"),
                          parse_constant=lambda x: (_ for _ in ()).throw(ValueError(x)))
    except (OSError, ValueError) as exc:
        raise ComponentError(f"Cannot read JSON {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ComponentError(f"Expected a JSON object in {path}")
    return data


def write_json(path: str | Path, value: Any) -> Path:
    """Atomic replacement: failed runs must never leave half-written reports."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    fd, temp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)
    return path


def sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def resolve_path(value: str | Path, base: str | Path) -> Path:
    path = Path(os.path.expandvars(str(value))).expanduser()
    return path.resolve() if path.is_absolute() else (Path(base) / path).resolve()


def deep_merge(base: dict, overrides: dict) -> dict:
    result = dict(base)
    for key, value in overrides.items():
        result[key] = deep_merge(result.get(key, {}), value) if isinstance(value, dict) and isinstance(result.get(key, {}), dict) else value
    return result


def section(config: dict | None, name: str) -> dict:
    config = config or {}
    return dict(config.get("steps", {}).get(name, config if "steps" not in config else {}))


def load_config(path: str | Path | None) -> dict:
    """Resolve optional per-component config_file relative to its declaring file."""
    if path is None:
        return {}
    path = Path(path).resolve()
    config = read_json(path)
    for name, settings in config.get("steps", {}).items():
        if not isinstance(settings, dict):
            raise ComponentError(f"steps.{name} must be an object")
        if "config_file" in settings:
            external = resolve_path(settings["config_file"], path.parent)
            config["steps"][name] = deep_merge(read_json(external), {k: v for k, v in settings.items() if k != "config_file"})
    return config


def positive(value: Any, name: str, *, allow_zero: bool = False) -> float:
    if isinstance(value, bool):
        raise ComponentError(f"{name} must be a finite number, not a boolean")
    try:
        number = float(value)
    except (ValueError, TypeError) as exc:
        raise ComponentError(f"{name} must be a finite number") from exc
    if not math.isfinite(number) or number < 0 or (number == 0 and not allow_zero):
        raise ComponentError(f"{name} must be finite and {'nonnegative' if allow_zero else 'positive'}")
    return number


def integer(value: Any, name: str, minimum: int = 0, maximum: int = 1000000) -> int:
    n = positive(value, name, allow_zero=True)
    if int(n) != n or not minimum <= n <= maximum:
        raise ComponentError(f"{name} must be an integer from {minimum} to {maximum}")
    return int(n)


def require_file(path: str | Path, label: str = "input") -> Path:
    path = Path(path).resolve()
    if not path.is_file():
        raise ComponentError(f"Missing {label}: {path}")
    return path


def logger_or_default(logger: logging.Logger | None, name: str) -> logging.Logger:
    return logger or logging.getLogger(f"pcbsim.{name}")


def result(component: str, outputs: dict, **details: Any) -> dict:
    return {"schema_version": 1, "component": component, "status": "success",
            "outputs": {k: str(v) for k, v in outputs.items()}, **details}


def cli_entry(function) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s", stream=sys.stderr)
    try:
        report = function()
        if report is not None:
            print(json.dumps(report, indent=2, allow_nan=False))
        if isinstance(report, dict) and report.get("status") in {"failed", "unavailable", "timeout"}:
            raise SystemExit(1)
    except (ComponentError, FileNotFoundError, ValueError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}), file=sys.stderr)
        raise SystemExit(1) from exc


def config_arg(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--config", type=Path, help="pipeline.json or a component settings JSON")
