from __future__ import annotations

import json
import os
import re
import time
from dataclasses import dataclass
from typing import Callable, Dict, Optional, Set

import pandas as pd


def _safe_key(key: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", key)


def _resolve_format(fmt: str) -> str:
    fmt = (fmt or "").strip().lower()
    if fmt not in {"parquet", "csv"}:
        fmt = "parquet"
    if fmt == "parquet":
        try:
            pd.io.parquet.get_engine("auto")
        except Exception:
            return "csv"
    return fmt


@dataclass
class LocalStore:
    root: str
    fmt: str

    @classmethod
    def from_config(cls, cfg: Dict) -> Optional["LocalStore"]:
        data_cfg = cfg.get("data", {})
        cache_dir = data_cfg.get("cache_dir")
        if not cache_dir:
            return None
        fmt = _resolve_format(str(data_cfg.get("store_format", "parquet")))
        return cls(root=cache_dir, fmt=fmt)

    def _path(self, key: str) -> str:
        filename = f"{_safe_key(key)}.{self.fmt}"
        return os.path.join(self.root, filename)

    def _manifest_path(self) -> str:
        return os.path.join(self.root, "cache_manifest.json")

    def _load_manifest(self) -> Dict[str, Dict[str, object]]:
        path = self._manifest_path()
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            return {}
        if not isinstance(data, dict):
            return {}
        return data

    def _save_manifest(self, manifest: Dict[str, Dict[str, object]]) -> None:
        os.makedirs(self.root, exist_ok=True)
        path = self._manifest_path()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=True, indent=2)

    def load_df(self, key: str) -> Optional[pd.DataFrame]:
        path = self._path(key)
        if not os.path.exists(path):
            return None
        if self.fmt == "parquet":
            return pd.read_parquet(path)
        return pd.read_csv(path)

    def load_df_safe(self, key: str) -> Optional[pd.DataFrame]:
        try:
            return self.load_df(key)
        except Exception:
            return None

    def save_df(self, key: str, df: pd.DataFrame) -> None:
        os.makedirs(self.root, exist_ok=True)
        path = self._path(key)
        if self.fmt == "parquet":
            df.to_parquet(path, index=False)
        else:
            df.to_csv(path, index=False)

    def get_or_fetch(
        self, key: str, fetcher: Callable[[], pd.DataFrame]
    ) -> pd.DataFrame:
        cached = self.load_df(key)
        if cached is not None:
            return cached
        df = fetcher()
        if df is None:
            df = pd.DataFrame()
        self.save_df(key, df)
        return df

    def list_cached_dates(self, prefix: str) -> Set[str]:
        if not os.path.isdir(self.root):
            return set()
        safe_prefix = _safe_key(prefix)
        pattern = re.compile(rf"^{re.escape(safe_prefix)}(\\d{{8}})\\.{re.escape(self.fmt)}$")
        dates: Set[str] = set()
        for name in os.listdir(self.root):
            match = pattern.match(name)
            if match:
                dates.add(match.group(1))
        return dates

    def get_manifest_dates(self, key: str) -> Set[str]:
        manifest = self._load_manifest()
        entry = manifest.get(key, {})
        dates = entry.get("dates", [])
        if not isinstance(dates, list):
            return set()
        return {str(x) for x in dates}

    def record_dates(self, key: str, dates: Set[str]) -> None:
        if not dates:
            return
        manifest = self._load_manifest()
        entry = manifest.get(key, {})
        existing = entry.get("dates", [])
        if not isinstance(existing, list):
            existing = []
        merged = {str(x) for x in existing}
        merged.update({str(x) for x in dates})
        entry = {
            "dates": sorted(merged),
            "updated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        manifest[key] = entry
        self._save_manifest(manifest)
