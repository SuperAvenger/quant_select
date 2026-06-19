from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict


SECRET_KEYS = {"token", "api_key", "secret", "password"}


def _redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[REDACTED]" if key.lower() in SECRET_KEYS else _redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [_redact(item) for item in value]
    return value


def config_sha256(cfg: Dict[str, Any]) -> str:
    safe_cfg = _redact(deepcopy(cfg))
    payload = json.dumps(safe_cfg, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _code_revision(repo_root: Path) -> str:
    github_sha = os.getenv("GITHUB_SHA")
    if github_sha:
        return github_sha
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return result.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def build_run_metadata(cfg: Dict[str, Any], config_path: str, repo_root: Path) -> Dict[str, Any]:
    """Describe the effective research run without retaining credentials."""
    execution = cfg.get("execution", {})
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "mode": "backtest_research",
        "automatic_order_submission": False,
        "config_path": config_path,
        "config_sha256": config_sha256(cfg),
        "code_revision": _code_revision(repo_root),
        "python_version": platform.python_version(),
        "strategy": cfg.get("strategy", {}).get("name"),
        "data": {
            "start": cfg.get("backtest", {}).get("start"),
            "end": cfg.get("backtest", {}).get("end"),
            "calendar_exchange": cfg.get("backtest", {}).get("calendar_exchange"),
            "adjustment": cfg.get("data", {}).get("adj"),
            "pull_mode": cfg.get("data", {}).get("pull_mode", "by_ts_code"),
        },
        "fee_model": {
            "slippage_bps": execution.get("slippage_bps"),
            "commission_bps": execution.get("commission_bps"),
            "commission_bps_by_prefix": execution.get("commission_bps_by_prefix", {}),
            "stamp_tax_bps": execution.get("stamp_tax_bps"),
            "stamp_tax_bps_by_prefix": execution.get("stamp_tax_bps_by_prefix", {}),
            "min_commission": execution.get("min_commission"),
        },
        "universe": {"max_names": cfg.get("universe", {}).get("max_names")},
    }
