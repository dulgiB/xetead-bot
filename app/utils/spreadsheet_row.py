"""gspread Worksheet.get_all_records()가 반환하는 한 행의 타입.

숫자로 보이는 셀은 int 또는 float로, 그 외에는 str로 온다. 체크박스 컬럼은
bool로 오기도 하지만 그 경우는 parse_spreadsheet_bool()이 별도로 처리하므로
여기 포함하지 않는다.
"""

SpreadsheetRow = dict[str, str | int | float]
