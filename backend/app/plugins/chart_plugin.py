from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.plugins.base import Plugin, PluginContext, PluginError, PluginResult
from app.plugins.registry import register_plugin

MAX_CATEGORIES = 200
MAX_SCATTER_POINTS = 2000  # scatter plots raw pairs, not aggregates — cap so a 5000-row result can't produce an unbounded payload


class ChartArgs(BaseModel):
    ref_id: str = Field(..., description="ref_id of a previous 'query' plugin result to chart.")
    chart_type: Literal["line", "bar", "scatter"] = Field(..., description="Chart type to produce.")
    x_field: str = Field(..., description="Column from the query result to use as the x-axis / category.")
    y_field: str = Field(..., description="Column to aggregate for the y-axis (line/bar) or plot directly (scatter).")
    series_field: str | None = Field(
        default=None, description="Optional column to split into multiple series (e.g. one line per server)."
    )
    agg: Literal["sum", "avg", "count", "max", "min"] = Field(
        default="sum",
        description="How to aggregate y_field per x (and per series, if given). Ignored for chart_type='scatter' — "
        "scatter plots every row as its own (x, y) point, since aggregating would defeat the point of looking "
        "for a relationship between two variables.",
    )
    sort_by_value: bool = Field(
        default=False, description="Sort categories by aggregated value descending instead of by x. Use for top-N bar charts. Ignored for scatter."
    )
    top_n: int | None = Field(default=None, ge=1, le=MAX_CATEGORIES, description="Keep only the top N categories after sorting. Ignored for scatter.")
    title: str = Field(default="", description="Chart title.")

    @field_validator("y_field")
    @classmethod
    def _y_not_star(cls, v):
        if v.strip() in ("*", ""):
            raise ValueError("y_field must be a real column name, not '*' or empty.")
        return v


@register_plugin
class ChartPlugin(Plugin):
    name = "chart"
    description = (
        "Turn a previous query's result (given its ref_id) into a chart. Handles time series (line), "
        "top-N comparisons (bar) — both aggregate y_field grouped by x_field using the given agg — and "
        "relationships/distributions (scatter), which plots every row as its own raw (x_field, y_field) point "
        "with no aggregation, since aggregating would hide the relationship you're trying to see. Returns a "
        "chart spec the frontend renders — pin it to the dashboard to keep it live."
    )
    input_model = ChartArgs
    consumes = "result_set"
    produces = "chart_spec"

    async def execute(self, args: ChartArgs, ctx: PluginContext) -> PluginResult:
        source_ref = ctx.store.get(args.ref_id)
        if source_ref.kind != "result_set":
            raise PluginError(
                "WRONG_INPUT_KIND",
                f"chart expects a 'result_set' ref, got '{source_ref.kind}'.",
                retryable=True,
            )
        rows: list[dict] = source_ref.full_data or []
        if not rows:
            raise PluginError("EMPTY_RESULT", "The referenced query returned no rows to chart.", retryable=False)

        for col, label in ((args.x_field, "x_field"), (args.y_field, "y_field")):
            if col not in rows[0]:
                raise PluginError(
                    "UNKNOWN_COLUMN",
                    f"{label} '{col}' is not a column in the referenced result. Available columns: {list(rows[0].keys())}",
                    retryable=True,
                )
        if args.series_field and args.series_field not in rows[0]:
            raise PluginError(
                "UNKNOWN_COLUMN",
                f"series_field '{args.series_field}' is not a column in the referenced result. "
                f"Available columns: {list(rows[0].keys())}",
                retryable=True,
            )

        if args.chart_type == "scatter":
            chart_spec = self._build_scatter(args, rows)
            point_count = sum(len(s["points"]) for s in chart_spec["series"])
            ref = ctx.store.put(kind="chart_spec", full_data=chart_spec, preview=chart_spec, row_count=point_count)
            display_text = (
                f"Built a scatter chart '{chart_spec['title']}' with {point_count} point(s) "
                f"across {len(chart_spec['series'])} series."
            )
            return PluginResult(ref=ref, display_text=display_text)

        chart_spec = self._build_aggregated(args, rows)
        ref = ctx.store.put(
            kind="chart_spec", full_data=chart_spec, preview=chart_spec, row_count=len(chart_spec["categories"])
        )
        display_text = (
            f"Built a {args.chart_type} chart '{chart_spec['title']}' with {len(chart_spec['categories'])} "
            f"categor{'y' if len(chart_spec['categories']) == 1 else 'ies'} and {len(chart_spec['series'])} series."
        )
        return PluginResult(ref=ref, display_text=display_text)

    @staticmethod
    def _build_scatter(args: ChartArgs, rows: list[dict]) -> dict:
        """No aggregation, no bucketing by x — every row becomes one (x, y)
        point. Grouping by series_field is still honoured (e.g. one colour
        per server), but within a series the points are exactly the rows,
        not a sum/avg of them."""
        by_series: dict[str, list[dict]] = defaultdict(list)
        skipped_non_numeric = 0
        for row in rows:
            series = str(row.get(args.series_field)) if args.series_field else "value"
            try:
                x = float(row.get(args.x_field))
                y = float(row.get(args.y_field))
            except (TypeError, ValueError):
                skipped_non_numeric += 1
                continue
            by_series[series].append({"x": x, "y": y})

        total = sum(len(pts) for pts in by_series.values())
        if total > MAX_SCATTER_POINTS:
            # Evenly downsample each series rather than truncating one
            # series to zero — keeps the shape of the relationship visible
            # instead of just chopping off whatever sorted last. ceil()
            # (not round()) guarantees the result is at or under the cap,
            # not slightly over it.
            import math
            for series in by_series:
                pts = by_series[series]
                target = max(1, round(len(pts) * MAX_SCATTER_POINTS / total))
                step = max(1, math.ceil(len(pts) / target))
                by_series[series] = pts[::step]

        series_out = [{"name": name, "points": pts} for name, pts in sorted(by_series.items())]
        title = args.title or f"{args.y_field} vs {args.x_field}"
        return {
            "chart_type": "scatter",
            "title": title,
            "x_label": args.x_field,
            "y_label": args.y_field,
            "categories": [],
            "series": series_out,
            "source_ref_id": args.ref_id,
            "note": f"{skipped_non_numeric} row(s) skipped (non-numeric)" if skipped_non_numeric else None,
        }

    @staticmethod
    def _build_aggregated(args: ChartArgs, rows: list[dict]) -> dict:
        grouped: dict[tuple, list[float]] = defaultdict(list)
        for row in rows:
            x = row.get(args.x_field)
            series = row.get(args.series_field) if args.series_field else "value"
            y_raw = row.get(args.y_field)
            try:
                y = float(y_raw) if y_raw is not None else 0.0
            except (TypeError, ValueError):
                y = 1.0 if args.agg == "count" else 0.0
            grouped[(x, series)].append(y)

        def aggregate(values: list[float]) -> float:
            if args.agg == "sum":
                return sum(values)
            if args.agg == "avg":
                return sum(values) / len(values)
            if args.agg == "count":
                return float(len(values))
            if args.agg == "max":
                return max(values)
            return min(values)

        aggregated: dict[tuple, float] = {k: aggregate(v) for k, v in grouped.items()}

        categories = sorted({x for (x, _series) in aggregated.keys()}, key=lambda v: (v is None, v))
        series_names = sorted({s for (_x, s) in aggregated.keys()})

        if args.sort_by_value:
            totals = {x: sum(aggregated.get((x, s), 0.0) for s in series_names) for x in categories}
            categories = sorted(categories, key=lambda x: totals[x], reverse=True)
        if args.top_n:
            categories = categories[: args.top_n]
        if len(categories) > MAX_CATEGORIES:
            categories = categories[:MAX_CATEGORIES]

        series_out = [
            {"name": s, "values": [aggregated.get((x, s), 0.0) for x in categories]}
            for s in series_names
        ]

        return {
            "chart_type": args.chart_type,
            "title": args.title or f"{args.agg}({args.y_field}) by {args.x_field}",
            "x_label": args.x_field,
            "y_label": f"{args.agg}({args.y_field})",
            "categories": [str(c) for c in categories],
            "series": series_out,
            "source_ref_id": args.ref_id,
        }