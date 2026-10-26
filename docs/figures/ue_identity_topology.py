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
WIDTH, HEIGHT = 1450, 780
GROUP_FILL, GROUP_BORDER = "#fff9e6", "#b6ac8f"
INK, BORDER = "#243247", "#627187"

# SVG glyph outlines avoid OS font substitution and browser text measurement.
plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "svg.fonttype": "path",
    "svg.hashsalt": "falcon-ue-identity-topology",
})

NODES = {
    "ue1": (40, 595, 120, 90, "UE1", ["10.45.0.2"]),
    "du1": (180, 585, 200, 110, "DU1", ["F1: 54 -> 55", "DU ID + KPM"]),
    "ue2": (40, 435, 120, 90, "UE2", ["10.46.0.2"]),
    "du2": (180, 425, 200, 110, "DU2", ["F1: 34 -> 35", "DU ID + KPM"]),
    "cu": (180, 220, 200, 125, "CU-CP", ["NGAP + GUAMI", "F1 identities", "owned snapshot"]),
    "ric": (480, 535, 200, 125, "RIC platform", ["CU + DU1 + DU2", "KPM transport"]),
    "amf": (480, 65, 240, 120, "AMF", ["NGAP IDs + SUPI", "gNB + state"]),
    "smf": (850, 65, 240, 120, "SMF", ["SUPI + session", "DNN + UE IP"]),
    "radio": (750, 490, 190, 125, "RAN cache", ["DU/F1 context", "NGAP + GUAMI"]),
    "core": (750, 350, 190, 110, "Core cache", ["join by SUPI", "PDU + DNN + IP"]),
    "join": (990, 420, 160, 145, "UE binding", ["scoped IDs", "unique", "fresh"]),
    "output": (1240, 427.5, 190, 130, "Output", ["IDs + IP + KPM"]),
}


def main():
    fig = plt.figure(figsize=(WIDTH / 100, HEIGHT / 100), dpi=120, facecolor="white")
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

    def group(x, y, width, height, title, fill=GROUP_FILL):
        rectangle(x, y, width, height, fill, GROUP_BORDER, radius=10)
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

    group(20, 180, 380, 570, "RAN")
    group(460, 25, 730, 220, "5G Core")
    # Logical FlexRIC scope; platform and xApp remain separate processes.
    group(460, 300, 730, 450, "FlexRIC")
    group(730, 330, 440, 360, "xApp", fill="#f1f5fb")

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

    edge([(160, 640), (180, 640)])
    edge([(160, 480), (180, 480)])
    label("NR", 170, 661, size=10.5)
    label("NR", 170, 501, size=10.5)

    # F1/NGAP establish CU contexts; solid paths carry xApp input data.
    edge([(280, 585), (280, 565), (395, 565), (395, 305), (380, 305)],
         context=True, both=True)
    edge([(280, 425), (280, 345)], context=True, both=True)
    label("F1-C", 340, 565, size=10.5)
    label("F1-C", 247, 385, size=10.5)
    edge([(280, 220), (280, 125), (480, 125)],
         context=True, both=True)
    label("N2 / NGAP", 375, 145)

    # Shared E2 transport, with CU and both DU identities retained by the RIC.
    ax.plot([435, 435], [282.5, 640], color=INK, linewidth=1.35, zorder=2)
    for y in (640, 480, 282.5):
        edge([(380, y), (435, y)])
    edge([(435, 510), (580, 510), (580, 535)])
    label("E2 / KPM", 535, 490)
    edge([(680, 597.5), (710, 597.5), (710, 552.5), (750, 552.5)])
    label("3 subs", 715, 625)

    edge([(600, 185), (600, 270), (790, 270), (790, 350)])
    edge([(970, 185), (970, 270), (900, 270), (900, 350)])
    label("HTTP", 845, 310)
    edge([(940, 552.5), (965, 552.5), (965, 530), (990, 530)])
    edge([(940, 405), (965, 405), (965, 465), (990, 465)])
    edge([(1150, 492.5), (1240, 492.5)])
    label("push", 1205, 515)

    ax.text(40, 65, "Solid: E2 / API / report data", fontsize=11.5, color=INK, va="center")
    ax.text(40, 40, "Dashed: F1 / NGAP context", fontsize=11.5, color=BORDER, va="center")

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
        "Title": "Dual-UE FlexRIC xApp identity and IP binding",
        "Description": "RAN and 5G Core supply E2 and read-only API inputs to xApp. "
                       "The logical FlexRIC group contains the RIC platform and xApp. "
                       "The xApp pushes IDs, IP and KPM to the external output.",
    })
    # Matplotlib leaves trailing spaces in multiline SVG path attributes.
    svg.write_text("\n".join(line.rstrip() for line in svg.read_text(encoding="utf-8").splitlines()) + "\n",
                   encoding="utf-8")
    plt.close(fig)
    parsed = ET.parse(svg)
    tags = {element.tag.rsplit("}", 1)[-1] for element in parsed.iter()}
    assert "text" not in tags and "foreignObject" not in tags
    print(f"Generated landscape PNG ({round(WIDTH * 1.8)} x {round(HEIGHT * 1.8)}) "
          "and self-contained SVG with outlined text.")
    print("All node/group labels fit inside their boxes; no HTML labels or live font dependency.")


if __name__ == "__main__":
    main()
