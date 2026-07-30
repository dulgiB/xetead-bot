"""스프레드시트 셀의 boolean 컬럼 값을 안전하게 해석/표기한다.

gspread가 반환하는 값은 시트 컬럼이 실제 체크박스/boolean으로 되어 있으면
Python bool을, 일반 텍스트로 "TRUE"/"FALSE"가 입력되어 있으면 str을
반환한다. `bool("FALSE")`는 빈 문자열이 아니라는 이유로 True가 되므로,
이 둘을 구분하지 않고 bool()로 그대로 캐스팅하면 텍스트로 "FALSE"가
입력된 셀이 True로 잘못 해석되는 실수가 반복된다.
"""

from typing import Any


def parse_spreadsheet_bool(value: Any) -> bool:
    """스프레드시트 셀 값을 bool로 해석한다.

    - 이미 bool이면 그대로 반환한다(체크박스 등 실제 boolean 컬럼).
    - 문자열이면 앞뒤 공백을 지우고 대소문자 무관하게 "TRUE"인 경우만 True로
      인식한다 — "FALSE"/빈 문자열/그 외 텍스트는 전부 False.
    - 그 외(None 등)는 Python 기본 bool() 규칙을 따른다.
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().upper() == "TRUE"
    return bool(value)


def format_spreadsheet_bool(value: bool) -> str:
    """bool 값을 스프레드시트에 텍스트로 적을 때 쓰는 표준 표기로 변환한다."""
    return "TRUE" if value else "FALSE"
