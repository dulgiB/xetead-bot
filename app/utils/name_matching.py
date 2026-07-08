"""커맨드에 등장하는 고유명사(캐릭터/스킬/아이템 이름 등)와 고정 문자열 커맨드
키워드를 공백 유무와 무관하게 매칭하기 위한 유틸리티.

스프레드시트의 표시용 이름(예: "변칙 공격", "적군 1")은 그대로 유지하고,
사용자가 커맨드에 공백을 다르게 입력해도(예: "변칙공격") 매칭되도록
비교 시점에만 공백을 제거해 대조한다.
"""

import re
from typing import Iterable, Optional


def normalize_name(name: str) -> str:
    """비교용으로 문자열의 공백을 모두 제거한다."""
    return re.sub(r"\s+", "", name)


def resolve_matching_key(raw: str, candidates: Iterable[str]) -> str:
    """공백 차이를 무시하고 candidates에서 raw와 일치하는 원래 표기를 찾는다.

    정확히 일치하는 항목이 있으면 그대로 반환하고, 공백만 다르게 일치하는
    항목이 있으면 candidates 쪽 표기로 치환해 반환한다. 일치하는 항목이
    없으면 raw를 그대로 반환한다 (호출측의 기존 '존재하지 않음' 처리 경로를
    그대로 타도록 하기 위함).
    """
    candidates = list(candidates)
    if raw in candidates:
        return raw
    target = normalize_name(raw)
    for candidate in candidates:
        if normalize_name(candidate) == target:
            return candidate
    return raw


def find_matching_key(raw: str, candidates: Iterable[str]) -> Optional[str]:
    """resolve_matching_key와 동일하게 찾되, 일치하는 게 없으면 None을 반환한다."""
    candidates = list(candidates)
    if raw in candidates:
        return raw
    target = normalize_name(raw)
    for candidate in candidates:
        if normalize_name(candidate) == target:
            return candidate
    return None


def whitespace_tolerant_literal(literal: str) -> str:
    """리터럴 문자열의 각 글자 사이에 \\s*를 끼워 넣어, 글자 사이에 공백이
    섞여 들어와도 매칭되는 정규식 패턴 조각을 만든다.

    예: whitespace_tolerant_literal("페이즈") == "페\\s*이\\s*즈"
    정규식 특수문자가 없는 순수 한글/영문 키워드에만 사용한다.
    """
    return r"\s*".join(literal)
