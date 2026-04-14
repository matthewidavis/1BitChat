"""Generate retro manual-style images for the README."""
from PIL import Image, ImageDraw, ImageFont, ImageFilter
import math, os
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "docs"
OUT.mkdir(exist_ok=True)

# Paper / beige manual palette
PAPER = (238, 228, 200)
PAPER_DARK = (215, 200, 168)
INK = (38, 32, 24)
INK_SOFT = (70, 60, 45)
RED = (168, 42, 36)
SEAL_BLUE = (30, 60, 120)


def load_font(candidates, size):
    for c in candidates:
        try:
            return ImageFont.truetype(c, size)
        except Exception:
            continue
    return ImageFont.load_default()


SERIF = ["times.ttf", "timesbd.ttf", "georgia.ttf", "georgiab.ttf"]
SERIF_BOLD = ["timesbd.ttf", "georgiab.ttf", "times.ttf"]
MONO = ["consola.ttf", "cour.ttf"]
SANS_BOLD = ["arialbd.ttf", "arial.ttf"]


def add_paper_noise(img, strength=6):
    """Subtle speckle + fiber texture to mimic old paper."""
    import random
    random.seed(1)
    px = img.load()
    w, h = img.size
    for _ in range(w * h // 40):
        x = random.randint(0, w - 1)
        y = random.randint(0, h - 1)
        r, g, b = px[x, y][:3]
        d = random.randint(-strength, strength)
        px[x, y] = (max(0, min(255, r + d)),
                    max(0, min(255, g + d)),
                    max(0, min(255, b + d)))
    return img


def cover():
    W, H = 1100, 380
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)

    # Outer decorative double border
    margin = 18
    d.rectangle([margin, margin, W - margin, H - margin], outline=INK, width=3)
    d.rectangle([margin + 6, margin + 6, W - margin - 6, H - margin - 6], outline=INK, width=1)

    # Top ornamental rule
    d.line([margin + 24, 60, W - margin - 24, 60], fill=INK, width=1)
    d.line([margin + 24, 64, W - margin - 24, 64], fill=INK, width=1)

    # Small decorative diamonds at the corners
    for cx, cy in [(margin + 36, 62), (W - margin - 36, 62)]:
        d.polygon([(cx, cy - 6), (cx + 6, cy), (cx, cy + 6), (cx - 6, cy)], fill=INK)

    # Title
    title = load_font(SERIF_BOLD, 64)
    subtitle = load_font(SERIF, 24)
    sub_small = load_font(SERIF, 18)
    stamp_font = load_font(SANS_BOLD, 16)

    def centered(text, y, font, fill):
        bbox = d.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        d.text(((W - tw) // 2 - bbox[0], y), text, fill=fill, font=font)

    centered("1 B I T C H A T", 95, title, INK)
    centered("O P E R A T O R ' S   I N S T R U C T I O N   M A N U A L", 180, subtitle, INK_SOFT)

    # Horizontal rules below subtitle
    d.line([W // 2 - 220, 225, W // 2 + 220, 225], fill=INK, width=1)
    centered("MODEL 1BC-2.4B-4T  ·  REVISION 0.2  ·  MMXXVI", 240, sub_small, INK_SOFT)
    d.line([W // 2 - 220, 268, W // 2 + 220, 268], fill=INK, width=1)

    # Faux "CLASSIFIED / INSPECTED" red stamp bottom-right
    stamp_w, stamp_h = 230, 58
    sx, sy = W - margin - 24 - stamp_w, H - margin - 24 - stamp_h
    stamp = Image.new("RGBA", (stamp_w, stamp_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(stamp)
    sd.rectangle([0, 0, stamp_w - 1, stamp_h - 1], outline=RED, width=3)
    sd.rectangle([4, 4, stamp_w - 5, stamp_h - 5], outline=RED, width=1)
    sd.text((18, 8), "APPROVED FOR", fill=RED, font=stamp_font)
    sd.text((18, 30), "FIELD OPERATION", fill=RED, font=stamp_font)
    stamp = stamp.rotate(-6, resample=Image.BICUBIC, expand=True)
    img.paste(stamp, (sx, sy), stamp)

    # Form number bottom-left
    d.text((margin + 24, H - margin - 36), "FORM 1BC-001  (REV. 04/2026)", fill=INK_SOFT, font=sub_small)

    img = add_paper_noise(img, strength=5)
    img.save(OUT / "manual-cover.png", optimize=True)
    print("wrote", OUT / "manual-cover.png")


def inspection_seal():
    S = 260
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    cx, cy, r = S // 2, S // 2, S // 2 - 14
    d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=SEAL_BLUE, width=5)
    d.ellipse([cx - r + 10, cy - r + 10, cx + r - 10, cy + r - 10], outline=SEAL_BLUE, width=1)

    # Curved text around top and bottom - approximated with rotated glyphs
    def arc_text(text, radius, start_angle_deg, font, clockwise=True):
        # render each char rotated so it sits tangent to the circle
        from PIL import Image as _I
        theta = math.radians(start_angle_deg)
        step = math.radians(12 if clockwise else -12)
        for i, ch in enumerate(text):
            ang = theta + i * step
            bbox = d.textbbox((0, 0), ch, font=font)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            char_img = _I.new("RGBA", (w + 8, h + 8), (0, 0, 0, 0))
            cd = ImageDraw.Draw(char_img)
            cd.text((4 - bbox[0], 4 - bbox[1]), ch, fill=SEAL_BLUE, font=font)
            # rotate so char base is tangent to circle
            rot = math.degrees(ang) + (90 if clockwise else -90)
            rotated = char_img.rotate(-rot, resample=Image.BICUBIC, expand=True)
            px = cx + int(radius * math.cos(ang)) - rotated.width // 2
            py = cy + int(radius * math.sin(ang)) - rotated.height // 2
            img.paste(rotated, (px, py), rotated)

    seal_font = load_font(SANS_BOLD, 18)
    top_text = "ENGINEERING  DIVISION"
    arc_text(top_text, r - 22, 180 + 54, seal_font, clockwise=True)

    # Center star
    def star(cx, cy, r_outer, r_inner, points=5):
        pts = []
        for i in range(points * 2):
            rr = r_outer if i % 2 == 0 else r_inner
            ang = -math.pi / 2 + i * math.pi / points
            pts.append((cx + rr * math.cos(ang), cy + rr * math.sin(ang)))
        d.polygon(pts, fill=SEAL_BLUE)

    star(cx, cy - 18, 28, 12)

    # "INSPECTED" / "No. 0001"
    f_big = load_font(SANS_BOLD, 20)
    f_small = load_font(SANS_BOLD, 14)

    for text, y, f in [("INSPECTED", cy + 22, f_big), ("No. 0001", cy + 50, f_small)]:
        bbox = d.textbbox((0, 0), text, font=f)
        tw = bbox[2] - bbox[0]
        d.text((cx - tw // 2 - bbox[0], y), text, fill=SEAL_BLUE, font=f)

    img.save(OUT / "inspection-seal.png", optimize=True)
    print("wrote", OUT / "inspection-seal.png")


def bit_diagram():
    W, H = 900, 320
    img = Image.new("RGB", (W, H), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle([10, 10, W - 10, H - 10], outline=INK, width=2)

    title_f = load_font(SERIF_BOLD, 22)
    label_f = load_font(SERIF, 16)
    mono_f = load_font(MONO, 15)
    caption_f = load_font(SERIF, 13)

    d.text((28, 24), "FIGURE 1.1  —  WEIGHT REPRESENTATIONS, COMPARED", fill=INK, font=title_f)
    d.line([28, 58, W - 28, 58], fill=INK, width=1)

    # Left: 16-bit standard
    col1_x = 60
    d.text((col1_x, 78), "STANDARD LLM (16-bit float)", fill=INK, font=label_f)
    d.text((col1_x, 102), "one weight = 16 bits", fill=INK_SOFT, font=caption_f)
    for i in range(16):
        x = col1_x + i * 14
        d.rectangle([x, 130, x + 10, 160], outline=INK, width=1)
    d.text((col1_x, 170), "65,536 possible values", fill=INK_SOFT, font=caption_f)

    # Middle: naive 1-bit
    col2_x = 360
    d.text((col2_x, 78), "NAIVE 1-BIT", fill=INK, font=label_f)
    d.text((col2_x, 102), "one weight = 1 bit", fill=INK_SOFT, font=caption_f)
    d.rectangle([col2_x, 130, col2_x + 28, 160], fill=INK)
    d.text((col2_x + 40, 135), "{ 0, 1 }", fill=INK, font=mono_f)
    d.text((col2_x, 170), "Insufficient for language!", fill=RED, font=caption_f)

    # Right: BitNet b1.58
    col3_x = 620
    d.text((col3_x, 78), "BITNET b1.58 (ternary)", fill=INK, font=label_f)
    d.text((col3_x, 102), "one weight ≈ 1.58 bits", fill=INK_SOFT, font=caption_f)
    for i, lbl in enumerate(["-1", " 0", "+1"]):
        x = col3_x + i * 48
        d.rectangle([x, 130, x + 36, 160], outline=INK, width=1)
        d.text((x + 10, 136), lbl, fill=INK, font=mono_f)
    d.text((col3_x, 170), "log₂(3) ≈ 1.58 bits per weight", fill=INK_SOFT, font=caption_f)

    # Bottom note
    note = ("NOTE: BitNet stores each parameter as one of three states "
            "(negative one, zero, positive one). The \"1-bit\" branding"
            " is a friendly simplification; in truth, three states require"
            " approximately 1.58 bits, per Shannon.")
    # wrap manually
    import textwrap
    lines = textwrap.wrap(note, width=110)
    y = 215
    for ln in lines:
        d.text((28, y), ln, fill=INK, font=caption_f)
        y += 18

    img = add_paper_noise(img, strength=4)
    img.save(OUT / "fig-1-1-weights.png", optimize=True)
    print("wrote", OUT / "fig-1-1-weights.png")


if __name__ == "__main__":
    cover()
    inspection_seal()
    bit_diagram()
