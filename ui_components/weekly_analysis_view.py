from __future__ import annotations

import asyncio

import flet as ft

from analysis_cache import cache_snapshot, format_generated_at, load_cache, save_cache, should_refresh
import config
from localization import Strings
from multimodel_service import get_multi_model_forecast
from synoptic_analysis import get_multimodel_analysis
from synoptic_service import get_synoptic_context
from settings_store import load_settings
from ui_components.widgets import action_button
from utils import format_precipitation, format_temperature

BG_CARD = "#2b3228"
TEXT = "#f0e8d5"
MUTED = "#b8ad93"
GOLD = "#e6c656"
OLIVE = "#7fb069"
SAGE = "#a3b18a"
BORDER = "#4a5548"
DARK = "#1c201a"

MODEL_LABELS = {"gfs_seamless": "GFS", "ecmwf_ifs025": "ECMWF", "icon_seamless": "ICON"}
MODEL_ORDER = ["gfs_seamless", "ecmwf_ifs025", "icon_seamless"]


def surface(content: ft.Control, padding: int = 16) -> ft.Container:
    return ft.Container(
        content=content,
        padding=padding,
        border_radius=18,
        bgcolor=BG_CARD,
        border=ft.Border.all(1, BORDER),
        shadow=ft.BoxShadow(blur_radius=14, color="#30000000", offset=ft.Offset(0, 4)),
    )


def _split_sections(analysis: str):
    """Split analysis into intro + per-model sections (GFS/ECMWF/ICON)."""
    markers = [("GFS", "\u062a\u062d\u0644\u06cc\u0644 GFS"), ("ECMWF", "\u062a\u062d\u0644\u06cc\u0644 ECMWF"), ("ICON", "\u062a\u062d\u0644\u06cc\u0644 ICON")]
    hits = []
    for label, marker in markers:
        idx = analysis.find(marker)
        if idx != -1:
            hits.append((idx, label, marker))
    if not hits:
        return analysis, []
    hits.sort()
    intro = analysis[:hits[0][0]].strip()
    sections = []
    for n, (idx, label, marker) in enumerate(hits):
        end = hits[n + 1][0] if n + 1 < len(hits) else len(analysis)
        body = analysis[idx:end].strip()
        sections.append((f"\u062a\u062d\u0644\u06cc\u0644 {label}", body))
    return intro, sections


def _model_rows(snapshot: dict):
    rows = []
    for model_id in MODEL_ORDER:
        if model_id in snapshot:
            rows.append((model_id, snapshot[model_id]))
    for model_id, data in snapshot.items():
        if model_id not in MODEL_LABELS:
            rows.append((model_id, data))
    return rows


def _signal_text(total_rain: float) -> str:
    if total_rain >= 10:
        return "\U0001f327 \u0628\u0627\u0631\u0634\u06cc"
    if total_rain >= 2:
        return "\U0001f326 \u0628\u0627\u0631\u0634 \u067e\u0631\u0627\u06a9\u0646\u062f\u0647"
    return "\u2600 \u067e\u0627\u06cc\u062f\u0627\u0631"


def _comparison_table(snapshot: dict | None) -> ft.Control:
    if not snapshot:
        return surface(ft.Text("\u062f\u0627\u062f\u0647 \u0645\u062f\u0644\u200c\u0647\u0627 \u062f\u0631 \u062f\u0633\u062a\u0631\u0633 \u0646\u06cc\u0633\u062a.", size=12, color=MUTED))
    rows = []
    for model_id, data in _model_rows(snapshot):
        label = MODEL_LABELS.get(model_id, model_id)
        maxes = [float(v) for v in data.get("temperature_max", [])]
        mines = [float(v) for v in data.get("temperature_min", [])]
        rains = [float(v) for v in data.get("precipitation_sum", [])]
        hi = max(maxes) if maxes else None
        lo = min(mines) if mines else None
        total = round(sum(rains), 1) if rains else 0.0
        rows.append(
            ft.DataRow(cells=[
                ft.DataCell(ft.Text(label, size=12, weight=ft.FontWeight.BOLD, color=GOLD)),
                ft.DataCell(ft.Text(format_temperature(hi) if hi is not None else "\u2014", size=12, color=TEXT)),
                ft.DataCell(ft.Text(format_temperature(lo) if lo is not None else "\u2014", size=12, color=TEXT)),
                ft.DataCell(ft.Text(format_precipitation(total), size=12, color=TEXT)),
                ft.DataCell(ft.Text(_signal_text(total), size=11, color=OLIVE)),
            ])
        )
    return surface(
        ft.Column([
            ft.Text("\u0645\u0642\u0627\u06cc\u0633\u0647 \u0645\u062f\u0644\u200c\u0647\u0627", size=14, weight=ft.FontWeight.BOLD, color=TEXT),
            ft.DataTable(
                columns=[
                    ft.DataColumn(ft.Text("\u0645\u062f\u0644", size=11, color=MUTED)),
                    ft.DataColumn(ft.Text("\u0628\u06cc\u0634\u06cc\u0646\u0647", size=11, color=MUTED)),
                    ft.DataColumn(ft.Text("\u06a9\u0645\u06cc\u0646\u0647", size=11, color=MUTED)),
                    ft.DataColumn(ft.Text("\u0628\u0627\u0631\u0634", size=11, color=MUTED)),
                    ft.DataColumn(ft.Text("\u0633\u06cc\u06af\u0646\u0627\u0644", size=11, color=MUTED)),
                ],
                rows=rows,
            ),
        ], spacing=8)
    )


def _key_points_card(snapshot: dict | None) -> ft.Control:
    bullets = []
    if snapshot:
        stats = []
        for model_id, data in _model_rows(snapshot):
            maxes = [float(v) for v in data.get("temperature_max", [])]
            rains = [float(v) for v in data.get("precipitation_sum", [])]
            stats.append((MODEL_LABELS.get(model_id, model_id), max(maxes) if maxes else None, round(sum(rains), 1) if rains else 0.0))
        hot = max([s for s in stats if s[1] is not None], key=lambda s: s[1], default=None)
        wet = max(stats, key=lambda s: s[2], default=None)
        if hot:
            bullets.append(f"\u06af\u0631\u0645\u200c\u062a\u0631\u06cc\u0646 \u0628\u06cc\u0634\u06cc\u0646\u0647: {hot[0]} \u0628\u0627 {format_temperature(hot[1])}")
        if wet and wet[2] >= 2:
            bullets.append(f"\u0628\u06cc\u0634\u062a\u0631\u06cc\u0646 \u0628\u0627\u0631\u0634: {wet[0]} \u0628\u0627 {format_precipitation(wet[2])}")
        elif wet:
            bullets.append("\u0647\u06cc\u0686 \u0645\u062f\u0644\u06cc \u0628\u0627\u0631\u0634 \u0642\u0627\u0628\u0644 \u062a\u0648\u062c\u0647\u06cc \u0646\u0645\u06cc\u200c\u0628\u06cc\u0646\u062f.")
        highs = [s[1] for s in stats if s[1] is not None]
        if len(highs) >= 2:
            spread = round(max(highs) - min(highs), 1)
            verdict = "\u062a\u0648\u0627\u0641\u0642 \u062e\u0648\u0628 \u0645\u062f\u0644\u200c\u0647\u0627" if spread < 3 else "\u0627\u062e\u062a\u0644\u0627\u0641 \u0642\u0627\u0628\u0644 \u062a\u0648\u062c\u0647 \u0645\u062f\u0644\u200c\u0647\u0627"
            bullets.append(f"\u0627\u062e\u062a\u0644\u0627\u0641 \u0628\u06cc\u0634\u06cc\u0646\u0647 \u0645\u062f\u0644\u200c\u0647\u0627: {spread} \u062f\u0631\u062c\u0647 (\u200c{verdict})")
    if not bullets:
        bullets = ["\u062a\u062d\u0644\u06cc\u0644 \u0622\u0645\u0627\u062f\u0647 \u0627\u0633\u062a؛ \u062c\u0632\u0626\u06cc\u0627\u062a \u0631\u0627 \u062f\u0631 \u0633\u062a\u0648\u0646 \u0631\u0627\u0633\u062a \u0628\u062e\u0648\u0627\u0646\u06cc\u062f."]
    return surface(
        ft.Column([
            ft.Text("\U0001f4cc \u0646\u06a9\u0627\u062a \u06a9\u0644\u06cc\u062f\u06cc \u062a\u062d\u0644\u06cc\u0644", size=14, weight=ft.FontWeight.BOLD, color=GOLD),
            *[ft.Text(f"\u2022 {b}", size=13, color=TEXT) for b in bullets[:3]],
        ], spacing=8)
    )


class WeeklyAnalysisView(ft.Container):
    def __init__(self):
        super().__init__(expand=True, padding=0)
        initial_text = Strings.ANALYSIS_NOT_CONFIGURED if not config.GEMINI_API_KEY else Strings.LOADING
        self.content = ft.Column(
            controls=[ft.Text(initial_text, color=MUTED)],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            alignment=ft.MainAxisAlignment.CENTER,
        )

    def _render_analysis(self, analysis: str, cache: dict | None, from_cache: bool = False):
        generated_at = format_generated_at(cache)
        status = Strings.ANALYSIS_CACHED if from_cache else "\u062a\u062d\u0644\u06cc\u0644 \u062c\u062f\u06cc\u062f \u062a\u0648\u0644\u06cc\u062f \u0634\u062f."
        if generated_at:
            status = f"{status} | {Strings.LAST_ANALYSIS}: {generated_at}"
        snapshot = (cache or {}).get("forecast_snapshot")

        header = surface(
            ft.Row(
                controls=[
                    ft.Column(
                        controls=[
                            ft.Text(Strings.WEEKLY_ANALYSIS, size=20, weight=ft.FontWeight.BOLD, color=TEXT),
                            ft.Text(Strings.MULTI_MODEL_ANALYSIS, size=15, color=GOLD),
                            ft.Text(load_settings()["location_name"], size=13, color=MUTED),
                        ],
                        spacing=3,
                        expand=True,
                    ),
                    action_button(
                        Strings.REFRESH_ANALYSIS,
                        on_click=lambda event: asyncio.create_task(self.load_analysis_data(force=True)),
                        bgcolor=GOLD,
                        color=DARK,
                        icon=ft.Icons.REFRESH,
                    ),
                ],
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=12,
        )

        # Right (wide): analysis text, model sections inside expanders.
        intro, sections = _split_sections(analysis)
        right_controls = []
        if intro:
            right_controls.append(ft.Text(intro, size=15, selectable=True, color=TEXT))
        if sections:
            for title, body in sections:
                right_controls.append(
                    ft.ExpansionTile(
                        title=ft.Text(title, size=15, weight=ft.FontWeight.BOLD, color=GOLD),
                        controls=[ft.Text(body, size=15, selectable=True, color=TEXT)],
                        initially_expanded=False,
                    )
                )
        else:
            if not intro:
                right_controls.append(ft.Text(analysis, size=15, selectable=True, color=TEXT))
        # Responsive: narrow screens stack vertically so analysis gets full width.
        # Wide screens keep side-by-side with analysis 2x wider than side panels.
        try:
            _w = getattr(getattr(self, "page", None), "width", None)
            _narrow = isinstance(_w, (int, float)) and _w < 700
        except Exception:
            _narrow = False
        # On mobile the page width is often None at first render -> default to stacked
        # if we cannot prove we are wide.
        try:
            import os

            _platform_hint = os.getenv("FLET_PLATFORM", "")
            if _w is None:
                _narrow = True
        except Exception:
            pass

        analysis_card = surface(
            ft.Column(right_controls, spacing=10),
            padding=16,
        )
        side_cards = [_comparison_table(snapshot), _key_points_card(snapshot)]

        if _narrow:
            self.content = ft.Column(
                controls=[
                    header,
                    ft.Text(status, size=11, color=MUTED),
                    analysis_card,
                    *side_cards,
                ],
                spacing=10,
                expand=True,
                scroll=ft.ScrollMode.AUTO,
            )
        else:
            right_col = ft.Column([analysis_card], expand=2, spacing=10, scroll=ft.ScrollMode.AUTO)
            left_col = ft.Column(
                side_cards,
                expand=1, spacing=12, scroll=ft.ScrollMode.AUTO,
            )
            self.content = ft.Column(
                controls=[
                    header,
                    ft.Text(status, size=11, color=MUTED),
                    ft.Row([right_col, left_col], spacing=12, expand=True, vertical_alignment=ft.CrossAxisAlignment.START),
                ],
                spacing=10,
                expand=True,
            )

    async def load_analysis_data(self, force: bool = False):
        if not config.GEMINI_API_KEY:
            return
        try:
            cache = load_cache()
            multimodel_data, synoptic_context = await asyncio.gather(
                asyncio.to_thread(get_multi_model_forecast),
                asyncio.to_thread(get_synoptic_context),
            )
            if cache and not should_refresh(cache, multimodel_data, force=force):
                self._render_analysis(cache["analysis"], cache, from_cache=True)
            else:
                multimodel_data["synoptic_context"] = synoptic_context
                analysis = await asyncio.to_thread(get_multimodel_analysis, multimodel_data)
                failed_messages = {
                    Strings.ERROR_FETCHING_ANALYSIS,
                    Strings.ANALYSIS_QUOTA_EXCEEDED,
                    Strings.ANALYSIS_NOT_CONFIGURED,
                }
                if analysis in failed_messages:
                    self._render_analysis(analysis, cache, from_cache=False)
                else:
                    save_cache(analysis, cache_snapshot(multimodel_data))
                    self._render_analysis(analysis, load_cache(), from_cache=False)
        except Exception:
            self.content = ft.Container(
                alignment=ft.Alignment.CENTER,
                content=ft.Text(Strings.ERROR_FETCHING_ANALYSIS, color="#B42318", text_align=ft.TextAlign.CENTER),
            )
        if self.page:
            self.page.update()
