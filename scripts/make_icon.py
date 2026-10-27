"""Génère l'icône de l'app : squircle indigo, onde en dégradé aurora (menthe → iris → corail), point REC corail.

    python scripts/make_icon.py
→ src/noter/ui/assets/AppIcon.png (1024), AppIcon.icns, icon.png (512, README)
"""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

OUT = Path(__file__).resolve().parents[1] / "src" / "noter" / "ui" / "assets"
ROOT = Path(__file__).resolve().parents[1]

INDIGO_TOP = (46, 38, 98)
INDIGO_BOT = (18, 16, 38)
AURORA = [(61, 219, 168), (140, 128, 255), (255, 122, 110)]  # menthe, iris, corail (thème sombre)
REC = (255, 107, 94)


def aurora(frac: float) -> tuple[int, int, int]:
    """Couleur du dégradé aurora à la position `frac` (0..1)."""
    seg = min(1, int(frac * 2))
    k = frac * 2 - seg
    a, b = AURORA[seg], AURORA[seg + 1]
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))


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
        for x in range(inner):
            t = (0.65 * y + 0.35 * x) / (inner - 1)  # dégradé légèrement diagonal
            c = tuple(int(INDIGO_TOP[i] * (1 - t) + INDIGO_BOT[i] * t) for i in range(3))
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
        d.rounded_rectangle([x, cy - bh / 2, x + bw, cy + bh / 2], radius=bw / 2, fill=aurora(i / (bars - 1)))
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
