from __future__ import annotations

from collections import defaultdict
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from app.plugins.base import Plugin, PluginContext, PluginError, PluginResult
from app.plugins.registry import register_plugin

MAX_CATEGORIES = 200


class ChartArgs(BaseModel):
    ref_id: str = Field(..., description="ref_id of a previous 'query' plugin result to chart.")
    chart_type: Literal["line", "bar", "scatter"] = Field(..., description="Chart type to produce.")
    x_field: str = Field(..., description="Column from the query result to use as the x-axis / category.")
    y_field: str = Field(..., description="Column to aggregate for the y-axis.")
    series_field: str | None = Field(
        default=None, description="Optional column to split into multiple series (e.g. one line per server)."
    )
    agg: Literal["sum", "avg", "count", "max", "min"] = Field(
        default="sum", description="How to aggregate y_field per x (and per series, if given)."
    )
    sort_by_value: bool = Field(
        default=False, description="Sort categories by aggregated value descending instead of by x. Use for top-N bar charts."
    )
    top_n: int | None = Field(default=None, ge=1, le=MAX_CATEGORIES, description="Keep only the top N categories after sorting.")
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
        "top-N comparisons (bar), and distributions/relationships (scatter). Aggregates y_field grouped by "
        "x_field (and optionally series_field) using the given aggregation. Returns a chart spec the frontend "
        "renders — pin it to the dashboard to keep it live."
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

        chart_spec = {
            "chart_type": args.chart_type,
            "title": args.title or f"{args.agg}({args.y_field}) by {args.x_field}",
            "x_label": args.x_field,
            "y_label": f"{args.agg}({args.y_field})",
            "categories": [str(c) for c in categories],
            "series": series_out,
            "source_ref_id": args.ref_id,
        }

        ref = ctx.store.put(kind="chart_spec", full_data=chart_spec, preview=chart_spec, row_count=len(categories))
        display_text = (
            f"Built a {args.chart_type} chart '{chart_spec['title']}' with {len(categories)} "
            f"categor{'y' if len(categories)==1 else 'ies'} and {len(series_out)} series."
        )
        return PluginResult(ref=ref, display_text=display_text)
