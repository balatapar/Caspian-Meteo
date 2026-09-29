from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

_APP_DIR: Path | None = None


def get_app_dir() -> Path:
    """Return a writable app data dir (works on Windows, Linux, Android).

    On Android Path.home() can resolve to /data which is not writable,
    so we probe candidates and use the first one we can create.
    """
    global _APP_DIR
    if _APP_DIR is not None:
        return _APP_DIR
    candidates: list[Path] = []
    localappdata = os.getenv("LOCALAPPDATA")
    if localappdata:
        candidates.append(Path(localappdata) / "CaspianWeather")
    try:
        candidates.append(Path.home() / "CaspianWeather")
    except Exception:
        pass
    try:
        candidates.append(Path.cwd() / "CaspianWeather")
    except Exception:
        pass
    try:
        candidates.append(Path(tempfile.gettempdir()) / "CaspianWeather")
    except Exception:
        pass
    for cand in candidates:
        try:
            cand.mkdir(parents=True, exist_ok=True)
            # probe writability
            probe = cand / ".write_test"
            probe.write_text("ok", encoding="utf-8")
            probe.unlink(missing_ok=True)
            _APP_DIR = cand
            return cand
        except Exception:
            continue
    # last resort: cwd (may still fail, caller handles OSError)
    _APP_DIR = Path.cwd()
    return _APP_DIR


def get_settings_path() -> Path:
    return get_app_dir() / "settings.json"


def get_gemini_key_path() -> Path:
    return get_app_dir() / "gemini_key.txt"


SETTINGS_PATH = get_settings_path()

DEFAULT_FAVORITES = [
    {"name": "نوشهر، مازندران", "latitude": 36.65, "longitude": 51.50, "timezone": "Asia/Tehran"},
    {"name": "تهران", "latitude": 35.6892, "longitude": 51.3890, "timezone": "Asia/Tehran"},
    {"name": "رشت، گیلان", "latitude": 37.2808, "longitude": 49.5832, "timezone": "Asia/Tehran"},
]

DEFAULT_SETTINGS = {
    "location_name": DEFAULT_FAVORITES[0]["name"],
    "latitude": DEFAULT_FAVORITES[0]["latitude"],
    "longitude": DEFAULT_FAVORITES[0]["longitude"],
    "timezone": DEFAULT_FAVORITES[0]["timezone"],
    "models": ["gfs_seamless", "ecmwf_ifs025", "icon_seamless"],
    "favorites": DEFAULT_FAVORITES,
}


def load_settings() -> dict[str, Any]:
    try:
        with SETTINGS_PATH.open("r", encoding="utf-8") as file:
            data = json.load(file)
        settings = DEFAULT_SETTINGS.copy()
        settings.update(data if isinstance(data, dict) else {})
        return _validate(settings)
    except (OSError, json.JSONDecodeError, TypeError):
        return DEFAULT_SETTINGS.copy()


def save_settings(settings: dict[str, Any]) -> dict[str, Any]:
    validated = _validate({**DEFAULT_SETTINGS, **settings})
    path = get_settings_path()
    # keep module-level path in sync for legacy imports
    global SETTINGS_PATH
    SETTINGS_PATH = path
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
    except Exception:
        # fall back to cwd if primary dir not writable (Android)
        path = Path.cwd() / "settings.json"
        SETTINGS_PATH = path
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as file:
        json.dump(validated, file, ensure_ascii=False, indent=2)
    temporary.replace(path)
    return validated


def _validate(settings: dict[str, Any]) -> dict[str, Any]:
    try:
        latitude = float(settings["latitude"])
        longitude = float(settings["longitude"])
        if not -90 <= latitude <= 90 or not -180 <= longitude <= 180:
            raise ValueError
    except (KeyError, TypeError, ValueError):
        latitude = DEFAULT_SETTINGS["latitude"]
        longitude = DEFAULT_SETTINGS["longitude"]

    models = settings.get("models", DEFAULT_SETTINGS["models"])
    valid_models = {"gfs_seamless", "ecmwf_ifs025", "icon_seamless"}
    models = [model for model in models if model in valid_models] if isinstance(models, list) else []
    if not models:
        models = DEFAULT_SETTINGS["models"].copy()

    favorites = settings.get("favorites", DEFAULT_FAVORITES)
    if not isinstance(favorites, list) or not favorites:
        favorites = DEFAULT_FAVORITES.copy()

    return {
        "location_name": str(settings.get("location_name") or DEFAULT_SETTINGS["location_name"]).strip(),
        "latitude": latitude,
        "longitude": longitude,
        "timezone": str(settings.get("timezone") or DEFAULT_SETTINGS["timezone"]).strip(),
        "models": models,
        "favorites": favorites,
    }


def reset_to_default_location() -> dict[str, Any]:
    settings = load_settings()
    default = DEFAULT_FAVORITES[0]
    settings.update({
        "location_name": default["name"],
        "latitude": default["latitude"],
        "longitude": default["longitude"],
        "timezone": default["timezone"],
    })
    return save_settings(settings)


def load_gemini_key() -> str:
    """Load persisted Gemini key: env first, then app-dir file (Android)."""
    env_key = os.getenv("GEMINI_API_KEY", "").strip()
    if env_key:
        return env_key
    try:
        p = get_gemini_key_path()
        if p.exists():
            return p.read_text(encoding="utf-8").strip()
    except Exception:
        pass
    return ""


def save_gemini_key(key: str) -> None:
    """Save the key to env, to a file (Android/desktop), and Windows registry."""
    key = key.strip()
    if not key:
        return
    os.environ["GEMINI_API_KEY"] = key
    try:
        kp = get_gemini_key_path()
        kp.parent.mkdir(parents=True, exist_ok=True)
        kp.write_text(key, encoding="utf-8")
    except Exception:
        # file persistence is best-effort; env above still works for session
        pass
    if os.name == "nt":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_SET_VALUE) as registry:
                winreg.SetValueEx(registry, "GEMINI_API_KEY", 0, winreg.REG_SZ, key)
        except Exception:
            pass
