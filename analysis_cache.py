from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from utils import to_persian_digits

try:
    from settings_store import get_app_dir as _get_app_dir

    CACHE_DIR = _get_app_dir()
except Exception:
    import tempfile

    try:
        CACHE_DIR = Path.cwd() / "CaspianWeather"
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        CACHE_DIR = Path(tempfile.gettempdir()) / "CaspianWeather"
CACHE_PATH = CACHE_DIR / "analysis_cache.json"
MAX_AGE = timedelta(hours=24)
MIN_SIGNIFICANT_CHANGE_AGE = timedelta(hours=6)
REFRESH_HOUR = 8


def _now() -> datetime:
    return datetime.now().astimezone()


def load_cache() -> dict[str, Any] | None:
    try:
        if not CACHE_PATH.exists():
            return None
        with CACHE_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
        if not isinstance(data, dict) or not data.get("analysis"):
            return None
        return data
    except (OSError, json.JSONDecodeError, TypeError):
        return None


def save_cache(analysis: str, forecast_snapshot: dict) -> None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        return
    data = {
        "generated_at": _now().isoformat(),
        "analysis": analysis,
        "forecast_snapshot": forecast_snapshot,
    }
    temporary_path = CACHE_PATH.with_suffix(".tmp")
    with temporary_path.open("w", encoding="utf-8") as file:
        json.dump(data, file, ensure_ascii=False, indent=2)
    temporary_path.replace(CACHE_PATH)


def _daily_snapshot(multimodel_data: dict) -> dict:
    snapshot = {}
    for model_id, model_data in multimodel_data.get("models", {}).items():
        daily = model_data.get("daily", {})
        snapshot[model_id] = {
            "temperature_max": [round(float(v), 1) for v in daily.get("temperature_max", [])[:3]],
            "temperature_min": [round(float(v), 1) for v in daily.get("temperature_min", [])[:3]],
            "precipitation_sum": [round(float(v), 1) for v in daily.get("precipitation_sum", [])[:3]],
            "precipitation_probability": [round(float(v)) for v in daily.get("precipitation_probability", [])[:3]],
        }
    return snapshot


def _is_significant_change(old: dict, new: dict) -> bool:
    for model_id, current in new.items():
        previous = old.get(model_id, {})
        for key in ("temperature_max", "temperature_min"):
            old_values = previous.get(key, [])
            new_values = current.get(key, [])
            if len(old_values) != len(new_values):
                return True
            if any(abs(a - b) >= 3 for a, b in zip(old_values, new_values)):
                return True
        old_rain = previous.get("precipitation_sum", [])
        new_rain = current.get("precipitation_sum", [])
        if len(old_rain) != len(new_rain) or any(abs(a - b) >= 5 for a, b in zip(old_rain, new_rain)):
            return True
        old_probability = previous.get("precipitation_probability", [])
        new_probability = current.get("precipitation_probability", [])
        if len(old_probability) != len(new_probability) or any(abs(a - b) >= 25 for a, b in zip(old_probability, new_probability)):
            return True
    return False


def should_refresh(cache: dict | None, multimodel_data: dict, force: bool = False) -> bool:
    if force or not cache:
        return True
    try:
        generated_at = datetime.fromisoformat(cache["generated_at"])
        age = _now() - generated_at.astimezone()
    except (KeyError, TypeError, ValueError):
        return True

    current_snapshot = _daily_snapshot(multimodel_data)
    old_snapshot = cache.get("forecast_snapshot", {})
    if age >= MIN_SIGNIFICANT_CHANGE_AGE and _is_significant_change(old_snapshot, current_snapshot):
        return True

    today_refresh_time = _now().replace(hour=REFRESH_HOUR, minute=0, second=0, microsecond=0)
    scheduled_due = _now() >= today_refresh_time and generated_at < today_refresh_time
    return age >= MAX_AGE and scheduled_due


def cache_snapshot(multimodel_data: dict) -> dict:
    return _daily_snapshot(multimodel_data)


def format_generated_at(cache: dict | None) -> str:
    if not cache:
        return ""
    try:
        generated = datetime.fromisoformat(cache["generated_at"]).astimezone()
        text = generated.strftime("%Y/%m/%d - %H:%M")
        return to_persian_digits(text)
    except (KeyError, TypeError, ValueError):
        return ""
