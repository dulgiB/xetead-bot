from pathlib import Path

import fitz
from PIL import Image

from bot.field_sheet_image import _RASTER_DPI, _rasterize_and_crop

_PAGE_W = 612
_PAGE_H = 792


def _make_pdf(path: Path, *, with_content: bool) -> None:
    doc = fitz.open()
    page = doc.new_page(width=_PAGE_W, height=_PAGE_H)
    if with_content:
        page.draw_rect(fitz.Rect(100, 100, 300, 200), color=(0, 0, 0), fill=(0, 0, 0))
    doc.save(path)
    doc.close()


def _full_raster_size() -> tuple[int, int]:
    zoom = _RASTER_DPI / 72
    return round(_PAGE_W * zoom), round(_PAGE_H * zoom)


def test_rasterize_and_crop_shrinks_to_content_bbox(tmp_path):
    """내용이 있는 페이지는 흰 여백이 잘려나가 원본 페이지보다 작아야 한다."""
    pdf_path = tmp_path / "in.pdf"
    png_path = tmp_path / "out.png"
    _make_pdf(pdf_path, with_content=True)

    _rasterize_and_crop(pdf_path, png_path)

    assert png_path.exists()
    image = Image.open(png_path)
    full_w, full_h = _full_raster_size()
    assert 0 < image.width < full_w
    assert 0 < image.height < full_h


def test_rasterize_and_crop_keeps_full_page_when_blank(tmp_path):
    """내용이 전혀 없는(완전히 흰) 페이지는 크롭할 bbox가 없으므로 원본
    페이지 크기 그대로 유지되어야 한다."""
    pdf_path = tmp_path / "blank.pdf"
    png_path = tmp_path / "blank.png"
    _make_pdf(pdf_path, with_content=False)

    _rasterize_and_crop(pdf_path, png_path)

    image = Image.open(png_path)
    full_w, full_h = _full_raster_size()
    assert image.size == (full_w, full_h)
