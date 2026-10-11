"""Génère l'icône de l'app : squircle graphite, onde claire, un point rouge (REC).

    python scripts/make_icon.py
→ src/noter/ui/assets/AppIcon.png (1024), AppIcon.icns, icon.png (512, README)
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "src" / "noter" / "ui" / "assets"
ROOT = Path(__file__).resolve().parents[1]

GRAPHITE_TOP = (44, 46, 50)
GRAPHITE_BOT = (22, 23, 26)
WAVE = (236, 237, 238)
REC = (229, 72, 77)


def squircle_mask(size: int, radius_frac: float = 0.225) -> Image.Image:
    """Masque façon macOS (coins continus) à partir d'une superellipse."""
    n = 5.0
    r = size / 2
    mask = Image.new("L", (size, size), 0)
    px = mask.load()
    k = radius_frac  # inutilisé : la superellipse fixe la forme
    _ = k
    for y in range(size):
        for x in range(size):
            dx = (x + 0.5 - r) / r
            dy = (y + 0.5 - r) / r
            v = abs(dx) ** n + abs(dy) ** n
            px[x, y] = 255 if v <= 1.0 else 0
    return mask.filter(ImageFilter.GaussianBlur(1.2))


def make(size: int = 1024) -> Image.Image:
    # macOS laisse ~10 % de marge transparente autour de l'icône
    pad = int(size * 0.10)
    inner = size - 2 * pad
    body = Image.new("RGBA", (inner, inner), (0, 0, 0, 0))
    grad = Image.new("RGBA", (inner, inner))
    gp = grad.load()
    for y in range(inner):
        t = y / (inner - 1)
        c = tuple(int(GRAPHITE_TOP[i] * (1 - t) + GRAPHITE_BOT[i] * t) for i in range(3))
        for x in range(inner):
            gp[x, y] = (*c, 255)
    body.paste(grad, (0, 0), squircle_mask(inner))

    d = ImageDraw.Draw(body)
    # Onde : 7 barres, hauteurs déterministes, arrondies
    heights = [0.22, 0.46, 0.78, 0.56, 0.92, 0.40, 0.26]
    bars = len(heights)
    bw = inner * 0.064
    gap = inner * 0.052
    total = bars * bw + (bars - 1) * gap
    x0 = (inner - total) / 2
    cy = inner * 0.54
    for i, h in enumerate(heights):
        bh = inner * 0.58 * h
        x = x0 + i * (bw + gap)
        d.rounded_rectangle([x, cy - bh / 2, x + bw, cy + bh / 2], radius=bw / 2, fill=WAVE)
    # Point REC, en haut à droite, avec halo doux
    dot_r = inner * 0.052
    cx, cyd = inner * 0.80, inner * 0.21
    halo = Image.new("RGBA", (inner, inner), (0, 0, 0, 0))
    hd = ImageDraw.Draw(halo)
    hd.ellipse([cx - dot_r * 2.1, cyd - dot_r * 2.1, cx + dot_r * 2.1, cyd + dot_r * 2.1], fill=(*REC, 70))
    halo = halo.filter(ImageFilter.GaussianBlur(inner * 0.02))
    body = Image.alpha_composite(body, halo)
    d = ImageDraw.Draw(body)
    d.ellipse([cx - dot_r, cyd - dot_r, cx + dot_r, cyd + dot_r], fill=REC)

    out = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    # Ombre portée légère
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sm = Image.new("RGBA", (inner, inner), (0, 0, 0, 0))
    sm.paste((0, 0, 0, 90), (0, 0), squircle_mask(inner))
    shadow.paste(sm, (pad, pad + int(size * 0.015)))
    shadow = shadow.filter(ImageFilter.GaussianBlur(size * 0.02))
    out = Image.alpha_composite(out, shadow)
    out.paste(body, (pad, pad), body)
    return out


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    icon = make(1024)
    icon.save(OUT / "AppIcon.png")
    icon.save(OUT / "AppIcon.icns", sizes=[(16, 16), (32, 32), (64, 64), (128, 128), (256, 256), (512, 512), (1024, 1024)])
    icon.resize((512, 512), Image.Resampling.LANCZOS).save(ROOT / "icon.png")
    print("OK", OUT / "AppIcon.png", OUT / "AppIcon.icns")
    _ = math


if __name__ == "__main__":
    main()
