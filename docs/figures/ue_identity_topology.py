#!/usr/bin/env python3
"""Render the report topology with fixed layout and font-independent exports."""

import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

os.environ.setdefault("MPLCONFIGDIR", tempfile.mkdtemp(prefix="falcon-topology-mpl-", dir="/tmp"))
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyArrowPatch, FancyBboxPatch
from matplotlib.path import Path as MplPath

ROOT = Path(__file__).resolve().parent
WIDTH, HEIGHT = 1550, 620
GROUP_FILL, GROUP_BORDER = "#fff9e6", "#b6ac8f"
INK, BORDER = "#243247", "#627187"

# SVG glyph outlines avoid OS font substitution and browser text measurement.
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "svg.fonttype": "path",
    "svg.hashsalt": "falcon-ue-identity-topology",
})

NODES = {
    "ue1": (40, 400, 120, 90, "UE1", ["10.45.0.2"]),
    "du1": (190, 390, 230, 110, "DU1", ["F1: 54 -> 55", "DU ID + KPM"]),
    "ue2": (40, 250, 120, 90, "UE2", ["10.46.0.2"]),
    "du2": (190, 240, 230, 110, "DU2", ["F1: 34 -> 35", "DU ID + KPM"]),
    "cu": (190, 85, 230, 120, "CU-CP", ["NGAP + GUAMI", "F1 identities", "owned snapshot"]),
    "ric": (520, 390, 240, 110, "FlexRIC", ["CU + DU1 + DU2", "KPM transport"]),
    "amf": (520, 210, 240, 95, "AMF", ["NGAP IDs + SUPI", "gNB + state"]),
    "smf": (520, 80, 240, 110, "SMF", ["SUPI + session", "DNN + UE IP"]),
    "radio": (840, 380, 190, 130, "RAN cache", ["DU/F1 context", "NGAP + GUAMI"]),
    "core": (840, 170, 190, 130, "Core cache", ["join by SUPI", "PDU + DNN + IP"]),
    "join": (1080, 270, 160, 140, "UE binding", ["scoped IDs", "unique", "fresh"]),
    "output": (1310, 275, 220, 130, "Saved output", ["bindings.txt", "rows.ndjson", "IDs + IP + KPM"]),
}


def main():
    fig = plt.figure(figsize=(15.5, 6.2), dpi=120, facecolor="white")
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set(xlim=(0, WIDTH), ylim=(0, HEIGHT))
    ax.axis("off")
    bounded_text = []

    def rectangle(x, y, width, height, fill, border, radius=8, zorder=1):
        ax.add_patch(FancyBboxPatch(
            (x, y), width, height,
            boxstyle=f"round,pad=0,rounding_size={radius}",
            facecolor=fill, edgecolor=border, linewidth=1.2, zorder=zorder,
        ))

    def group(x, y, width, height, title):
        rectangle(x, y, width, height, GROUP_FILL, GROUP_BORDER, radius=10)
        text = ax.text(x + width / 2, y + height - 25, title, ha="center",
                       va="center", fontsize=19, fontweight="bold", color=INK, zorder=4)
        bounded_text.append((text, (x, y, width, height), 12))

    def edge(points, context=False, both=False):
        path = MplPath(points, [MplPath.MOVETO] + [MplPath.LINETO] * (len(points) - 1))
        ax.add_patch(FancyArrowPatch(
            path=path, arrowstyle="<->" if both else "->", mutation_scale=14,
            linewidth=1.35, color=BORDER if context else INK,
            linestyle=(0, (4, 3)) if context else "-", zorder=2,
        ))

    def label(text, x, y, size=11.5):
        ax.text(x, y, text, ha="center", va="center", fontsize=size, color=INK,
                bbox=dict(facecolor="white", edgecolor="none", pad=1.5), zorder=6)

    group(20, 55, 430, 530, "RAN")
    group(500, 55, 280, 300, "5G Core")
    group(820, 135, 440, 450, "Standalone xApp")

    for name, (x, y, width, height, title, body) in NODES.items():
        rectangle(x, y, width, height, "white", BORDER, zorder=3)
        lines = [title, *body]
        start = y + height / 2 + (len(lines) - 1) * 12.5
        for index, line in enumerate(lines):
            text = ax.text(
                x + width / 2, start - index * 25, line, ha="center", va="center",
                fontsize=16.5 if index == 0 else 14.5,
                fontweight="bold" if index == 0 else "normal", color=INK, zorder=4,
            )
            bounded_text.append((text, (x, y, width, height), 9))

    edge([(160, 445), (190, 445)])
    edge([(160, 295), (190, 295)])
    label("NR", 175, 466, size=10.5)
    label("NR", 175, 316, size=10.5)

    # F1/NGAP establish CU contexts; solid paths carry xApp input data.
    edge([(305, 390), (305, 370), (435, 370), (435, 170), (420, 170)],
         context=True, both=True)
    edge([(305, 240), (305, 205)], context=True, both=True)
    label("F1-C", 387, 370, size=10.5)
    label("F1-C", 273, 222, size=10.5)
    edge([(305, 85), (305, 25), (490, 25), (490, 257.5), (520, 257.5)],
         context=True, both=True)
    label("N2 / NGAP", 396, 25)

    # Shared E2 transport, with CU and both DU identities retained by the RIC.
    ax.plot([470, 470], [145, 445], color=INK, linewidth=1.35, zorder=2)
    for y in (445, 295, 145):
        edge([(420, y), (470, y)])
    edge([(470, 445), (520, 445)])
    label("E2 / KPM", 473, 477)
    edge([(760, 445), (840, 445)])
    label("3 subs", 800, 465)

    edge([(760, 257.5), (800, 257.5), (800, 260), (840, 260)])
    edge([(760, 135), (800, 135), (800, 210), (840, 210)])
    label("HTTP", 800, 280)
    edge([(1030, 445), (1055, 445), (1055, 370), (1080, 370)])
    edge([(1030, 235), (1055, 235), (1055, 315), (1080, 315)])
    edge([(1240, 340), (1310, 340)])
    label("save", 1275, 360)

    ax.text(870, 75, "Solid: E2 / API data", fontsize=11.5, color=INK, va="center")
    ax.text(870, 45, "Dashed: F1 / NGAP context", fontsize=11.5, color=BORDER, va="center")

    # Fail generation if any label exceeds its node, including export padding.
    fig.canvas.draw()
    renderer = fig.canvas.get_renderer()
    for text, (x, y, width, height), padding in bounded_text:
        bounds = text.get_window_extent(renderer)
        lower = ax.transData.transform((x + padding, y + padding))
        upper = ax.transData.transform((x + width - padding, y + height - padding))
        assert bounds.x0 >= lower[0] and bounds.x1 <= upper[0], text.get_text()
        assert bounds.y0 >= lower[1] and bounds.y1 <= upper[1], text.get_text()

    png, svg = ROOT / "ue_identity_topology.png", ROOT / "ue_identity_topology.svg"
    fig.savefig(png, dpi=180, facecolor="white")
    fig.savefig(svg, facecolor="white", metadata={
        "Date": None,
        "Title": "Dual-UE xApp identity and IP binding",
        "Description": "RAN and 5G Core supply E2 and read-only API inputs to xApp. "
                       "Identity matching runs inside xApp; saved TXT/NDJSON output is outside.",
    })
    plt.close(fig)
    parsed = ET.parse(svg)
    tags = {element.tag.rsplit("}", 1)[-1] for element in parsed.iter()}
    assert "text" not in tags and "foreignObject" not in tags
    print("Generated landscape PNG (2790 x 1116) and self-contained SVG with outlined text.")
    print("All node/group labels fit inside their boxes; no HTML labels or live font dependency.")


if __name__ == "__main__":
    main()
