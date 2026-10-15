"""The photo pages (frontend redesign, Unit 4b: docs/redesign.md §5 and §6). The two Canva
photos may be used only unchanged (Canva's written permission, 15 October 2026), so every
treatment is CSS over the original file. No JS runtime needed: files are read as text/bytes.

- Each served photo is the original: its size and SHA-256 are the ones CREDITS.md records.
- No stylesheet puts a CSS filter or backdrop-filter on anything, or uses
  background-attachment: fixed (it breaks scrolling on phones).
- Text over a photo keeps WCAG AA at the worst point, a black pixel: the 60% veil behind the
  desktop page for ink (page titles and ink links), the 90% panel under the title for ink and
  ink-2.
- Only the assigned pages carry a photo, each its section's: img1 on Dashboard, Skin Profile,
  Routine, Catalog and product detail; img2 on Settings, Account, Privacy, About and Contact.
  Every assigned /app page has the band under its nav.
"""

import hashlib
import re
from html.parser import HTMLParser

import pytest

from app.tests.test_frontend_contract import FRONTEND, page

PHOTOS = {
    "1": ("static/media/backdrop-1.png", 3_249_050,
          "64534ddbdf43507a0341c4d571ccba3385cc5abe7288015d3398497764bd0945"),
    "2": ("static/media/backdrop-2.png", 2_805_909,
          "00e4936b4a9c382e53076891771ba89a0038836738aa478c20b826bccbd6ed98"),
}
ASSIGNED = {
    "pages/app/index.html": "1",
    "pages/app/profile/index.html": "1",
    "pages/app/routine/index.html": "1",
    "pages/app/catalog/index.html": "1",
    "pages/app/catalog/detail/index.html": "1",
    "pages/app/settings/index.html": "2",
    "pages/app/settings/account/index.html": "2",
    "pages/app/settings/privacy/index.html": "2",
    "pages/about/index.html": "2",
    "pages/contact/index.html": "2",
}
INK, INK2 = "#191a1c", "#55575c"


# --------------------------------------------------------------------------------------
# The files: the originals, unchanged
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("key", sorted(PHOTOS))
def test_each_photo_is_the_original_file_unchanged(key):
    path, size, sha256 = PHOTOS[key]
    data = (FRONTEND / path).read_bytes()
    assert len(data) == size and hashlib.sha256(data).hexdigest() == sha256, path
    assert sha256 in page("static/CREDITS.md"), f"CREDITS.md doesn't record {path}"
    assert f'body[data-photo="{key}"] {{\n  --photo: url("/{path}");' in page("static/css/main.css")


def test_no_filter_on_anything_and_no_fixed_background():
    for css in sorted(FRONTEND.rglob("*.css")):
        text = css.read_text(encoding="utf-8")
        rel = css.relative_to(FRONTEND)
        assert not re.search(r"(?<![\w-])(?:backdrop-)?filter\s*:", text), rel
        assert "background-attachment" not in text, rel


# --------------------------------------------------------------------------------------
# Contrast at the worst point
# --------------------------------------------------------------------------------------


def _luminance(rgb) -> float:
    def lin(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _hex(value: str) -> tuple[int, int, int]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def _share(css: str, name: str) -> int:
    return int(re.search(rf"{name}: color-mix\(in srgb, var\(--ground\) (\d+)%, transparent\);", css).group(1))


def _ratio_over_black(share: int, ground, text: str) -> float:
    worst = _luminance(tuple(share / 100 * c for c in ground))
    return (worst + 0.05) / (_luminance(_hex(text)) + 0.05)


def test_text_over_the_photos_keeps_aa_at_a_black_pixel():
    main = page("static/css/main.css")
    ground = _hex(re.search(r"--ground: (#[0-9a-f]{6});", main).group(1))
    veil, panel = _share(main, "--photo-veil"), _share(main, "--photo-panel")
    # The desktop veil: page titles and ink links sit on it (nothing in ink-2).
    assert _ratio_over_black(veil, ground, INK) >= 4.5, veil
    # The panel under the title (the band on phones; About's and Contact's band too).
    for text in (INK, INK2):
        assert _ratio_over_black(panel, ground, text) >= 4.5, (panel, text)
    band_panel = re.search(r"\.band__panel \{.*?\}", page("pages/public.css"), re.DOTALL).group(0)
    assert f"color-mix(in srgb, var(--ground) {panel}%, transparent)" in band_panel
    # The veil and the photo are one layer, and only from 1024px; below that the band.
    desktop = main[main.index("body[data-photo]::before"):]
    assert "linear-gradient(var(--photo-veil), var(--photo-veil))" in desktop.split("}")[0]
    assert re.search(r"@media \(min-width: 1024px\) \{\s*body\[data-photo\] \{\s*isolation: isolate;", main)


# --------------------------------------------------------------------------------------
# Which pages carry which photo
# --------------------------------------------------------------------------------------


class _Body(HTMLParser):
    def __init__(self):
        super().__init__()
        self.photo: str | None = None
        self.band_after_nav = False
        self._after_nav = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "body":
            self.photo = attrs.get("data-photo")
        elif tag == "nav" and attrs.get("id") == "app-nav":
            self._after_nav = True
        elif self._after_nav:
            self.band_after_nav = tag == "div" and attrs.get("class") == "photo-band"
            self._after_nav = False


def test_only_the_assigned_pages_carry_a_photo_each_its_sections():
    for path in sorted((FRONTEND / "pages").rglob("index.html")):
        rel = str(path.relative_to(FRONTEND)).replace("\\", "/")
        parser = _Body()
        parser.feed(path.read_text(encoding="utf-8"))
        assert parser.photo == ASSIGNED.get(rel), rel
        if rel in ASSIGNED and rel.startswith("pages/app/"):
            assert parser.band_after_nav, f"{rel}: no photo band right after the nav"
