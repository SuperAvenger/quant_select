from __future__ import annotations

import os
from typing import Any, Dict

import yaml


def load_config(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if not isinstance(cfg, dict):
        raise ValueError("Config file must be a mapping.")
    tushare_cfg = cfg.get("tushare", {})
    token_env = tushare_cfg.get("token_env")
    if not token_env:
        raise ValueError("Missing tushare.token_env in config.")
    token = os.getenv(token_env)
    if not token:
        raise EnvironmentError(
            f"Environment variable '{token_env}' is required for TuShare token."
        )
    tushare_cfg["token"] = token
    cfg["tushare"] = tushare_cfg
    data_cfg = cfg.get("data", {})
    adj = str(data_cfg.get("adj", "")).lower()
    if adj not in {"qfq", "hfq"}:
        raise ValueError("data.adj must be 'qfq' or 'hfq' for adjusted prices.")
    data_cfg["adj"] = adj
    cfg["data"] = data_cfg
    return cfg
