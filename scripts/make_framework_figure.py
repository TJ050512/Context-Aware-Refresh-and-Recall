#!/usr/bin/env python3
"""Generate the CARR system/architecture figure as a vector PDF.

The figure contrasts the frozen backbone (identical for every policy) with the
CARR control plane (the only component that varies), and shows the three
control actions (hold / reactivate / generate) and where each one touches the
backbone.  It uses the same palette as ``make_b_paper_figures.py`` so the paper
figures are visually consistent.
"""

from __future__ import annotations

import math
from pathlib import Path

from reportlab.lib.colors import Color, HexColor, black, white
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output" / "pdf"

NAVY = HexColor("#173A5E")
BLUE = HexColor("#2F6B9A")
ORANGE = HexColor("#D66A2C")
LIGHT_BLUE = HexColor("#DCEAF4")
ORANGE_BG = HexColor("#FBEADF")
GRAY = HexColor("#727A82")
LIGHT_GRAY = HexColor("#EEF0F2")
BACKBONE_BG = HexColor("#F4F6F8")


def _text(c, x, y, value, size=8, color=black, font="Helvetica", anchor="start"):
    c.setFont(font, size)
    c.setFillColor(color)
    if anchor == "middle":
        c.drawCentredString(x, y, value)
    elif anchor == "end":
        c.drawRightString(x, y, value)
    else:
        c.drawString(x, y, value)


def _box(c, x, y, w, h, lines, fill=white, stroke=NAVY, lw=1.0, radius=6):
    c.setFillColor(fill)
    c.setStrokeColor(stroke)
    c.setLineWidth(lw)
    c.roundRect(x, y, w, h, radius, fill=1, stroke=1)
    n = len(lines)
    lh = 11.0
    cx = x + w / 2
    center_y = y + h / 2
    first = center_y + (n - 1) * lh / 2 - lh * 0.32
    for i, (txt, size, color, font) in enumerate(lines):
        _text(c, cx, first - i * lh, txt, size, color, font, "middle")
    return {
        "cx": cx, "cy": center_y,
        "left": x, "right": x + w, "top": y + h, "bottom": y,
        "w": w, "h": h,
    }


def _seg(c, x1, y1, x2, y2, color=NAVY, width=1.1, dash=None):
    c.setStrokeColor(color)
    c.setLineWidth(width)
    c.setDash(dash or [])
    c.line(x1, y1, x2, y2)
    c.setDash([])


def _head(c, x, y, ang, color=NAVY, size=6.5, width=1.1):
    c.setStrokeColor(color)
    c.setLineWidth(width)
    for da in (math.radians(148), math.radians(-148)):
        c.line(x, y, x + size * math.cos(ang + da), y + size * math.sin(ang + da))


def _arrow(c, x1, y1, x2, y2, color=NAVY, width=1.1, dash=None, size=6.5):
    _seg(c, x1, y1, x2, y2, color, width, dash)
    _head(c, x2, y2, math.atan2(y2 - y1, x2 - x1), color, size, width)


def _elbow(c, pts, color=NAVY, width=1.1, dash=None, size=6.5):
    for (x1, y1), (x2, y2) in zip(pts, pts[1:]):
        _seg(c, x1, y1, x2, y2, color, width, dash)
    (xa, ya), (xb, yb) = pts[-2], pts[-1]
    _head(c, xb, yb, math.atan2(yb - ya, xb - xa), color, size, width)


def build() -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / "b_framework.pdf"
    width, height = 7.3 * inch, 3.55 * inch
    c = canvas.Canvas(str(path), pagesize=(width, height), pageCompression=1, invariant=1)
    c.setTitle("CARR system overview")

    # ---- Region backdrops -------------------------------------------------
    top_y, top_h = height - 128, 104
    bot_y, bot_h = 18, 108

    c.setFillColor(BACKBONE_BG)
    c.setStrokeColor(HexColor("#C8D0D8"))
    c.setLineWidth(0.8)
    c.roundRect(8, top_y, width - 16, top_h, 8, fill=1, stroke=1)
    _text(c, 16, top_y + top_h - 12, "Frozen backbone  \u2014  identical for every policy",
          8.5, GRAY, "Helvetica-Bold")

    c.setFillColor(ORANGE_BG)
    c.setStrokeColor(HexColor("#E7C3AA"))
    c.setLineWidth(0.8)
    c.roundRect(8, bot_y, width - 16, bot_h, 8, fill=1, stroke=1)
    _text(c, 16, bot_y + 8, "CARR control plane  \u2014  the only component that varies across policies",
          8.5, ORANGE, "Helvetica-Bold")

    # ---- Backbone boxes ---------------------------------------------------
    by, bh = top_y + 30, 40
    sim = _box(c, 16, by, 92, bh, [
        ("Simulator", 8.5, NAVY, "Helvetica-Bold"),
        ("n agents on grid G", 7.3, GRAY, "Helvetica"),
        ("task tapes T_i", 7.3, GRAY, "Helvetica"),
    ], fill=white)
    gen = _box(c, 124, by, 92, bh, [
        ("Frozen CNN", 8.5, NAVY, "Helvetica-Bold"),
        ("generator F\u03b8", 8.5, NAVY, "Helvetica-Bold"),
    ], fill=LIGHT_BLUE)
    inst = _box(c, 232, by, 104, bh, [
        ("Mask + normalize", 8.5, NAVY, "Helvetica-Bold"),
        ("install version v_k", 7.3, GRAY, "Helvetica"),
    ], fill=white)
    plan = _box(c, 352, by, 92, bh, [
        ("GPIBT planner", 8.5, NAVY, "Helvetica-Bold"),
        ("delayed adoption", 7.3, GRAY, "Helvetica"),
    ], fill=white)

    _arrow(c, sim["right"], sim["cy"], gen["left"], gen["cy"], NAVY, 1.2)
    _text(c, (sim["right"] + gen["left"]) / 2, sim["cy"] + 5, "o\u2264t_k", 7.0, GRAY, "Helvetica", "middle")
    _arrow(c, gen["right"], gen["cy"], inst["left"], inst["cy"], NAVY, 1.2)
    _text(c, (gen["right"] + inst["left"]) / 2, gen["cy"] + 5, "w_k", 7.0, GRAY, "Helvetica", "middle")
    _arrow(c, inst["right"], inst["cy"], plan["left"], plan["cy"], NAVY, 1.2)
    _text(c, (inst["right"] + plan["left"]) / 2, inst["cy"] + 5, "guidance", 7.0, GRAY, "Helvetica", "middle")

    # Throughput output from the planner.
    _arrow(c, plan["right"], plan["cy"], plan["right"] + 42, plan["cy"], NAVY, 1.2)
    _text(c, plan["right"] + 30, plan["cy"] + 7, "throughput", 6.6, GRAY, "Helvetica", "middle")
    _text(c, plan["right"] + 46, plan["cy"] - 3, "C_\u03c0", 8.5, NAVY, "Helvetica-Bold", "start")

    # Closed-loop return: planner routes drive the simulator's next step.
    loop_y = by - 15
    _elbow(c, [
        (plan["cx"], plan["bottom"]),
        (plan["cx"], loop_y),
        (sim["cx"], loop_y),
        (sim["cx"], sim["bottom"]),
    ], BLUE, 1.0, dash=(3, 2))
    _text(c, (sim["cx"] + plan["cx"]) / 2, loop_y - 8,
          "agents step \u2192 new causal observation", 7.0, BLUE, "Helvetica", "middle")

    # ---- Control-plane boxes ---------------------------------------------
    cy0, ch = bot_y + 30, 46
    sig = _box(c, 20, cy0, 128, ch, [
        ("Causal signals", 8.5, NAVY, "Helvetica-Bold"),
        ("change z_k, context c_k,", 7.2, GRAY, "Helvetica"),
        ("guidance age, maturity m_k", 7.2, GRAY, "Helvetica"),
    ], fill=white)
    ctrl = _box(c, 182, cy0 - 4, 170, ch + 8, [
        ("CARR controller", 9.2, ORANGE, "Helvetica-Bold"),
        ("a_k \u2208 {hold, reactivate(j), generate}", 7.4, NAVY, "Helvetica"),
        ("event/percentile guards", 7.2, GRAY, "Helvetica"),
        ("+ B25 call & switch budget", 7.2, GRAY, "Helvetica"),
    ], fill=ORANGE_BG, stroke=ORANGE, lw=1.6)
    cat = _box(c, 386, cy0, 132, ch, [
        ("Context catalog {c_j}", 8.3, NAVY, "Helvetica-Bold"),
        ("gen-time context per graph", 7.2, GRAY, "Helvetica"),
        ("(source for recall)", 7.2, GRAY, "Helvetica"),
    ], fill=white)

    _arrow(c, sig["right"], sig["cy"], ctrl["left"], sig["cy"], NAVY, 1.2)
    # reactivate: controller <-> catalog
    _arrow(c, ctrl["right"], ctrl["cy"], cat["left"], ctrl["cy"], ORANGE, 1.3)
    _text(c, (ctrl["right"] + cat["left"]) / 2, ctrl["cy"] + 5, "reactivate(j)", 6.8, ORANGE, "Helvetica-Bold", "middle")

    # signals are extracted from the frozen backbone state (backbone -> signals)
    _elbow(c, [
        (sim["cx"], sim["bottom"]),
        (sim["cx"], (top_y + bot_y + bot_h) / 2 + 6),
        (sig["cx"], (top_y + bot_y + bot_h) / 2 + 6),
        (sig["cx"], sig["top"]),
    ], GRAY, 1.0, dash=(3, 2))
    _text(c, sig["cx"] + 3, sig["top"] + 6, "causal state", 6.8, GRAY, "Helvetica", "start")

    # generate: controller -> F_theta (fresh call, costs a generator token)
    _elbow(c, [
        (ctrl["cx"] - 40, ctrl["top"]),
        (ctrl["cx"] - 40, (top_y + bot_y + bot_h) / 2),
        (gen["cx"], (top_y + bot_y + bot_h) / 2),
        (gen["cx"], gen["bottom"]),
    ], ORANGE, 1.3)
    _text(c, gen["cx"] - 2, gen["bottom"] - 9, "generate (costs a call)", 6.8, ORANGE, "Helvetica-Bold", "middle")

    # recall install: catalog -> install (reinstall historical graph, no call)
    _elbow(c, [
        (cat["cx"], cat["top"]),
        (cat["cx"], (top_y + bot_y + bot_h) / 2 - 6),
        (inst["cx"] + 24, (top_y + bot_y + bot_h) / 2 - 6),
        (inst["cx"] + 24, inst["bottom"]),
    ], BLUE, 1.2, dash=(3, 2))
    _text(c, cat["cx"], cat["top"] + 6, "reinstall (no call)", 6.8, BLUE, "Helvetica", "middle")

    # hold annotation
    _text(c, ctrl["cx"] + 40, ctrl["top"] + 6, "hold: keep active tensor", 6.8, GRAY, "Helvetica", "middle")

    c.showPage()
    c.save()
    return path


if __name__ == "__main__":
    print(build().relative_to(ROOT))
