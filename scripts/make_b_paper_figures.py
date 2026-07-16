#!/usr/bin/env python3
"""Generate vector paper figures directly from the frozen Experiment B analysis JSON."""

from __future__ import annotations

import json
import math
from pathlib import Path

from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
ANALYSIS = ROOT / "reports" / "same_call_confirmation_b_analysis.json"
OUT = ROOT / "output" / "pdf"

NAVY = HexColor("#173A5E")
BLUE = HexColor("#2F6B9A")
ORANGE = HexColor("#D66A2C")
LIGHT_BLUE = HexColor("#DCEAF4")
GRAY = HexColor("#727A82")
LIGHT_GRAY = HexColor("#E6E8EA")
GRID = HexColor("#D7DBDF")


LABELS = {
    "bootstrap_only": "Bootstrap",
    "exact_even_G4": "Exact-G4",
    "exact_even_G5": "Exact-G5",
    "random_G5": "Random-G5",
    "js_cap_G5": "JS-G5",
    "context_no_reactivation_B25": "CARR-NoRecall",
    "context_memory_B25": "CARR",
    "exact_even_B25": "Exact-B25",
}


def _fmt_p(p: float) -> str:
    if p < 1e-3:
        return f"{p:.0e}"
    return f"{p:.3f}"


def _text(c: canvas.Canvas, x: float, y: float, value: str, size: float = 8,
          color: Color = black, font: str = "Helvetica", anchor: str = "start") -> None:
    c.setFont(font, size)
    c.setFillColor(color)
    if anchor == "middle":
        c.drawCentredString(x, y, value)
    elif anchor == "end":
        c.drawRightString(x, y, value)
    else:
        c.drawString(x, y, value)


def _line(c: canvas.Canvas, x1: float, y1: float, x2: float, y2: float,
          color: Color = black, width: float = 1.0, dash: tuple[int, ...] | None = None) -> None:
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.setDash(dash or [])
    c.line(x1, y1, x2, y2)
    c.setDash([])


def make_pareto(data: dict) -> Path:
    path = OUT / "b_pareto_frontier.pdf"
    # Keep the plot readable at full ACM text width without spending half a
    # page on vertical whitespace.  The original 4.45-inch canvas was useful
    # for standalone inspection but unnecessarily tall in the paper.
    width, height = 7.2 * inch, 3.35 * inch
    c = canvas.Canvas(str(path), pagesize=(width, height), pageCompression=1, invariant=1)
    c.setTitle("Experiment B sample-mean throughput-generator-call frontier")

    left, right, bottom, top = 58, 20, 42, 22
    pw, ph = width - left - right, height - bottom - top
    xmin, xmax = 0.8, 30.0
    ymin, ymax = 4330.0, 4620.0

    def sx(x: float) -> float:
        return left + (math.log(x) - math.log(xmin)) / (math.log(xmax) - math.log(xmin)) * pw

    def sy(y: float) -> float:
        return bottom + (y - ymin) / (ymax - ymin) * ph

    _text(c, left, height - 14, "Sample-mean throughput-generator-call frontier", 11, NAVY, "Helvetica-Bold")
    _text(c, width - right, height - 14, "Better: up and left", 8, GRAY, anchor="end")

    for tick in [4350, 4400, 4450, 4500, 4550, 4600]:
        y = sy(tick)
        _line(c, left, y, width - right, y, GRID, 0.6)
        _text(c, left - 7, y - 3, f"{tick:,}", 7.5, GRAY, anchor="end")
    for tick in [1, 2, 5, 10, 20, 30]:
        x = sx(tick)
        _line(c, x, bottom, x, height - top, GRID, 0.45)
        _text(c, x, bottom - 14, str(tick), 7.5, GRAY, anchor="middle")

    _line(c, left, bottom, width - right, bottom, NAVY, 0.9)
    _line(c, left, bottom, left, height - top, NAVY, 0.9)
    _text(c, left + pw / 2, 12, "Mean generator calls (log scale; lower is better)", 8.5, NAVY, anchor="middle")
    c.saveState()
    c.translate(14, bottom + ph / 2)
    c.rotate(90)
    _text(c, 0, 0, "Mean completed tasks (higher is better)", 8.5, NAVY, anchor="middle")
    c.restoreState()

    points = data["pareto"]["points"]
    frontier = set(data["pareto"]["frontier_methods"])
    ordered_frontier = sorted(frontier, key=lambda m: points[m]["mean_total_generator_calls"])
    for a, b in zip(ordered_frontier, ordered_frontier[1:]):
        _line(
            c,
            sx(points[a]["mean_total_generator_calls"]), sy(points[a]["mean_tasks"]),
            sx(points[b]["mean_total_generator_calls"]), sy(points[b]["mean_tasks"]),
            BLUE, 1.25, (4, 3),
        )

    offsets = {
        "bootstrap_only": (10, 7, "start"),
        "exact_even_G4": (-9, -15, "end"),
        "exact_even_G5": (7, -2, "start"),
        "random_G5": (7, -2, "start"),
        "js_cap_G5": (7, -2, "start"),
        "context_no_reactivation_B25": (9, 3, "start"),
        "context_memory_B25": (-10, 9, "end"),
        "exact_even_B25": (-7, 7, "end"),
    }

    # Dominated methods first, then frontier points, then the focal point.
    draw_order = [m for m in points if m not in frontier]
    draw_order += [m for m in ordered_frontier if m != "context_memory_B25"]
    draw_order.append("context_memory_B25")
    for method in draw_order:
        p = points[method]
        x, y = sx(p["mean_total_generator_calls"]), sy(p["mean_tasks"])
        if method == "context_memory_B25":
            c.setFillColor(white)
            c.setStrokeColor(ORANGE)
            c.setLineWidth(2.0)
            c.circle(x, y, 6.0, fill=1, stroke=1)
            c.setFillColor(ORANGE)
            c.circle(x, y, 3.0, fill=1, stroke=0)
            label_color, label_font = ORANGE, "Helvetica-Bold"
        elif method in frontier:
            c.setFillColor(BLUE)
            c.setStrokeColor(white)
            c.setLineWidth(0.8)
            c.circle(x, y, 4.2, fill=1, stroke=1)
            label_color, label_font = NAVY, "Helvetica-Bold"
        else:
            c.setFillColor(white)
            c.setStrokeColor(GRAY)
            c.setLineWidth(1.2)
            c.circle(x, y, 3.8, fill=1, stroke=1)
            label_color, label_font = GRAY, "Helvetica"
        dx, dy, anchor = offsets[method]
        _text(c, x + dx, y + dy, LABELS[method], 7.7, label_color, label_font, anchor)

    _text(c, width - right, bottom + 3, "Dashed line: empirical sample-mean frontier", 7, GRAY, anchor="end")
    c.showPage()
    c.save()
    return path


def make_forest(data: dict) -> Path:
    path = OUT / "b_superiority_forest.pdf"
    # Six contrasts remain comfortably separated at this height while the
    # figure no longer crowds the references onto a later page.
    width, height = 7.2 * inch, 3.20 * inch
    c = canvas.Canvas(str(path), pagesize=(width, height), pageCompression=1, invariant=1)
    c.setTitle("Experiment B root-level superiority contrasts")

    left, right, bottom, top = 104, 80, 42, 32
    pw, ph = width - left - right, height - bottom - top
    xmin, xmax = -1.0, 5.5

    methods = [
        "bootstrap_only",
        "exact_even_G4",
        "exact_even_G5",
        "random_G5",
        "js_cap_G5",
        "context_no_reactivation_B25",
    ]
    comps = data["superiority_comparisons"]

    def sx(x: float) -> float:
        return left + (x - xmin) / (xmax - xmin) * pw

    row_gap = ph / len(methods)
    ys = [height - top - row_gap * (i + 0.5) for i in range(len(methods))]

    _text(c, left, height - 16, "CARR throughput effect versus frozen comparators", 11, NAVY, "Helvetica-Bold")
    _text(c, width - right + 8, height - 16, "Holm p", 7.5, GRAY, "Helvetica-Bold")

    for i, y in enumerate(ys):
        if i % 2 == 0:
            c.setFillColor(Color(0.965, 0.97, 0.975))
            c.rect(8, y - row_gap / 2, width - 16, row_gap, fill=1, stroke=0)

    for tick in [-1, 0, 1, 2, 3, 4, 5]:
        x = sx(tick)
        _line(c, x, bottom, x, height - top, NAVY if tick == 0 else GRID, 1.0 if tick == 0 else 0.55)
        _text(c, x, bottom - 14, f"{tick:+d}", 7.5, GRAY, anchor="middle")

    for method, y in zip(methods, ys):
        comp = comps[method]
        mean = 100.0 * comp["mean_relative_effect"]
        lo, hi = [100.0 * value for value in comp["cluster_bootstrap"]["mean_relative_effect_ci"]]
        p_holm = comp["exact_sign_flip"]["p_greater_holm"]
        significant = p_holm < 0.05

        _text(c, left - 9, y - 3, LABELS[method], 8, NAVY if significant else GRAY,
              "Helvetica-Bold" if significant else "Helvetica", anchor="end")
        _line(c, sx(lo), y, sx(hi), y, NAVY if significant else GRAY, 1.6)
        _line(c, sx(lo), y - 3, sx(lo), y + 3, NAVY if significant else GRAY, 1.0)
        _line(c, sx(hi), y - 3, sx(hi), y + 3, NAVY if significant else GRAY, 1.0)
        c.setFillColor(BLUE if significant else white)
        c.setStrokeColor(BLUE if significant else GRAY)
        c.setLineWidth(1.1)
        c.circle(sx(mean), y, 3.8, fill=1, stroke=1)
        _text(c, width - right + 8, y - 3, _fmt_p(p_holm), 7.5,
              NAVY if significant else GRAY)

    _text(c, left + pw / 2, 12, "Root-level relative throughput effect (%)", 8.5, NAVY, anchor="middle")
    _text(c, left, height - 29, "Positive values favor CARR; bars are 95% whole-root bootstrap intervals.", 7.5, GRAY)
    _text(c, width - 10, 12, "Filled: Holm-adjusted p < .05", 7, GRAY, anchor="end")
    c.showPage()
    c.save()
    return path


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    with ANALYSIS.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    for artifact in (make_pareto(data), make_forest(data)):
        print(artifact.relative_to(ROOT))


if __name__ == "__main__":
    main()
