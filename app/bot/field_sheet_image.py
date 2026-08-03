"""공개용 "필드" 시트(`field_sheet_renderer.py`가 갱신하는 그 시트)를 현재
상태 그대로 이미지로 캡처한다.

Google Sheets 공식 API에는 특정 range를 이미지로 export하는 기능이 없어,
비공식 export 엔드포인트(`docs.google.com/spreadsheets/.../export`)를 거쳐
PDF로 받은 뒤 PyMuPDF로 래스터화하고 흰 여백을 잘라낸다:

    PDF export (gspread 클라이언트의 인증 세션 재사용)
      → PNG 래스터화 (PyMuPDF)
      → 흰 여백 자동 크롭 (Pillow)

이 엔드포인트는 공식 문서화된 API가 아니므로 Google이 예고 없이 바꾸거나
막을 수 있다는 점을 감안해야 한다.

결과 이미지는 임시 디렉터리 안의 파일 경로로만 넘겨준다 — 호출자는
`with` 블록 안에서 업로드까지 마쳐야 하며, 블록을 벗어나면 파일이 즉시
삭제된다 (메모리에 이미지 바이트를 오래 들고 있지 않기 위함).
"""

import contextlib
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Iterator

import fitz
import gspread
from PIL import Image, ImageChops

_FIELD_SHEET = "필드"
_EXPORT_RANGE = "A1:M28"
_RASTER_DPI = 200
_CROP_PADDING = 10


def _export_url(spreadsheet_id: str, gid: int, range_a1: str) -> str:
    """`printnotes=false`가 없으면, 셀 메모(버프 설명 등)가 붙은 칸마다
    Google Sheets가 PDF에 각주 참조 번호("[N]")를 자동으로 찍는다. 이
    각주 번호가 가리키는 설명 목록은 내보내는 range 바깥(각주 전용
    페이지)에 나오므로, 좁은 range만 캡처하는 이 흐름에서는 번호만 남고
    무엇을 가리키는지는 잘려서 보이지 않는 채로 이미지에 남는다. 메모
    자체(스프레드시트를 직접 열었을 때 보이는 호버 설명)는 그대로 두고
    인쇄 시에만 생략해야 하므로, 셀 메모를 지우는 대신 이 파라미터로
    막는다."""
    return (
        f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/export"
        f"?format=pdf&gid={gid}&range={range_a1}"
        f"&size=letter&portrait=true&fitw=true&scale=4"
        f"&top_margin=0.05&bottom_margin=0.05&left_margin=0.05&right_margin=0.05"
        f"&gridlines=false&printtitle=false&sheetnames=false&pagenumbers=false"
        f"&horizontal_alignment=CENTER&vertical_alignment=TOP&attachment=false"
        f"&printnotes=false"
    )


def _rasterize_and_crop(pdf_path: Path, png_path: Path) -> None:
    doc = fitz.open(pdf_path)
    try:
        page = doc[0]
        zoom = _RASTER_DPI / 72
        pixmap = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom))
        image = Image.frombytes("RGB", (pixmap.width, pixmap.height), pixmap.samples)
    finally:
        doc.close()

    background = Image.new("RGB", image.size, (255, 255, 255))
    diff = ImageChops.difference(image, background)
    bbox = diff.getbbox()
    if bbox is not None:
        left, top, right, bottom = bbox
        left = max(0, left - _CROP_PADDING)
        top = max(0, top - _CROP_PADDING)
        right = min(image.width, right + _CROP_PADDING)
        bottom = min(image.height, bottom + _CROP_PADDING)
        image = image.crop((left, top, right, bottom))

    image.save(png_path, format="PNG")


@contextlib.contextmanager
def capture_field_sheet_image(
    spreadsheet: gspread.Spreadsheet,
    range_a1: str = _EXPORT_RANGE,
) -> Iterator[Path]:
    """"필드" 시트의 현재 상태를 PNG로 캡처해 임시 파일 경로를 넘겨준다.

    인증은 별도로 만들지 않고 `spreadsheet`가 이미 들고 있는 gspread 인증
    세션(`spreadsheet.client.session`, `AuthorizedSession`)을 재사용한다.
    """
    gid = spreadsheet.worksheet(_FIELD_SHEET).id
    response = spreadsheet.client.session.get(
        _export_url(spreadsheet.id, gid, range_a1)
    )
    response.raise_for_status()

    with TemporaryDirectory() as tmpdir:
        pdf_path = Path(tmpdir) / "field.pdf"
        png_path = Path(tmpdir) / "field.png"
        pdf_path.write_bytes(response.content)
        _rasterize_and_crop(pdf_path, png_path)
        yield png_path
