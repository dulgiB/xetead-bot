import os
from pathlib import Path

from html2image import Html2Image

from battle.core.battlefield_context import BattlefieldContext
from battle.objects.define import (
    CHARACTER_PER_COLUMN,
    BattlefieldColumnIndex,
    CombatStatType,
    FactionType,
)

_TEMPLATE_PATH = Path(__file__).parent / "template.html"
_COLUMNS = [col for col in BattlefieldColumnIndex if col != BattlefieldColumnIndex.NONE]

# template.html의 CSS 수치와 1:1 대응 — 한쪽을 바꾸면 반드시 같이 바꿀 것
_BODY_PAD_V = 16  # body padding-top / padding-bottom (각각)
_BODY_PAD_H = 16  # body padding-left / padding-right (각각)
_TITLE_H = 21  # .battlefield-title (font 11px line-height ~1.4) + margin-bottom 10px
_FACTION_HDR_H = 20  # .faction-header: padding 4px×2 + font ~11px + border-bottom 없음
_COL_HDR_H = 17  # .column-header: padding 3px×2 + font ~10px + border-bottom 1px
_CARD_H = 76  # .char-card / .empty-slot height
_CARD_GAP = 1  # .column-cards gap (= border 색으로 표현)
_DIVIDER_H = 22  # .divider: padding 5px×2 + font ~10px + border×2
_COL_W = 118  # .column width
_N_COLS = len(_COLUMNS)
_OUTER_BORDER = 2  # .columns-row 외곽 border 1px × 2면
_COL_BORDER = 1  # 열 사이 border


def _compute_image_size() -> tuple[int, int]:
    cards_area_h = (
        CHARACTER_PER_COLUMN * _CARD_H + (CHARACTER_PER_COLUMN - 1) * _CARD_GAP
    )
    faction_h = _FACTION_HDR_H + _COL_HDR_H + cards_area_h
    width = (
        2 * _BODY_PAD_H + _OUTER_BORDER + _N_COLS * _COL_W + (_N_COLS - 1) * _COL_BORDER
    )
    height = 2 * _BODY_PAD_V + _TITLE_H + 2 * faction_h + _DIVIDER_H
    # 브라우저 서브픽셀 렌더링 여유분 포함
    return width + 8, height + 8


def _hp_bar_color(curr: int, max_hp: int) -> str:
    ratio = curr / max_hp if max_hp > 0 else 0
    if ratio > 0.6:
        return "#43a047"
    elif ratio > 0.3:
        return "#fb8c00"
    return "#e53935"


def _char_card_html(char, faction_class: str) -> str:
    name = str(char.id)
    curr_hp = char.status.curr_hp
    max_hp = char.status[CombatStatType.MAX_HP]
    hp_pct = max(0, min(100, round(curr_hp / max_hp * 100))) if max_hp > 0 else 0
    rem_cost = char.status.remaining_cost
    max_cost = char.status[CombatStatType.COST_PER_TURN]

    return (
        f'<div class="char-card {faction_class}">'
        f'<div class="char-name">{name}</div>'
        f"<div>"
        f'<div class="hp-bar-track">'
        f'<div class="hp-bar-fill" style="width:{hp_pct}%;background:{_hp_bar_color(curr_hp, max_hp)};"></div>'
        f"</div>"
        f'<div class="hp-text">HP {curr_hp} / {max_hp}</div>'
        f"</div>"
        f'<div class="cost-text">코스트 {rem_cost} / {max_cost}</div>'
        f"</div>"
    )


def _faction_section_html(context: BattlefieldContext, faction: FactionType) -> str:
    label = faction.value
    faction_class = "enemy" if faction == FactionType.ENEMY else "ally"

    col_htmls: list[str] = []
    for col in _COLUMNS:
        slots = context.position_map[faction][col]
        # 적군은 슬롯을 역순으로 배치해 채워진 카드가 하단(VS 라인 쪽)에 쌓이게 함
        slot_indices = (
            range(CHARACTER_PER_COLUMN - 1, -1, -1)
            if faction == FactionType.ENEMY
            else range(CHARACTER_PER_COLUMN)
        )
        slot_htmls: list[str] = []
        for slot_idx in slot_indices:
            if slot_idx in slots:
                char = context.characters[slots[slot_idx]]
                slot_htmls.append(_char_card_html(char, faction_class))
            else:
                slot_htmls.append('<div class="empty-slot"></div>')

        if faction == FactionType.ENEMY:
            col_htmls.append(
                f'<div class="column">'
                f'<div class="column-cards {faction_class}">'
                + "".join(slot_htmls)
                + f"</div>"
                f'<div class="column-header bottom enemy">{col}열</div>'
                f"</div>"
            )
        else:
            col_htmls.append(
                f'<div class="column">'
                f'<div class="column-header ally">{col}열</div>'
                f'<div class="column-cards {faction_class}">'
                + "".join(slot_htmls)
                + "</div>"
                "</div>"
            )

    if faction == FactionType.ENEMY:
        # 적군: columns-row → faction-header 순서 (faction-header가 최하단)
        return (
            '<div class="columns-row">'
            + "".join(col_htmls)
            + "</div>"
            + f'<div class="faction-header {faction_class}">{label}</div>'
        )
    else:
        # 아군: faction-header → columns-row 순서 (faction-header가 최상단)
        return (
            f'<div class="faction-header {faction_class}">{label}</div>'
            + '<div class="columns-row">'
            + "".join(col_htmls)
            + "</div>"
        )


def render_battlefield_html(context: BattlefieldContext) -> str:
    template = _TEMPLATE_PATH.read_text(encoding="utf-8")
    enemy_section = _faction_section_html(context, FactionType.ENEMY)
    ally_section = _faction_section_html(context, FactionType.ALLY)
    content = enemy_section + '<div class="divider">── VS ──</div>' + ally_section
    return template.replace("{CONTENT}", content)


def render_battlefield_image(
    context: BattlefieldContext,
    *,
    size: tuple[int, int] | None = None,
) -> bytes:
    html = render_battlefield_html(context)
    w, h = size if size is not None else _compute_image_size()
    hti = Html2Image(output_path=os.getcwd(), size=(w, h))
    hti.screenshot(html_str=html, save_as="battlefield.png")
    return Path(os.path.join(os.getcwd(), "battlefield.png")).read_bytes()
