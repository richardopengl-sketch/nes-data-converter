"""Portable existing-runtime lookup, without installation or silent fallbacks."""
import json
import shutil
import subprocess
from pathlib import Path


def require(condition, message):
    if not condition:
        raise ValueError(message)


def run_node(script: Path, payload):
    node = shutil.which("node")
    if node is None:
        raise RuntimeError("Node.js is not on PATH; see README prerequisites")
    try:
        result = subprocess.run(
            [node, str(script)], input=json.dumps(payload), text=True, encoding="utf-8",
            capture_output=True, check=True, timeout=30,
        )
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"Node validation failed ({script.name}, exit {error.returncode}): {error.stderr.strip()}"
        ) from error
    return json.loads(result.stdout)
