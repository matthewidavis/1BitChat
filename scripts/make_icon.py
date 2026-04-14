"""Generate 1BitChat.ico. Run once; the output is checked in alongside the exe."""
from PIL import Image, ImageDraw, ImageFont
import random

SIZE = 256
ACCENT = (108, 99, 255)
ACCENT_DIM = (78, 70, 200)
BG = (15, 15, 15)
WHITE = (232, 232, 232)


def make_icon(size=SIZE):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)

    # Rounded square background
    r = size // 6
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=r, fill=BG, outline=ACCENT, width=max(2, size // 64))

    # Ternary weight grid: small squares with -1 / 0 / +1 vibe in accent color
    random.seed(7)
    pad = size // 10
    cells = 8
    cell = (size - pad * 2) // cells
    for cy in range(cells):
        for cx in range(cells):
            v = random.choice([-1, 0, 0, 1])
            if v == 0:
                continue
            x0 = pad + cx * cell + cell // 8
            y0 = pad + cy * cell + cell // 8
            x1 = x0 + cell * 3 // 4
            y1 = y0 + cell * 3 // 4
            color = ACCENT if v == 1 else ACCENT_DIM
            d.rectangle([x0, y0, x1, y1], fill=color)

    # Center "1b" mark on a dark pill
    label = "1b"
    try:
        font = ImageFont.truetype("segoeuib.ttf", size // 2)
    except Exception:
        font = ImageFont.load_default()
    bbox = d.textbbox((0, 0), label, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    px, py = size // 8, size // 12
    pill_w, pill_h = tw + px * 2, th + py * 2
    pill_x = (size - pill_w) // 2
    pill_y = (size - pill_h) // 2
    d.rounded_rectangle(
        [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
        radius=pill_h // 2, fill=BG, outline=ACCENT, width=max(2, size // 64),
    )
    d.text(
        ((size - tw) // 2 - bbox[0], (size - th) // 2 - bbox[1]),
        label, fill=WHITE, font=font,
    )
    return img


from pathlib import Path
base = make_icon(256)
sizes = [(s, s) for s in (16, 24, 32, 48, 64, 128, 256)]
out = Path(__file__).resolve().parent.parent / "1BitChat.ico"
base.save(out, sizes=sizes)
print("wrote", out)
