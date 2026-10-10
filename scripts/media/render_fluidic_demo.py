"""Render the checked two-channel IR as an exploded schematic GIF (Pillow only).

Not a CAD/CFD renderer. Layer gaps and tubing are schematic; channel tracer
speeds are derived from Q/A and the declared main-channel lengths.
"""

from __future__ import annotations

import argparse
import math
from pathlib import Path
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from forma_core.fluidics.calculations import (  # noqa: E402
    average_velocity_mm_s, pressure_drop_kpa, residence_time_s,
)
from forma_core.fluidics.validation import validate_fluidic_system  # noqa: E402
from forma_core.workspaces.projects.models import HardwareIntermediateRepresentation  # noqa: E402

W, H, SCALE = 1320, 800, 2
BG, WHITE, MUTED = "#0c1626", "#eaf1fb", "#9caec5"
BLUE, CORAL, GOLD = "#51c9f5", "#ff7c8d", "#e4c478"


def font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    try:
        return ImageFont.truetype(name, size * SCALE)
    except OSError:
        return ImageFont.load_default(size=size * SCALE)


def project(x: float, y: float, z: float) -> tuple[float, float]:
    return 293 + x + 0.4 * y, 490 + 0.20 * x - 0.40 * y - z


def render(project_ir: HardwareIntermediateRepresentation, output: Path) -> None:
    system = project_ir.fluidic_system
    if system is None or validate_fluidic_system(system):
        raise ValueError("The GIF requires a validated fluidic system.")
    channels = {c.id: c for c in system.channels}
    if "vascular_channel" not in channels or "epithelial_channel" not in channels:
        raise ValueError("This example renderer requires the two named organ-chip channels.")
    # This renderer deliberately supports only the exact two-circuit example.
    # Refuse dosing/other networks rather than silently omitting their components.
    expected = {f"{c}_{s}" for c in ("vascular", "epithelial") for s in ("supply", "feed", "channel")}
    if set(channels) != expected or len(system.membranes) != 1:
        raise ValueError("Use the two-channel fixture; additional branches need a different visual layout.")
    fluids = {f.id: f for f in system.fluids}
    metrics = {
        name: (average_velocity_mm_s(channels[name + "_channel"]),
               residence_time_s(channels[name + "_channel"]),
               pressure_drop_kpa(channels[name + "_channel"], fluids[channels[name + "_channel"].fluid]))
        for name in ("vascular", "epithelial")
    }
    frames: list[Image.Image] = []
    palette = None
    for frame in range(144):
        t = frame / 12
        im = Image.new("RGB", (W * SCALE, H * SCALE), BG)
        d = ImageDraw.Draw(im)

        def xy(points):
            return [(round(x * SCALE), round(y * SCALE)) for x, y in points]

        def poly(points, fill, outline=None):
            d.polygon(xy(points), fill=fill)
            if outline:
                d.line(xy([*points, points[0]]), fill=outline, width=SCALE)

        def line(points, fill, width=1):
            d.line(xy(points), fill=fill, width=round(width * SCALE), joint="curve")

        def circle(x, y, radius, fill, outline=None):
            d.ellipse(tuple(round(v * SCALE) for v in (x-radius, y-radius, x+radius, y+radius)), fill=fill, outline=outline, width=SCALE)

        def box(x0, y0, x1, y1, fill, outline=None, radius=10):
            d.rounded_rectangle(tuple(round(v * SCALE) for v in (x0, y0, x1, y1)), radius=radius*SCALE, fill=fill, outline=outline, width=SCALE)

        def text(x, y, value, size=16, fill=WHITE, bold=False):
            d.text((x*SCALE, y*SCALE), value, font=font(size, bold), fill=fill)

        def slab(z, top, side, edge):
            a, b, c, e = [project(x, y, z) for x, y in [(0, 0), (470, 0), (470, 180), (0, 180)]]
            down_a, down_b, down_c = [project(x, y, z-12) for x, y in [(0, 0), (470, 0), (470, 180)]]
            poly([a, b, down_b, down_a], side, edge)
            poly([b, c, down_c, down_b], side, edge)
            poly([a, b, c, e], top, edge)
            for x in (20, 450):
                for y in (20, 160):
                    px, py = project(x, y, z)
                    circle(px, py, 4, BG, edge)

        def bottle(x, y, color):
            box(x-22, y, x+22, y+55, "#18283c", "#64809e", 8)
            box(x-20, y+28, x+20, y+52, color, radius=6)
            box(x-10, y-14, x+10, y+5, "#23394c", "#64809e", 3)
            line([(x-11, y-14), (x+11, y-14)], WHITE, 2)
            for offset in (17, 26, 35):
                line([(x+10, y+offset), (x+20, y+offset)], "#a8bac9")

        # Subtle coordinate grid and dashboard framing.
        for x in range(40, 920, 28):
            for y in range(170, 613, 28):
                circle(x, y, 0.7, "#25344a")
        text(42, 25, "MAPPED ASSEMBLY  /  FORMA", 14, GOLD, True)
        text(40, 56, "Organ-on-a-chip", 41, WHITE, True)
        text(42, 112, "Two perfused channels · separate waste paths · porous membrane", 18, MUTED)
        box(687, 156, 910, 188, "#183529", radius=16)
        circle(704, 172, 4, "#6de4b3")
        text(717, 161, "VALIDATED EXAMPLE IR", 12, "#91edc4", True)

        # Lower vascular layer, then the interface, then upper epithelial layer.
        for name, z, color, top, edge in [
            ("vascular", 48, CORAL, "#263349", "#52647c"),
            ("membrane", 123, GOLD, "#4b4335", "#bba46d"),
            ("epithelial", 198, BLUE, "#23384b", "#6f90a5"),
        ]:
            slab(z, top, "#1b293b" if name != "membrane" else "#34342f", edge)
            if name == "membrane":
                for x in range(42, 439, 16):
                    for y in range(26, 160, 17):
                        px, py = project(x, y, z+1)
                        circle(px, py, 1.7, "#a28f62")
                continue
            main = channels[name + "_channel"]
            start, end = project(72, 90, z+3), project(440, 90, z+3)
            inlet, outlet = project(0, 90, z+3), project(470, 90, z+3)
            chamber = project(55, 90, z+3)
            line([inlet, chamber, start, end, outlet], "#102335", 24)
            line([inlet, chamber, start, end, outlet], color, 13)
            line([inlet, chamber, start, end, outlet], "#345368" if name == "epithelial" else "#6b4057", 7)
            circle(*chamber, 16, color)
            circle(*chamber, 10, "#183049")
            # Uniform tracer spacing, true mean Q/A speed in the main channel.
            spacing = main.length_mm / 8
            for n in range(8):
                fraction = ((n * spacing + metrics[name][0] * t) % main.length_mm) / main.length_mm
                x, y = (start[k] + (end[k]-start[k]) * fraction for k in (0, 1))
                circle(x, y, 4.5, color)
                circle(x-0.7, y-0.7, 1.8, "#fff8f4")
            # Cell-contact surfaces are indicative, not biological simulation.
            for x in range(100, 425, 23):
                px, py = project(x, 116, z+1)
                circle(px, py, 5, "#487187" if name == "epithelial" else "#744554", color)
            # Inlet/pump and collection vial for this circuit.
            pump_y = 240 if name == "epithelial" else 407
            line([(100, pump_y), (203, pump_y), (253, pump_y), inlet], "#34485f", 13)
            line([(100, pump_y), (203, pump_y), (253, pump_y), inlet], color, 5)
            box(112, pump_y-17, 201, pump_y+17, "#244055", "#829bb2", 5)
            box(115, pump_y-13, 168, pump_y+13, "#3e7384" if name == "epithelial" else "#6a475b", radius=3)
            line([(169, pump_y-17), (169, pump_y+17)], WHITE, 3)
            line([(84, pump_y), (112, pump_y)], "#cad6e1", 4)
            line([(84, pump_y-13), (84, pump_y+13)], "#cad6e1", 3)
            for tick in range(121, 199, 10):
                line([(tick, pump_y-16), (tick, pump_y-9)], WHITE)
            text(48, pump_y-66, name.upper(), 14, color, True)
            text(48, pump_y-45, f"Inlet + pump  /  {main.target_flow_rate_ul_min:g} µL/min", 13, MUTED)
            waste_y = 368 if name == "epithelial" else 535
            line([outlet, (861, outlet[1]), (877, waste_y-14)], "#35485e", 10)
            line([outlet, (861, outlet[1]), (877, waste_y-14)], color, 4)
            bottle(877, waste_y, color)
            text(829, waste_y+59, "Waste", 13, color)

        # Dimension/interface annotation below the exploded chip.
        line([project(240, 0, 123), (550, 579), (397, 579)], GOLD)
        text(313, 587, "Porous PET membrane · 10 µm thick", 14, GOLD)
        text(45, 566, "EXPLODED SCHEMATIC", 12, MUTED, True)
        text(45, 587, "Layer gaps exaggerated", 12, MUTED)

        box(944, 164, 1280, 621, "#142236", "#2b3c55", 18)
        text(968, 186, "FLOW AT A GLANCE", 13, MUTED, True)
        for name, yy, color in [("vascular", 228, CORAL), ("epithelial", 397, BLUE)]:
            channel = channels[name + "_channel"]
            v, residence, pressure = metrics[name]
            text(968, yy, name.title(), 20, color, True)
            text(968, yy+34, f"{channel.target_flow_rate_ul_min:g}", 36, WHITE, True)
            text(1040, yy+52, "µL/min", 16, MUTED)
            text(968, yy+91, f"Mean speed      {v:.2f} mm/s", 14)
            text(968, yy+116, f"Channel transit  {residence:g} s", 14)
            text(968, yy+141, f"Estimated Δp    {pressure*1000:.2f} Pa", 14)
        line([(968, 390), (1255, 390)], "#304158")
        text(968, 585, "Declared water-like demo fluid", 12, MUTED)

        box(43, 653, 1280, 744, "#142236", "#293b51", 14)
        text(65, 668, "NETWORK CHECKS", 12, MUTED, True)
        text(65, 698, "✓ Complete inlet → waste paths", 15, "#90e6be")
        text(470, 698, "✓ Isolated bulk-fluid circuits", 15, "#90e6be")
        text(862, 698, "✓ Flow + pressure constraints", 15, "#90e6be")
        text(44, 762, "Schematic flow preview • not CFD or biological validation • tracer speed uses the validated IR", 12, MUTED)
        text(1160, 762, f"t = {t:04.1f} s", 12, GOLD)

        reduced = im.resize((W, H), Image.Resampling.LANCZOS)
        if palette is None:
            palette = reduced.quantize(colors=192)
        frames.append(reduced.quantize(palette=palette, dither=Image.Dither.NONE))

    output.parent.mkdir(parents=True, exist_ok=True)
    # GIF stores centiseconds: 80/80/90 ms = 12 fps on average.
    frames[0].save(output, save_all=True, append_images=frames[1:], loop=0,
                   duration=[80, 80, 90] * 48, optimize=True, disposal=1)
    print(f"{output}: {len(frames)} frames, 12 s, {W}x{H}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", type=Path, default=ROOT / "examples/organ-on-chip/two-channel.json")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    render(HardwareIntermediateRepresentation.model_validate_json(args.project.read_text(encoding="utf-8")), args.output)


if __name__ == "__main__":
    main()
