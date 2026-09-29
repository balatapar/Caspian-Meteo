from __future__ import annotations

import signal
import _signal
import threading

try:
    _orig_signal = _signal.signal
    def _safe_signal(sig, handler):
        if threading.current_thread() is not threading.main_thread():
            return None
        try:
            return _orig_signal(sig, handler)
        except (ValueError, RuntimeError):
            pass
        return None
    _signal.signal = _safe_signal
    signal.signal = _safe_signal
except Exception:
    pass

import asyncio
import flet as ft

import config
from localization import Strings
from settings_store import load_settings, save_settings, save_gemini_key, load_gemini_key, reset_to_default_location, DEFAULT_FAVORITES
from weather_service import get_daily_and_hourly_weather
from ui_components.weather_charts import build_weather_charts
from ui_components.weekly_analysis_view import WeeklyAnalysisView
from ui_components.widgets import action_button
from utils import (
    format_date,
    format_hour,
    format_percentage,
    format_precipitation,
    format_temperature,
    format_wind_speed,
)

BG = "#1c201a"
BG_CARD = "#2b3228"
TEXT = "#f0e8d5"
MUTED = "#b8ad93"
BLUE = "#e6c656"
TEAL = "#7fb069"
FIELD_BG = "#353d31"

WEATHER_LABELS = {
    0: "آسمان صاف", 1: "کمی ابری", 2: "نیمه‌ابری", 3: "ابری",
    45: "مه‌آلود", 48: "مه یخ‌زده", 51: "نم‌نم باران", 53: "بارش پراکنده",
    61: "باران سبک", 63: "باران", 65: "باران شدید", 71: "برف سبک",
    73: "برف", 80: "رگبار پراکنده", 95: "رعدوبرق", 99: "رعدوبرق و تگرگ شدید"
}

def weather_label(code: int | None) -> str:
    return WEATHER_LABELS.get(code, "وضعیت جوی نامشخص")

class CaspianWeatherApp(ft.Container):
    def __init__(self, page: ft.Page):
        # --- CRITICAL FIX START ---
        self._page = page
        # --- CRITICAL FIX END ---

        super().__init__(expand=True, bgcolor=BG)

        self.settings = load_settings()
        self.favorites = self.settings.get("favorites", DEFAULT_FAVORITES)
        self.selected_models = set(self.settings.get("models", ["gfs_seamless"]))

        self._is_mobile = self._detect_mobile()
        self._sidebar_open = not self._is_mobile

        # UI Components references
        self.favorite_dropdown = ft.Dropdown(
            label="شهرهای ذخیره‌شده",
            color=TEXT, bgcolor=FIELD_BG, border_color="#5a6658", focused_border_color=TEAL,
        )
        self.location_name = ft.TextField(
            label="نام مکان", value=self.settings.get("location_name", ""),
            color=TEXT, bgcolor=FIELD_BG, border_color="#5a6658", focused_border_color=TEAL,
        )
        self.latitude = ft.TextField(
            label="عرض جغرافیایی", value=str(self.settings.get("latitude", "")),
            label_style=ft.TextStyle(size=13),
            color=TEXT, bgcolor=FIELD_BG, border_color="#5a6658", focused_border_color=TEAL,
            expand=True
        )
        self.longitude = ft.TextField(
            label="طول جغرافیایی", value=str(self.settings.get("longitude", "")),
            label_style=ft.TextStyle(size=13),
            color=TEXT, bgcolor=FIELD_BG, border_color="#5a6658", focused_border_color=TEAL,
            expand=True
        )
        self.timezone = ft.TextField(
            label="منطقه زمانی", value=self.settings.get("timezone", ""),
            color=TEXT, bgcolor=FIELD_BG, border_color="#5a6658", focused_border_color=TEAL,
        )
        try:
            _saved_key = load_gemini_key() or config.GEMINI_API_KEY or ""
        except Exception:
            _saved_key = config.GEMINI_API_KEY or ""
        self.gemini_key = ft.TextField(
            label="کلید Gemini", password=True, can_reveal_password=True,
            value=_saved_key,
            color=TEXT, bgcolor=FIELD_BG, border_color="#5a6658", focused_border_color=TEAL,
        )
        if _saved_key:
            config.GEMINI_API_KEY = _saved_key

        # Model checkboxes
        self.model_checks = {
            "gfs_seamless": ft.Checkbox(label="GFS — آمریکا", value="gfs_seamless" in self.selected_models, fill_color=TEAL, check_color=BG),
            "ecmwf_ifs025": ft.Checkbox(label="ECMWF — اروپا", value="ecmwf_ifs025" in self.selected_models, fill_color=TEAL, check_color=BG),
            "icon_seamless": ft.Checkbox(label="ICON — آلمان", value="icon_seamless" in self.selected_models, fill_color=TEAL, check_color=BG),
        }

        self.status_text = ft.Text("", size=11, color=TEAL)

        # Views
        self.daily_view = ft.Column(expand=True, scroll=ft.ScrollMode.AUTO, spacing=12)
        self.weekly_view = WeeklyAnalysisView()

        # Buttons
        self.sidebar_refresh_btn = action_button(Strings.REFRESH, on_click=lambda _: self.refresh_from_fields(), icon=ft.Icons.REFRESH, bgcolor=BLUE, color=BG)
        self.save_btn = action_button(Strings.SAVE_SETTINGS, on_click=self._save_settings, bgcolor=BLUE, color=BG)
        self.use_favorite_btn = action_button("استفاده از شهر انتخاب‌شده", on_click=self._use_favorite, bgcolor=TEAL, color=BG)

        # Build layout
        self._build_sidebar()
        self._build_main_area()

        # Placeholder so the dashboard tab is never blank before first fetch
        self.daily_view.controls = [
            ft.Row([ft.ProgressRing(), ft.Text(Strings.LOADING, color=MUTED)], alignment=ft.MainAxisAlignment.CENTER)
        ]

    def _detect_mobile(self) -> bool:
        try:
            plat = getattr(self._page, "platform", None)
            plat_value = getattr(plat, "value", plat)
            plat_str = str(plat_value or "").lower()
            if plat_str in ("android", "android_tv", "ios"):
                return True
            width = getattr(self._page, "width", None)
            if isinstance(width, (int, float)) and width < 600:
                return True
        except Exception:
            pass
        return False

    def _apply_platform_layout(self):
        self._build_sidebar()
        self._build_main_area()
        if self._page:
            self._page.update()

    def did_mount(self):
        # Re-evaluate now that the page is mounted and has a real size.
        is_mobile = self._detect_mobile()
        if is_mobile != self._is_mobile:
            self._is_mobile = is_mobile
            self._sidebar_open = not is_mobile
            self._apply_platform_layout()

        if self._page is not None:
            self._page.on_resize = self._on_resize

        # Fetch weather data
        try:
            if self._page:
                self._page.run_task(self.load_weather)
        except Exception:
            try:
                asyncio.create_task(self.load_weather())
            except Exception:
                pass

    def _on_resize(self, e):
        is_mobile = self._detect_mobile()
        if is_mobile != self._is_mobile:
            self._is_mobile = is_mobile
            self._sidebar_open = not is_mobile
            self._apply_platform_layout()

    def refresh_from_fields(self):
        # Refresh handler: persist field values first so a city change is real.
        try:
            self._save_settings(None)
        except Exception:
            try:
                asyncio.create_task(self.load_weather())
            except Exception:
                pass

    def _build_sidebar(self):
        # Populate favorite dropdown options
        self.favorite_dropdown.options = [ft.dropdown.Option(key=str(i), text=f["name"]) for i, f in enumerate(self.favorites)]

        self.sidebar = ft.Container(
            width=280,
            bgcolor="#161a14",
            padding=16,
            visible=True,
            content=ft.ListView(
                expand=True,
                spacing=10,
                controls=[
ft.Row([ft.Image(src="/branding/caspian-weather-icon.png", width=36, height=36), ft.Text(Strings.APP_TITLE, size=18, weight=ft.FontWeight.BOLD, color=TEXT)]),
                    ft.Divider(color="#4a5548"),
                    ft.Text("تنظیمات و مکان", size=14, weight=ft.FontWeight.BOLD, color=BLUE),
                    self.favorite_dropdown,
                    self.use_favorite_btn,
                    ft.Row([self.sidebar_refresh_btn], alignment=ft.MainAxisAlignment.END),
                    ft.Divider(color="#4a5548"),
                    ft.Text("شهر جدید", size=13, weight=ft.FontWeight.BOLD, color=TEXT),
                    self.location_name,
ft.Row([self.latitude, self.longitude], spacing=6),
                    self.timezone,
                    ft.TextButton("ذخیره این شهر در علاقمندی‌ها", on_click=self._save_favorite_click, tooltip="شهر جاری را ذخیره کن"),
                    ft.Divider(color="#4a5548"),
                    ft.Text("مدل‌های پیش‌بینی", size=13, weight=ft.FontWeight.BOLD, color=TEXT),
ft.Column(list(self.model_checks.values()), spacing=2),
                    ft.Divider(color="#4a5548"),
                    ft.Text("اتصال Gemini", size=13, weight=ft.FontWeight.BOLD, color=TEXT),
                    self.gemini_key,
                    self.save_btn,
                    self.status_text,
                ]
            )
        )

    def _toggle_sidebar(self, e):
        self._sidebar_open = not self._sidebar_open
        if self._is_mobile:
            self.sidebar_overlay.visible = self._sidebar_open
            self.sidebar_scrim.visible = self._sidebar_open
        else:
            self.sidebar.visible = self._sidebar_open
        if self._page:
            self._page.update()

    def _close_sidebar(self, e=None):
        self._sidebar_open = False
        if self._is_mobile:
            self.sidebar_overlay.visible = False
            self.sidebar_scrim.visible = False
        if self._page:
            self._page.update()

    def _build_main_area(self):
        # Hamburger menu button (mobile only)
        self.menu_button = ft.IconButton(
            icon=ft.Icons.MENU,
            on_click=self._toggle_sidebar,
            icon_color=TEXT,
            visible=self._is_mobile,
        )

        # Tabs (Flet 0.86 API: Tabs(length, content=Column(TabBar, TabBarView)))
        self.tabs = ft.Tabs(
            length=2,
            selected_index=0,
            animation_duration=300,
            on_change=self._on_tab_change,
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(
                        label_color="#e6c656",
                        unselected_label_color="#b8ad93",
                        indicator_color="#7fb069",
                        divider_color="#4a5548",
                        tabs=[
                            ft.Tab(label=ft.Row([ft.Icon(ft.Icons.DASHBOARD, size=16), ft.Text("📊 داشبورد و پیش‌بینی")])),
                            ft.Tab(label=ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME, size=16), ft.Text("📝 تحلیل سینوپتیک هفتگی")])),
                        ],
                    ),
                    ft.TabBarView(
                        expand=True,
                        controls=[self.daily_view, self.weekly_view],
                    ),
                ],
            ),
        )

        # Main content area
        main_content = ft.Container(
            expand=True,
            bgcolor=BG,
            padding=12,
            content=self.tabs
        )

        # Mobile top bar with hamburger (offset below status bar / battery)
        self.mobile_top_bar = ft.Container(
            padding=ft.padding.only(top=36, left=8, right=8, bottom=8),
            bgcolor=BG_CARD,
            content=ft.Row([
                self.menu_button,
                ft.Text(Strings.APP_TITLE, size=16, weight=ft.FontWeight.BOLD, color=TEXT, expand=True),
            ]),
            visible=self._is_mobile,
        )

        if self._is_mobile:
            # On mobile: sidebar overlays main content when open
            self.sidebar_scrim = ft.Container(
                expand=True,
                bgcolor="#00000080",
                visible=self._sidebar_open,
                on_click=self._close_sidebar,
            )
            self.sidebar_overlay = ft.Container(
                content=self.sidebar,
                width=260,
                height=None,
                bgcolor="#161a14",
                padding=ft.padding.only(top=36, left=0, right=0, bottom=0),
                left=0,
                top=0,
                bottom=0,
                visible=self._sidebar_open,
            )
            self.content = ft.SafeArea(
                content=ft.Stack([
                    ft.Column([
                        self.mobile_top_bar,
                        main_content,
                    ], expand=True),
                    self.sidebar_scrim,
                    self.sidebar_overlay,
                ], expand=True),
                expand=True,
            )
        else:
            # Desktop: standard sidebar + main layout
            self.content = ft.Row(
                [self.sidebar, ft.VerticalDivider(width=1, color="#4a5548"), main_content],
                expand=True, spacing=0
            )

    async def load_weather(self):
        """Fetches weather data and updates the UI."""
        self.status_text.value = Strings.LOADING
        self.status_text.color = MUTED
        if self._page: self._page.update() # Use _page

        try:
            # Use live field values so Refresh reflects a city change even before Save.
            try:
                live_lat = float(str(self.latitude.value).strip())
            except Exception:
                live_lat = self.settings.get("latitude")
            try:
                live_lon = float(str(self.longitude.value).strip())
            except Exception:
                live_lon = self.settings.get("longitude")
            live_tz = (self.timezone.value or "").strip() or self.settings.get("timezone")
            data = await asyncio.to_thread(
                get_daily_and_hourly_weather,
                live_lat, live_lon, live_tz,
            )
            current = data.get("current", {})
            daily = data.get("daily", {})
            hourly = data.get("hourly", {})

            location_name = self.location_name.value or self.settings.get("location_name", "مکان انتخاب شده")
            
            # Header with Refresh (fresh button instance: Controls are single-parent)
            header_row = ft.Row(
                controls=[
                    ft.Text(f"پیش‌بینی هواشناسی — {location_name}", size=20, weight=ft.FontWeight.BOLD, color=TEXT, expand=True),
                    action_button(Strings.REFRESH, on_click=lambda _: self.refresh_from_fields(), icon=ft.Icons.REFRESH, bgcolor=BLUE, color=BG),
                ],
                alignment=ft.MainAxisAlignment.SPACE_BETWEEN
            )

            # Current card
            temp = current.get("temperature_2m")
            humidity = current.get("relative_humidity_2m")
            wind = current.get("wind_speed_10m")
            rain = current.get("precipitation", 0)
            apparent = current.get("apparent_temperature")
            curr_time = current.get("time")

            current_card = ft.Container(
                padding=16, border_radius=16, bgcolor=BG_CARD,
                border=ft.Border.all(1, "#4a5548"),
                content=ft.Column([
ft.Row([ft.Text(Strings.CURRENT_CONDITIONS, size=13, color=MUTED, expand=True), ft.Text(format_date(curr_time) if curr_time else "", size=12, color=MUTED)]),
ft.Row([
ft.Column([ft.Text(format_temperature(temp), size=40, weight=ft.FontWeight.BOLD, color=TEXT), ft.Text(weather_label(current.get("weather_code")), size=15, color=TEXT)], spacing=2),
                        ft.Text("⛅", size=48),
                    ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
ft.Row([
                        ft.Container(padding=10, bgcolor=FIELD_BG, content=ft.Text(Strings.HUMIDITY + ": " + format_percentage(humidity), size=12, color=TEXT)),
                        ft.Container(padding=10, bgcolor=FIELD_BG, content=ft.Text(Strings.WIND + ": " + format_wind_speed(wind), size=12, color=TEXT)),
                        ft.Container(padding=10, bgcolor=FIELD_BG, content=ft.Text(Strings.FEELS_LIKE + ": " + format_temperature(apparent), size=12, color=TEXT)),
                    ], spacing=8),
                ], spacing=10)
            )

            # Hourly forecast
            all_times = hourly.get("time", [])
            temps = hourly.get("temperature_2m", [])
            probs = hourly.get("precipitation_probability", [])
            hourly_cards = []
            for i in range(min(12, len(all_times))):
                hourly_cards.append(ft.Container(
                    width=76, padding=8, border_radius=10, bgcolor=FIELD_BG,
                    content=ft.Column([ft.Text(format_hour(all_times[i]), size=11, color=MUTED, text_align=ft.TextAlign.CENTER), ft.Text(format_temperature(temps[i]) if i < len(temps) else "—", size=15, weight=ft.FontWeight.BOLD, color=TEXT, text_align=ft.TextAlign.CENTER), ft.Text("☂ " + format_percentage(probs[i]) if i < len(probs) else "0%", size=10, color=TEAL, text_align=ft.TextAlign.CENTER)], horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4)
                ))
            hourly_section = ft.Container(
                padding=14, border_radius=16, bgcolor=BG_CARD, border=ft.Border.all(1, "#4a5548"),
                content=ft.Column([ft.Text(Strings.HOURLY_FORECAST, size=16, weight=ft.FontWeight.BOLD, color=TEXT), ft.Row(controls=hourly_cards, scroll=ft.ScrollMode.AUTO)], spacing=10)
            )

            # Charts (isolated: a chart failure must never blank the dashboard)
            try:
                charts_widget = build_weather_charts(daily)
            except Exception as chart_ex:
                charts_widget = ft.Text(f"نمودارها بارگذاری نشدند ({chart_ex})", size=12, color=MUTED)

            # 7-day list
            daily_cards = []
            maxs = daily.get("temperature_2m_max", [])
            mins = daily.get("temperature_2m_min", [])
            d_times = daily.get("time", [])
            d_probs = daily.get("precipitation_probability_max", [])
            d_codes = daily.get("weather_code", [])

            for i in range(min(7, len(d_times))):
                max_t = maxs[i] if i < len(maxs) else None
                min_t = mins[i] if i < len(mins) else None
                prob = d_probs[i] if i < len(d_probs) else 0
                code = d_codes[i] if i < len(d_codes) else None
                dt = d_times[i]
                daily_cards.append(ft.Container(
                    padding=6, border_radius=10, bgcolor=BG_CARD, border=ft.Border.all(1, "#4a5548"),
                    content=ft.Row([
                        ft.Text(format_date(dt), size=12, weight=ft.FontWeight.BOLD, color=TEXT),
                        ft.Text(weather_label(code), size=11, color=MUTED),
                        ft.Text(format_temperature(max_t), size=12, weight=ft.FontWeight.BOLD, color="#e6c656"),
                        ft.Text(format_temperature(min_t), size=12, color="#a3b18a"),
                        ft.Text(f"\u2602 {format_percentage(prob)}", size=11, color="#7fb069"),
                    ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER)
                ))

            # Two real columns: wide right (current/hourly/charts), narrow left (7-day).
            # daily_view lives in a bounded TabBarView, so disable its own scroll
            # and let each column scroll independently: no more endless page.
            self.daily_view.scroll = None
            right_col = ft.Column([current_card, hourly_section, charts_widget], expand=17, spacing=12, scroll=ft.ScrollMode.AUTO)
            seven_day_card = ft.Container(
                padding=10, border_radius=16, bgcolor=BG_CARD, border=ft.Border.all(1, "#4a5548"),
                content=ft.Column([
                    ft.Text("\u067e\u06cc\u0634\u200c\u0628\u06cc\u0646\u06cc \u06f7 \u0631\u0648\u0632\u0647", size=15, weight=ft.FontWeight.BOLD, color=TEXT),
                    *daily_cards,
                ], spacing=6),
            )
            left_col = ft.Column([seven_day_card], expand=10, spacing=12, scroll=ft.ScrollMode.AUTO)
            self.daily_view.controls = [
                header_row,
                ft.Row([right_col, left_col], spacing=12, expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
            ]
            self.status_text.value = "بازیابی اطلاعات کامل شد."
            self.status_text.color = TEAL
        except Exception as ex:
            self.daily_view.controls = [ft.Container(alignment=ft.Alignment.CENTER, content=ft.Text(Strings.ERROR_FETCHING_WEATHER + " (" + str(ex) + ")", color="#B42318", text_align=ft.TextAlign.CENTER))]
            self.status_text.value = "خطا در بارگذاری داده‌ها."
            self.status_text.color = "#F87171"
        finally:
            if self._page: self._page.update()

    def _on_tab_change(self, e):
        if self._page and e.control.selected_index == 1:
            asyncio.create_task(self.weekly_view.load_analysis_data())

    # --- Favorite/Settings Actions ---
    def _use_favorite(self, e):
        try:
            idx = int(self.favorite_dropdown.value)
            fav = self.favorites[idx]
            self.location_name.value = fav["name"]
            self.latitude.value = str(fav["latitude"])
            self.longitude.value = str(fav["longitude"])
            self.timezone.value = fav["timezone"]
            # Trigger weather load implicitly or wait for user click
            self.status_text.value = "شهر انتخاب شده شد."
            self.status_text.color = TEAL
            if self._page: self._page.update()
        except Exception:
            pass

    def _add_to_favorites(self, e):
        name = self.location_name.value.strip()
        if not name: return
        new_fav = {"name": name, "latitude": float(self.latitude.value), "longitude": float(self.longitude.value), "timezone": self.timezone.value.strip()}
        if not any(f["name"] == name for f in self.favorites):
            self.favorites.append(new_fav)
            self.favorite_dropdown.options = [ft.dropdown.Option(key=str(i), text=f["name"]) for i, f in enumerate(self.favorites)]
            self.status_text.value = "شهر بهRelationships افزوده شد."
            self.status_text.color = TEAL
            if self._page: self._page.update()

    def _save_favorite_click(self, e):
        self._add_to_favorites(e)

    def _save_settings(self, e):
        try:
            # Gather model states
            active_models = [mid for mid, chk in self.model_checks.items() if chk.value]
            if not active_models: active_models = ["gfs_seamless"]

            self.settings = save_settings({
                "location_name": self.location_name.value,
                "latitude": self.latitude.value,
                "longitude": self.longitude.value,
                "timezone": self.timezone.value,
                "models": active_models,
                "favorites": self.favorites,
            })
            if self.gemini_key.value.strip():
                save_gemini_key(self.gemini_key.value)
                config.GEMINI_API_KEY = self.gemini_key.value.strip()

            self.status_text.value = "تنظیمات ذخیره شد."
            self.status_text.color = TEAL
            asyncio.create_task(self.load_weather())
        except Exception as ex:
            self.status_text.value = "خطا در ذخیره تنظیمات: " + str(ex)
            self.status_text.color = "#F87171"
        if self._page: self._page.update()

def main(page: ft.Page):
    page.fonts = {"Vazirmatn": "/fonts/Vazirmatn-Regular.ttf", "Vazirmatn-SemiBold": "/fonts/Vazirmatn-SemiBold.ttf", "Vazirmatn-Bold": "/fonts/Vazirmatn-Bold.ttf"}
    page.theme = ft.Theme(font_family="Vazirmatn")
    page.title = Strings.APP_TITLE
    page.rtl = True
    page.bgcolor = BG
    page.padding = 0
    page.window_width = 1100
    page.window_height = 800
    page.window_resizable = True

    app = CaspianWeatherApp(page)
    page.add(app)
    try:
        page.run_task(app.load_weather)
    except Exception:
        pass

if __name__ == "__main__":
    ft.app(target=main, assets_dir="assets")
