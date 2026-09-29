import os

OPEN_METEO_BASE_URL = "https://api.open-meteo.com/v1/forecast"

# Read the value from the GEMINI_API_KEY environment variable.
# The first argument must be the variable name, not the API key itself.
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
if not GEMINI_API_KEY:
    # Fallback to persisted file (needed on Android where env is not persistent)
    try:
        from pathlib import Path
        import tempfile

        _candidates = []
        try:
            _candidates.append(Path.home() / "CaspianWeather" / "gemini_key.txt")
        except Exception:
            pass
        try:
            _candidates.append(Path.cwd() / "CaspianWeather" / "gemini_key.txt")
        except Exception:
            pass
        try:
            _candidates.append(Path(tempfile.gettempdir()) / "CaspianWeather" / "gemini_key.txt")
        except Exception:
            pass
        for _p in _candidates:
            try:
                if _p.exists():
                    GEMINI_API_KEY = _p.read_text(encoding="utf-8").strip()
                    if GEMINI_API_KEY:
                        os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY
                        break
            except Exception:
                continue
    except Exception:
        pass
# Use the current rolling lite alias: it is available to this project/API key.
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-lite-latest").strip()

# Nowshahr, Mazandaran
DEFAULT_LATITUDE = 36.65
DEFAULT_LONGITUDE = 51.50
DEFAULT_TIMEZONE = "Asia/Tehran"
FORECAST_DAYS = 7
REQUEST_TIMEOUT_SECONDS = 15
