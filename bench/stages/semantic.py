"""
Semantic assertion stage runner for IaC/CD benchmark.

Runs pytest assertions against rendered/planned artifacts.
"""

from __future__ import annotations

import subprocess
import logging
import json
from pathlib import Path

log = logging.getLogger(__name__)


def run_semantic(task_dir: Path) -> dict:
    """Run pytest semantic assertions if tests/ exists."""
    test_file = task_dir / "tests" / "test_task.py"
    if not test_file.exists():
        return {
            "passed": True,
            "logs": "no semantic tests",
            "passed_count": 0,
            "total_count": 0,
            "safety_pass": True,
        }

    log.info("Running pytest: %s", test_file)
    try:
        proc = subprocess.run(
            ["python3", "-m", "pytest", "-v", "--json-report", str(test_file)],
            capture_output=True, text=True, timeout=120,
        )

        # Parse pytest output for assertion counts
        output = proc.stdout + proc.stderr
        passed_count = output.count("PASSED")
        total_count = passed_count + output.count("FAILED")

        return {
            "passed": proc.returncode == 0,
            "logs": output[-2000:],
            "passed_count": passed_count,
            "total_count": total_count,
            "safety_pass": "safety" not in output.lower() or "safety PASSED" in output,
        }
    except subprocess.TimeoutExpired:
        return {
            "passed": False,
            "logs": "TIMEOUT: pytest exceeded 120s",
            "passed_count": 0,
            "total_count": 0,
            "safety_pass": False,
        }
    except FileNotFoundError:
        return {
            "passed": False,
            "logs": "NOT FOUND: pytest",
            "passed_count": 0,
            "total_count": 0,
            "safety_pass": False,
        }
