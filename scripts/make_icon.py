"""Draw the brand icon (a coin with a euro sign over a house roof).

Run: python scripts/make_icon.py  (needs Pillow). Writes icon.png (256x256) and
icon@2x.png (512x512) to custom_components/home_finance/brand/.
"""

from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent.parent / "custom_components/home_finance/brand"


def draw(size: int) -> Image.Image:
    s = size / 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # House roof
    d.polygon([(128 * s, 14 * s), (244 * s, 112 * s), (12 * s, 112 * s)], fill="#2E7D5B")
    # Coin
    d.ellipse(
        [40 * s, 70 * s, 216 * s, 246 * s], fill="#F2B632", outline="#B9821A", width=int(10 * s)
    )
    # Euro sign: an open arc plus two bars
    d.arc([82 * s, 106 * s, 182 * s, 210 * s], 40, 320, fill="#5A3E08", width=int(16 * s))
    for y in (138, 166):
        d.rectangle([66 * s, (y - 6) * s, 142 * s, (y + 6) * s], fill="#5A3E08")
    return img


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    draw(256).save(OUT / "icon.png", optimize=True)
    draw(512).save(OUT / "icon@2x.png", optimize=True)
