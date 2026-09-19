# CLAUDE.md

## 프로젝트 개요

TRPG 캠페인의 전투를 자동 정산하는 Mastodon 봇. 전투 로직(`app/battle/`)과 봇 인터페이스(`app/bot/`)가 분리되어 있다.

데이터(스킬, 버프, 캐릭터)는 Google Spreadsheet에서 로드하며, 클래스 이름을 문자열로 저장하고 `importlib`로 동적 dispatch한다.

---

## 디렉터리 구조

```
app/
  battle/
    core/
      battlefield_context.py   # 전장 전체 상태 (캐릭터, 위치, 버프, 결과)
      round_manager.py          # 라운드 페이즈 관리 및 커맨드 라우팅
      command_expanders.py      # CommandPart → CommandPartData 전개
      command_processors.py     # 전개 전 검증 + 실제 효과 적용
      command_calculator.py     # 이동/대미지/힐/버프 개별 처리 + 버프 이벤트 적용
      buff_container.py         # 버프 생명주기 (추가/제거/라운드 훅/반응형 트리거)
      field_effect_container.py # 필드 효과 생명주기 (등록/해제/스탯 오프셋/중간 참전)
      commands/
        define.py               # RoundPhaseType enum
        models.py               # CharacterCommand, CommandPart, CommandPartData, DamageCalculateData 등
        parser.py               # 문자열 → CharacterCommand 파싱
        admin.py                 # AdminCommand 계열 (강제 이동/대미지/힐/버프 부여·제거)
    exceptions.py                # CommandValidationError, 검증 실패 메시지 생성 함수들
    logger.py                    # Logger, CommandResult (콘솔 디버그 로그)
    practice/                    # 대련/결투/상시전투 전용 축소 라운드 관리
      context.py                 # PracticeBattlefieldContext
      define.py                  # SideType, PracticeBattleMode, PracticeRoundPhase
      round_manager.py           # PracticeRoundManager
    objects/
      buff/
        buff_base.py             # BuffBase, BuffDurationCounter, BuffAddData
        buff_events.py           # BuffEvent 추상 기반
        buffs/                   # 개별 버프 구현체
        models.py                # BuffData (스프레드시트 행 대응)
        conditions.py            # 버프 적용 조건
        reactive_damage.py       # 제3자 반응형 대미지에 주는/받는 대미지 버프 반영
        damage_factory.py        # 계수 기반 대미지(DamageCalculateData) 생성 헬퍼
      skill/
        models.py                # SkillData, SkillEffectBase, Skill
        target_functions.py      # SkillTargetRule 구현체
        effects/                 # 개별 스킬 효과 구현체
        define.py                # SkillValueType
      passive_skill/
        models.py                # PassiveSkillData ("스킬_패시브"/"버프_패시브" 시트 대응)
        passive_skill.py         # PassiveSkillWrapperBuff/Event — BuffBase 인터페이스로 감싸 BuffContainer에 등록
      field_effect/
        models.py                # FieldEffect, FieldEffectOp, FieldEffectSource, 센티넬 홀더
      item/
        models.py                # Item, ItemData (소비형 아이템 슬롯, 부적의 passive_skill_id)
      character/
        combat_character.py      # CombatCharacter
        combat_stats.py          # CombatStats
        buffed_stats.py          # 버프 반영 후 최종 스탯 계산
      companion.py                # 소환수(동료) 생존 여부 등 헬퍼 (is_companion_alive)
      extensions.py                # CommandPart 코스트 계산 (get_total_cost)
      models.py                    # CharacterId, DamageData, HealData, ValueWithModifiers 등
      define.py                    # 주요 enum (ActionType, BuffApplyTiming, CombatStatType 등)
  bot/                          # Mastodon 봇 인터페이스
    main.py                     # 봇 진입점 (MastodonBotListener)
    commands/
      admin.py                  # Admin 커맨드 핸들러
      character.py              # 캐릭터 전투 커맨드 핸들러
      noncombat.py              # 비전투 커맨드 핸들러 (판정, 의뢰, 상시조사)
    session.py                  # BattleSession
    practice_state.py           # PracticeBattleState (대련/결투/상시전투)
    noncombat_state.py          # NonCombatState
    load_data.py                # 스프레드시트 데이터 로딩
    log_sheets.py                # "필드"/"로그_전투"/"로그_비전투" 시트 기록 (내부 자동화 DB)
    field_sheet_renderer.py      # 공개용 "필드" 시트(관중 노출용) 렌더링
    field_sheet_image.py         # 공개용 "필드" 시트를 이미지로 캡처
    battle_reply_text.py         # 전투 커맨드 처리 결과 → 답글 텍스트 조립
  spreadsheets/
    models/                       # 스프레드시트 행 ↔ dataclass 매핑 (combat/noncombat/quest)
    inventory.py                  # 아이템 인벤토리 조회/차감
  utils/
    battle_helpers.py              # is_reachable() 등 사거리/위치 계산
    dice.py                        # nd6() 주사위 굴림
    name_matching.py               # 커맨드 고유명사 매칭 유틸 (공백 무관)
    logging.py                     # 대미지/회복 적용 콘솔 로그
```

---

## 커맨드 처리 파이프라인

```
입력 문자열
  └─ parse_character_command()          # parser.py
       └─ CharacterCommand (parts 리스트)
            └─ try_expansion_if_valid() # command_processors.py
                 ├─ 사전 검증 (사용자 존재, 스킬 등록 여부, target_count, 코스트, 대상 존재, 사거리)
                 └─ expand_character_command() # command_expanders.py
                      └─ list[CommandPartData] (move/damage/heal/buff_add 분리됨)
                           └─ process_move/damage/heal/buff_add()
                                └─ _apply_buff_events() → BuffEvent.apply()
```

각 `CommandPart` 하나가 여러 `CommandPartData`로 전개될 수 있다 (스킬 효과가 복수인 경우).

---

## 라운드 페이즈

```
ENEMY_PRE_ACTION  →  ALLY_ACTION  →  ENEMY_POST_ACTION  →  BUFF_UPDATE_AND_NEXT_ROUND_STANDBY
     (적 선언)          (아군 행동)        (적 공격 정산)            (버프 턴수 차감, 라운드 종료)
```

대련/상시전투는 이 4페이즈 대신 선공/후공 2페이즈를 쓴다
(`PracticeRoundManager`). 선공을 정하는 방식은 진영 구도에 따라 갈린다
(`_draw_movers()`):

- **대련/결투**: 매 라운드 다시 추첨한다. 밸런스가 PvE 기준으로 짜여 있어
  순서를 고정하면 불리한 캐릭터가 매번 같은 방식으로 지므로, "선공을 잡으면
  상대가 행동하기 전에 끝낼 수도 있다"는 역전 여지를 남기는 밸런스 장치다.
- **상시전투**: 아군(SIDE_1) 선공 고정. 본 전투가 아군 행동 뒤에 적 후행
  정산을 두는 것과 같은 순서다. 그만큼 적군이 거는 1턴짜리 효과는 구조적으로
  뒤로 밀리므로, 상시전투에 배치하는 적에게는 1턴 효과를 주지 않는 것이
  데이터 쪽 운영 원칙이다.

- 적군 커맨드는 **PRE**에서 이동과 PRE 타이밍 버프만 즉시 처리, 대미지/힐/POST 버프는 `remaining_parts_dict`에 저장했다가 **POST** 페이즈에 처리.
- `on_start_round()` = 코스트 초기화 + `ON_ROUND_START` 버프 이벤트.
- `on_finish_round()` = `ON_ROUND_END` 버프 이벤트 + 턴 차감/제거.

---

## 버프 시스템

### 등록

스프레드시트 "버프" 시트(컬럼 스키마는
[SPREADSHEET_SCHEMA.md](SPREADSHEET_SCHEMA.md#버프-시트-버프) 참고) →
`BuffData.from_dict()` → `buff_class_name` 문자열(시트 컬럼명은 `buff_name`)로
`importlib` dispatch → `BuffBase` 구현체 인스턴스화.

### 타이밍

| `BuffApplyTiming`               | 트리거                                                              |
|----------------------------------|-------------------------------------------------------------------|
| `ON_BATTLE_START`                 | `buff_container.on_battle_start()`                                 |
| `ON_ROUND_START`                  | `buff_container.on_round_start()`                                   |
| `ON_ACTION`                       | `_apply_buff_events()` (자신이 공격/피격 시)                              |
| `ON_ENEMY_POST_ACTION`            | `buff_container.on_enemy_post_action()`                             |
| `ON_ENEMY_POST_ACTION_RESOLVED`   | `buff_container.on_enemy_post_action_resolved()` (지연 공격 반영 후 평가) |
| `ON_ROUND_END`                    | `buff_container.on_round_end()`                                     |
| `ON_ENEMY_MOVE`                   | `buff_container.on_enemy_move()` (자발적/강제 이동 모두)                  |
| `ALLY_DAMAGED`                    | `buff_container.on_character_damaged()` (같은 열·자신 포함)              |
| `ALLY_IN_RANGE_DAMAGED`           | `buff_container.on_ally_in_range_damaged()` (사거리 내·자신 포함)         |
| `ALLY_IN_RANGE_ATTACKED`          | `buff_container.on_ally_in_range_attacked()` (사거리 내·자신 포함)        |

`ON_ENEMY_POST_ACTION_RESOLVED`는 `ON_ENEMY_POST_ACTION`과 스프레드시트 트리거
값("적 후행 시")이 같지만, `damaged_this_round`가 확정된 뒤에 평가돼야 하는
패시브 효과(조건이 `Condition.requires_round_resolved = True`이거나 — 예:
`HolderWasAttackedCondition` — 효과 자체가
`SkillEffectBase.requires_round_resolved = True`인 경우)를 위해
`PassiveSkillWrapperBuff.timing`이 자동으로 골라준다 — 버프 시트에 직접
등록하는 값이 아니다. 한 패시브 안에서 효과마다 갈릴 수 있으며, 그때는
`create()`가 `"effects"`/`"effects_resolved"` 인스턴스로 나눠 등록한다.

### 버프 이벤트 vs 대상 오버라이드

- **`BuffEvent.apply()`**: `CommandPartCalculator`를 받아 대미지/힐 수치를 변경하는 계산 시점 훅.
- **`BuffBase.get_target_override()`**: `None` 반환이 기본값. `None`이 아니면
  도발 리다이렉트 대상이 된다 (도발 등).

대상 교체가 필요한 버프는 `get_target_override()`를 오버라이드하고,
`ON_ACTION` 타이밍을 유지하면 버프 횟수 차감(`deduct_count`)이 자동으로
동작한다.

전개(`expand_character_command()`)는 커맨드에 적힌 대상 그대로 펼치고,
실제 치환은 `CommandPartCalculator`가 맡는다:

1. `taunt_redirect.assign_taunt_redirects()`가 한 캐릭터가 이번에 선언한
   **공격 인스턴스 전체**를 한 배치로 보고, 도발자마다 인스턴스를 하나씩
   무작위로 배정해 각 계산기의 `precomputed_taunt_redirects`에 채운다 —
   그래서 도발은 그 캐릭터의 공격을 전부가 아니라 **1개만** 끌어온다.
   이미 도발자를 직접 겨냥한 인스턴스는 재추첨 풀에서 빠지고, 풀이 먼저
   바닥나면 남은 도발자는 이번 라운드에 유도하지 못한다.
2. `CommandPartCalculator._prepare_redirects()`가 그 결과(+ 대리 수령
   `get_sacrifice_override()`)를 대미지 `target_id`에 반영하고 `redirect_map`에
   기록하며, 같은 커맨드의 `buff_add` 부가 효과도 `_redirect_applied_to()`로
   함께 옮긴다(이동은 옮기지 않는다 — 목적지가 원래 대상 기준으로 검증된다).

`ignores_taunt` 대미지(열 광역기 등)는 1단계의 배치 대상에서 빠진다.

### 지속 시간

- `remaining_turns`: 라운드 종료 시 차감
- `remaining_count`: 공격 또는 피격 시 차감 (`BuffCountDeductCondition`)
- 둘 다 `None`이면 패시브 (영구)
- 적층 버프는 스택이 0이 되는 순간에도 제거된다
  (`CommandPartCalculator._process_buff_remove()`). 스택 0짜리 인스턴스를
  남기면 `TargetHasDebuffCondition`·`reference_buff_id` 조회가 여전히
  "보유 중"으로 답해 수치가 0인데도 효과가 붙고, 필드 요약에도
  `[버프] (N턴/0스택)`이 뜬다. 답글에 찍을 "최종 스택"은 제거 전에
  `BuffRemoveCalculateData.remaining_stack`으로 빼 둔 값을 쓴다.
- 스택 차감은 기본적으로 같은 effect의 대미지보다 **먼저** 일어난다
  (`ValueSourceType.CONSUMED_BUFF_STACK`이 차감량을 읽어야 하므로).
  `BuffRemoveData.after_damage=True`인 항목만 대미지 뒤로 미뤄, 스택을
  터뜨리는 그 일격 자신이 아직 그 버프가 걸린 상태를 보고 계산되게 한다
  (`SkillEffectDamageByDebuffStackTier`의 최대 스택 분기). 둘은 함께 쓸 수
  없다 — 미룬 차감은 대미지 계산 시점에 `result_value`가 아직 없다.

**"지난 라운드에 X였으면 이번 라운드 동안 버프"는 라운드 종료가 아니라
라운드 시작 트리거로 표현한다.** `on_round_end()`는 `ON_ROUND_END` 이벤트를
돌린 **직후** 같은 호출에서 전체 턴을 차감하므로, 거기서 부여한 버프는 그
자리에서 1턴을 잃는다. 지속시간을 1 크게 적어 보정할 수는 있지만, 그러면
시트 값과 스킬 설명이 한 턴씩 어긋나 읽는 쪽이 매번 이 규칙을 알아야 한다.
대신
`BattlefieldContext.prev_damaged_this_round`(`on_start_round()`이 지우기 전에
떠 두는 직전 라운드 스냅샷)를 읽는 조건
(`OtherAllyInRangeWasAttackedLastRoundCondition` 등) + `라운드 시작` 트리거로
쓰면 지속시간을 설명 그대로 적을 수 있고 어느 모드에서나 같게 동작한다.

**차감 규칙은 모든 모드가 같다.** `on_round_end()`는 부여 시점을 보지 않고
필드의 모든 버프를 똑같이 1턴 깎는다 — 대련/결투/상시전투도 예외가 없다.
대련이 본 전투 규칙에 익숙해지는 자리이기도 하므로, 같은 데이터가 모드마다
다르게 보이지 않는 쪽을 택했다.

그 대신 선공/후공 2페이즈 구조에서는 양 팀이 한 라운드 안에서 각자 한 번씩
행동하므로, **라운드의 마지막 차례에 상대에게 건 1턴짜리 효과는 상대가 그
상태로 행동할 기회를 얻지 못한 채 사라진다.** 상대의 행동에 걸리는 것이
목적인 효과(취약·약화 등)는 데이터 쪽에서 2턴 이상으로 적어 해결한다.
1턴으로 남겨 두는 것은 본 전투 쓰임이 주가 되는 효과(도발 등)나, 그 라운드
안에서 값을 다 하는 효과뿐이다.

### 제3자 반응형 트리거와 공용 헬퍼

자신이 공격자/피격자가 아니어도 발동하는 반응형 타이밍(`ALLY_DAMAGED`,
`ALLY_IN_RANGE_DAMAGED`, `ALLY_IN_RANGE_ATTACKED`, `ON_ENEMY_MOVE`)은
`BuffContainer.on_*()`에서 처리한다. "같은 열" 기준과 "사거리 내" 기준은
범위 판정 함수만 다른 같은 패턴이므로, 새 반응형 타이밍을 추가할 때는
`BuffContainer._collect_reactive_event_pairs()`(timing 필터 + 진영 확인 +
범위 predicate)와 `_apply_reactive_events()`를 재사용한다.

같은 이유로 `conditions.py`의 "같은 열/사거리 내 × 자신 포함/제외" 조합
Condition들은 `_characters_in_holder_scope()` 헬퍼로 캐릭터 순회·필터링을
공유한다. 새 범위 기반 Condition을 추가할 때는 이 헬퍼에 predicate만
넘기는 방식을 우선 검토한다.

이 훅들은 대미지 항목이 아니라 **"한 번의 타격"당 한 번** 발동한다
(`CommandPartCalculator._reactive_hooks_fired`, ON_ATTACK/ON_HIT와 같은 기준).
effect를 여러 개 써서 같은 대상을 때리는 스킬에서 반격·추가 대미지가 구성요소
수만큼 붙지 않게 하기 위함이다. 묶는 단위는 (공격자, 대상) 쌍이라, 한 effect가
아군 여럿을 동시에 때리는 광역기는 피격자마다 정상 발동한다.

**동료(소환수)는 "아군" 범위 판정에서 일관되게 제외한다** —
`_characters_in_holder_scope()`, `SkillTargetRuleAllAllies`,
`PassiveSkill._resolve_targets()`, `SkillEffectAddBuffPerDamagedColumn`이
모두 `context.companion_owners`를 건너뛴다. 동료는 슬롯을 차지하지 않고
소환자의 위치를 그대로 따르는 종속 개체라, 세면 소환자 한 명이 두 명으로
잡히고(예: "사거리 내 아군 3명" 조건) 소환자가 스스로 동료 체력을 대가로
지불한 것까지 "아군 피격"으로 잡힌다.

`BuffEvent.is_pure_damage_modifier = True`(수치만 바꾸고 부수효과가 없는
이벤트)는 두 경로에서 따로 재실행된다. 둘 다 "부수효과 이벤트는 한 번만,
배율은 빠짐없이"라는 같은 규칙의 구현이므로, 새 이벤트를 만들 때 이 플래그를
정확히 세워야 한다:

- `CommandPartCalculator._apply_pure_modifier_events()`: ON_ATTACK/ON_HIT
  디스패치는 커맨드당 공격자/대상별 1회지만(반격·반사·지속 횟수 차감이
  effect마다 중복되면 안 되므로), 수치 수정자는 effect마다 다시 얹어야 한다
  — 안 그러면 두 번째 이후 effect의 대미지(돌진 스킬의 경로 광역 등)만
  조용히 배율을 못 받는다. 중복은 `(effect_seq_number, 보유자)`로 막는다.
- `reactive_damage.apply_pure_damage_modifiers_to()`: 반격/추가 대미지처럼
  버프가 나중에 끼워 넣는 대미지 항목에 양쪽 배율을 반영한다.

"ATK 굴림/스택 수 × 계수%" 형태의 대미지 항목(반격, 스택 비례 대미지 등)을
새로 만들 때는 `damage_factory.make_coefficient_damage_calc()`를 쓰고,
그 항목에도 배율이 붙어야 하면 `apply_pure_damage_modifiers_to()`로 감싼다.
FIXED 값이나 커스텀 `roll_display`가 필요한 대미지(`BuffDamageOverTime`,
`BuffReflect`)는 형태가 달라 이 팩토리 대상이 아니다.

---

## 스킬 시스템

### 데이터 흐름

스프레드시트 "스킬_캐릭터"/"스킬_에너미" 시트(컬럼 스키마는
[SPREADSHEET_SCHEMA.md](SPREADSHEET_SCHEMA.md#스킬_캐릭터--스킬_에너미-시트)
참고) → `SkillData.from_dict()` → `to_skill_instance()` → `Skill(target_rule, data)`.

### SkillTargetRule

| 구현체                           | 설명                                          | `ignores_input_targets` |
|-------------------------------|---------------------------------------------|--------------------------|
| `SkillTargetRuleSelf`         | 시전자 자신 고정                                    | `True`                   |
| `SkillTargetRuleNamed`        | 이름 지정 대상 (시전자 사거리 제한 적용)                     | `False`                  |
| `SkillTargetRuleNamedExcludingSelf` | `SkillTargetRuleNamed`와 동일하되 시전자 자신을 지정하면 검증 실패 | `False`             |
| `SkillTargetRuleNamedWithColumn` | 캐릭터 1명 + 그 캐릭터에 인접한 열 1개(생략 가능) 동시 지정      | `False`                  |
| `SkillTargetRuleColumn`       | 열(column) 기준 광역, 항상 시전자의 `foe_faction`(적 진영)  | `False`                  |
| `SkillTargetRuleAllyColumn`   | 열 기준 광역, 항상 시전자와 같은 진영(아군)                  | `False`                  |
| `SkillTargetRuleColumnRange`  | 열 1개 지정 → ±2열(최대 5열) 광역, 항상 시전자의 `foe_faction`(적 진영) | `False`                  |
| `SkillTargetRuleAllAllies`    | 입력 무시, 시전자와 같은 진영 전원(시전자 자신·동료 제외)         | `True`                   |

`ignores_input_targets`는 커맨드에 적힌 대상 입력을 규칙이 무시하는지만
뜻한다 — `fate_config_error()`가 "대상 추가" 모드를 걸러내는 데만 쓰고,
도발 리다이렉트 여부와는 무관하다(그쪽은 `ignores_taunt`가 정한다).
`SkillTargetRuleColumn`/`SkillTargetRuleAllyColumn`/`SkillTargetRuleColumnRange`는 입력이 열 번호일 뿐 대상
진영은 입력값과 무관하게 규칙이 고정한다는 점에 주의 — 반대로 **기본 공격
(`ActionType.ATTACK`)은 이 규칙 자체를 타지 않는 별도의 하드코딩된 분기**라서
진영 검증이 전혀 없다. 즉 `공격/[아군 이름]`처럼 입력하면 사거리 검증만
통과하면 실제로 아군에게도 대미지가 들어간다(`command_expanders.py`의
`ActionType.ATTACK` 분기, `command_processors.py`의 사전 검증 항목 어디에도
진영 확인이 없음).

### SkillEffect

`SkillEffectBase.expand(context, holder, targets, raw_targets=()) → (move_list, damage_list, heal_list, buff_add_list, buff_remove_list)`

`target_override`가 설정돼 있으면 `expand()`가 대상을 자동 치환하고 실제
구현은 `_expand()`(서브클래스가 오버라이드)에만 위임한다.

스킬 하나에 effect 최대 3개까지 정의 가능 (`effect_0`, `effect_1`, `effect_2` 컬럼).
패시브 스킬(`PassiveSkillData.effects`)도 같은 `SkillEffectBase` 구현체를
재사용하며, 최대 `MAX_PASSIVE_EFFECT_COUNT`(3)개까지 정의 가능하다.

### 에너미 스킬 예고 블라인드 (`SkillData.revealed`)

본 전투(`RoundPhaseType.ENEMY_PRE_ACTION`이 있는 경로)에서 에너미가
스킬을 선언하면 답글에 `↳ {description}` 형태로 효과를 미리 예고한다
(`bot/battle_reply_text.py`의 `format_battle_reply(..., show_skill_preview=True)`).
아직 한 번도 선언된 적 없는 스킬(`SkillData.revealed == False`, "스킬_에너미"
시트 `is_revealed` 컬럼)은 설명 대신 `[효과 미확인]`으로 블라인드 처리된다.

선언 시점에는 그 값 그대로(블라인드면 블라인드로) 답글을 만들고, 그 *다음에*
`bot/load_data.py`의 `reveal_declared_enemy_skills()`가 이번에 선언된 스킬을
공개 상태로 전환한다 — `BattlefieldContext.mark_skill_revealed()`로 같은
전투 세션의 `skill_dict`를 즉시 갱신하고, "스킬_에너미" 시트에도 write-back해
다음 전투부터도 공개 상태가 유지되게 한다. 즉 이번 선언 자체는 블라인드로
예고되고, 같은 스킬의 다음 선언부터 설명이 노출된다. 공개 여부는 에너미별이
아니라 스킬 id 단위 전역 상태다(스킬 데이터 자체가 에너미별이 아니라 id로
공유되므로).

대련/결투/상시전투(`PracticeRoundManager`)는 페이즈 구조가 달라 이 기능
대상이 아니다.

---

## 패시브 스킬 시스템

일반 버프(`BuffBase`, "버프" 시트)와는 별도로, "스킬_패시브"/"버프_패시브"
시트로 관리되는 패시브 스킬 파이프라인이 있다.

- **`PassiveSkillData`**(`passive_skill/models.py`): "스킬_패시브" 시트 한 행
  대응. `trigger`(`PassiveSkillTrigger`), `target_type`
  (`PassiveSkillTargetType`), `effects`(`SkillEffectBase` 재사용), 그리고
  선택적으로 `buff_mod_event`("버프_패시브" 시트에서 기존 `BuffBase` 구현체를
  가져와 만든 `BuffEvent` 인스턴스 — 버프 시트 없이 버프 이벤트 로직만
  재사용하는 경로)를 가진다.
- **`PassiveSkillWrapperBuff`**(`passive_skill.py`): `PassiveSkillData`를
  `BuffBase` 인터페이스로 감싸 `BuffContainer`에 그대로 등록한다.
  `buff_mod_event`와 `effects`는 서로 다른 `BuffApplyTiming`이 필요할 수 있어
  (전자는 실제 공격 처리 중이어야 하는 `ON_ACTION` 고정, 후자는 `trigger`가
  선언한 타이밍), `create()`가 역할별로 버프 인스턴스를 나눠 만들어 등록한다.
  역할은 `"buff_mod"` / `"effects"` / `"effects_resolved"` 세 가지이며, 뒤의
  둘은 `_indexed_effects_for_role()`이 효과별 `requires_round_resolved`를 보고
  가른다 — 한쪽 타이밍에 몰아넣으면 다른 쪽이 한 라운드씩 밀리기 때문이다
  (그 라운드의 피격을 경감할 버프는 `ON_ENEMY_POST_ACTION`에, 그 라운드의
  피격 결과를 읽는 효과는 `ON_ENEMY_POST_ACTION_RESOLVED`에 걸려야 한다).
- **`PassiveSkillTargetType`**: `SELF`/`SAME_COLUMN_ALLIES`/
  `SELF_AND_SAME_COLUMN_ALLIES`/`SELF_AND_ADJACENT_COLUMN_ALLIES`/
  `ALL_ALLIES`/`ATTACKER_OR_TARGET`/`LOWEST_HP_ALLY`. `_resolve_targets()`가
  실제 대상 목록으로 변환하며, 동료(소환수, `context.companion_owners`)는
  아군 범위 대상에서 제외된다.

아군 전체/열 범위에 **받는 대미지 경감**을 주는 패시브는 `buff_id`(버프
모디파이어) 경로로는 구현할 수 없다 — `_apply_buff_events()`는 피격 당사자에게
`applied_to`된 버프만 조회하는데 래퍼는 홀더에게만 등록되므로, 그 경로는
홀더 본인에게만 적용된다(`target_type`이 무시된다). 범위 경감은 `effect_N`으로
"버프" 시트의 실제 경감 버프를 매 라운드 대상들에게 부여하는 방식으로 만든다.

### 대상별 조건 (`target_condition_N`)

`condition_N`이 효과 전체를 켜고 끄는 것과 달리, `target_condition_N`은 이미
정해진 대상 목록에서 조건을 만족하지 않는 대상을 걸러낸다("체력 50% 이하인
아군에게만" 등). 조건 클래스는 그대로 재사용하며 `holder` 자리에 각 대상을
넣어 평가하므로, `SelfHpBelowCondition`이 "그 대상의 체력이 N% 미만"이 된다.
`SkillEffectBase.expand()`가 거르므로 스킬·패시브·필드 효과 어디에나 붙는다.

**조건에서 벗어났을 때 버프를 걷어야 하면 `SkillEffectConditionalBuff`를
쓴다.** `SkillEffectAddBuff` + `target_condition_N`은 부여만 하므로 조건을
벗어나도 지속시간이 끝날 때까지 남는다. 조건부 버프 효과만
`applies_target_condition_itself`를 켜서 필터를 끄고 전체 목록을 받는다 —
조건을 만족하지 못한 대상에게도 할 일(회수)이 있기 때문이다. 회수는 그
효과가 `given_by`로 건 인스턴스만 지운다.

---

## 필드 효과 (`FieldEffect`)

캐릭터가 아니라 **전장에** 걸리는 효과다. 지속 턴수가 없고 명시적으로
해제하기 전까지 유지되며, 본 전투에서만 쓴다(`allow_field_effects`).

### 데이터는 "스킬_패시브" 시트를 공유한다

필드 효과 전용 시트는 없다. 효과 본체는 `PassiveSkillData`를 그대로 쓰고,
**홀더를 보지 않는 필드 범위 `target_type`이 그 행을 캐릭터 패시브와
구분한다**(`PassiveSkillData.is_field_effect`).

| 값 | 대상 |
|---|---|
| `필드 아군 진영` | 아군 전원 |
| `필드 적군 진영` | 적군 전원 |
| `필드 전원` | 양 진영 전원 |
| `필드 사건 당사자` | 반응형 트리거에서 그 사건을 일으킨 캐릭터 |

앞의 셋은 **절대 진영** 기준이다 — 보스가 자기 진영을 강화하는 필드 효과는
`필드 적군 진영`이다. 반응형 트리거에서는 이 값이 "누구의 사건에 반응하는가"도
함께 정한다(`필드 사건 당사자`는 진영을 가리지 않는다).

### 수치 반영은 BuffContainer에 위임한다

필드 효과는 전장에 없는 **센티넬 홀더**(`__field__{id}`)로 래퍼 버프를
등록해 두고, 트리거가 오면 기존 패시브 파이프라인이 그대로 대상들에게 실제
버프를 부여한다. 계산 경로를 새로 만들지 않으므로 `buffed_stats`와
`_apply_buff_events()`는 필드 효과를 알지 못한다.

센티넬은 **효과마다 고유**하다 — 걷을 때 `given_by`로 자기가 부여한 버프만
정확히 회수하기 위해서다.

홀더가 전장에 없다는 사실이 세 곳에서 특별 취급을 요구한다:

- `resolve_passive_targets()`는 필드 범위를 `characters.get(holder)` **앞에서**
  처리한다. 뒤에 두면 홀더가 없어 대상이 하나도 안 잡힌다.
- `BuffContainer._collect_reactive_event_pairs()`는 홀더의 진영 대신 **사건
  당사자의 진영**(`subject_faction`)으로 가린다. `required_faction`은 훅마다
  의미가 달라(이동은 `foe_faction`, 피격은 당사자 진영) 쓸 수 없다.
- `CommandPartCalculator._is_live_damage_calc()`는 센티넬 공격자를 통과시킨다.
  `characters` 조회만으로 가리면 "이미 사망한 공격자"로 오인해 항목을 통째로
  버린다.

### 효과에 쓸 수 있는 것

`SkillEffectBase.requires_holder_character`가 `False`인 효과만 쓸 수 있다.
기본값은 `True`(시전자 필요)이므로, 새 효과를 만들 때 표시를 빠뜨리면 필드
효과에서 거부될 뿐 조용히 깨지지는 않는다.

| 효과 | 쓰임 |
|---|---|
| `SkillEffectAddBuff` / `SkillEffectConditionalBuff` | 범위에 버프/디버프 부여 |
| `SkillEffectFieldDamage` | 시전자 없는 고정 대미지 (물리 고정, 계수 미지원) |
| `SkillEffectFieldStatOffset` | 공격력·사거리·턴당 코스트 증감 |
| `SkillEffectAddFieldEffect` / `SkillEffectRemoveFieldEffect` | 다른 필드 효과 부여·해제 |

**스탯 증감은 `CombatStats.__getitem__`에 직접 얹는다.** 버프(`BuffedStats`)로는
안 되는데, `BuffedStats`는 `CommandPartCalculator` 안에서만 살기 때문에 사거리
검증·범위 조건·필드 시트 표시처럼 `CombatStats`를 직접 읽는 지점에 반영되지
않기 때문이다. 최대 체력은 지원하지 않는다.

### 부여·제거 경로 셋

- **admin**: `[필드효과/이름]` / `[필드효과해제/이름]`. 디스패치에서 해제를
  먼저 본다 — "필드효과해제"가 "필드효과" 패턴에도 걸리기 때문이다.
- **스킬**: `SkillEffectAddFieldEffect`/`SkillEffectRemoveFieldEffect` +
  `field_effect_id_N`. `expand()`의 5-튜플에 자리가 없어
  `get_field_effect_ops()`로 따로 받는다(디버프 일괄 제거와 같은 방식).
- **부적**: "아이템" 시트에서 `item_type`이 `부적`인 항목의
  `passive_skill_id`. **인벤토리에 가진 캐릭터가 있기만 하면 발동하며, 그
  소지자가 전투에 참여하는지는 보지 않는다** — 요구하면 전투 참여 압력이 되기
  때문이다.

### 등록 시점과 영속화

등록은 `BattlefieldContext.on_battle_start()` 한 곳에서, **버프 트리거보다
먼저** 한다("전투 시작" 트리거가 같은 호출에서 발동해야 하므로). 이 한 곳이면
신규 전투와 봇 재기동 복원이 함께 커버된다.

전투 도중 참전한 캐릭터는 `add_character()` 말미의
`FieldEffectContainer.apply_to_newcomer()`로 즉시 받는다 — 진영 판정은 정규
경로와 같은 `resolve_passive_targets()`를 거친다.

영속화는 "필드" 시트에 컬럼을 늘리지 않고 `meta_json`에 싣는다. 복원은
캐릭터 배치 뒤·`on_battle_start()` 전이어야 한다.

### 표시

필드 효과는 센티넬 홀더에 붙어 있어 **캐릭터별 버프 목록에는 잡히지
않는다** — 따로 보여주지 않으면 어디에도 드러나지 않는다.

표시 라벨은 `FieldEffect.display_label()`이 만드는 `이름[출처]`로 통일한다.
대괄호 안은 출처를 특정할 수 있으면 그 이름(부적 이름 등), 아니면 출처
종류(`시스템`/`스킬`/`부적`)다 — 어느 부적이 걸었는지가 종류보다 쓸모 있다.
admin을 "시스템"이라 적는 것은 게임 안에서 admin의 행동을 부르는 기존
이름(`commands/admin.py`의 `ADMIN_ID`)과 맞추기 위해서다.

나가는 곳은 셋이다.

- **공개 "필드" 시트**의 필드 효과 칸(`_FIELD_EFFECT_CELL`): 한 행짜리라
  줄을 나누면 두 번째부터 잘리므로 가운뎃점으로 이어 한 줄에 담고, 설명은
  버프 칸과 같이 셀 메모에 넣는다. 걸린 게 없으면 `없음` — 빈 칸으로 두면
  아직 렌더링되지 않은 것과 구분되지 않는다.
- **필드 텍스트**(`_format_field_effect_summary()`): 버프 요약보다 앞에 두고
  효과마다 한 줄씩, 설명을 아래에 붙인다.
- **답글 결과 줄**: `BattleLogEntryKind.FIELD_EFFECT`. 대상이 캐릭터가
  아니므로 "이름 | 결과"가 아니라 "필드 효과 발생: 이름"으로 나간다.

**"필드" 시트의 행 좌표는 `_HEADER_ROW` 하나에서 파생된다.** 시트 위쪽에
행이 늘고 줄면 그 값만 맞추면 진영 격자와 선언 내용 병합 범위가 함께
따라온다. 이미지 캡처 범위(`field_sheet_image._EXPORT_RANGE`)도 같은
상수에서 끝 행을 가져오므로 따로 고칠 필요가 없다 — 예전에는 리터럴이라
위쪽에 행이 늘면 아래가 조용히 잘렸다.

---

## 운명간섭 · 부활 횟수

"캐릭터" 시트의 `revival_count`(정수)와 `fate_date`(YYYY-MM-DD) 두 컬럼이
근간이다. 컬럼 스키마는 [README.md#캐릭터-시트](README.md#캐릭터-시트) 참고.

### revival_count는 읽기 전용이다

`revival_count`는 GM이 시트에서 직접 관리한다 — 봇은 배치 시점에 읽어 아래
수치 효과에만 반영하고 값을 갱신하지 않는다. 부활 횟수별 강화 중 코스트 3
스킬 해금(1회)과 코스트 2·3 스킬 강화(2·3회)도 GM이 스킬 슬롯을 조정하는
운영 처리이므로 **코드에 게이트를 두지 않는다**. 자동화하고 싶어지더라도,
"에너미" 시트에는 `revival_count` 컬럼이 없어 항상 0으로 읽힌다는 점을
먼저 고려해야 한다(에너미 전체가 게이트에 걸린다).

### 적용 지점

| 효과                 | 위치                                                                 |
|--------------------|--------------------------------------------------------------------|
| 받는 대미지 +10%/회      | `CombatStats.revival_penalty` → `command_calculator._process_damage()`가 `m_res` 바로 옆에서 `received_modifiers`에 합류 |
| 턴당 코스트 +1 (4회 이상)  | `CombatStats.__init__`이 `_max_cost`에 한 번 반영 (`on_start_round()`가 매 라운드 이 값으로 회복) |
| 이동 코스트 +1 (4회 이상)  | `extensions.get_total_cost()`가 이동 파트마다 `extra_move_cost`를 얹는다     |

### 운명간섭("+" 접미사)

> **플레이어에게 보이는 이름은 "키워드 보정"이다.** 코드/문서의 내부 명칭만
> `운명간섭`(`fate_*`)이고, 답글·계산식에 나가는 문구는 전부 "키워드 보정"으로
> 통일한다.

`parser.py`가 `[공격+/대상]`/`[스킬명+/대상]`을 `CommandPart.fate_boost=True`로
파싱하고, 비전투 판정은 `bot/commands/noncombat.py`의 `parse_roll_command()`가
`[판정+/스탯]`을 따로 다룬다(전투 시스템에는 판정 커맨드가 없다).

- **보정치**: 기본 공격은 `FATE_INTERVENTION_ATTACK_BONUS`(15) 고정이고,
  스킬은 "스킬_캐릭터" 시트의 `fate_mode`가 정한다(아래 "스킬별 보정 모드").
  `command_calculator._apply_fate_boost_modifier()`가 계산기 생성 시점의
  대미지/회복에만 얹는다 — 이후 반격/반사가 만드는 파생 대미지는 시전자의
  선언 행동이 아니므로 대상이 아니다. 정수 보정은
  `IntValueModifier(applies_to_fixed=True)`라 배율보다 먼저 더해져 배율 보정을
  함께 받는다(스펙이 요구하는 "고정 대미지와 다른" 동작이 여기서 나온다).
- **사용 조건**: `command_processors._validate_fate_boost()`가 전개 전에
  검사하고, `fate_mode`를 비워 둔 스킬에 한해 "대미지 스킬인지"만 전개 후에
  확인한다(효과 구현체마다 달라 전개해 봐야 알 수 있다). 어느 쪽이든 실패하면
  체력도 코스트도 소모되지 않는다.
- **체력 20 소모**: `_apply_fate_intervention_cost()`가 대미지 파이프라인을
  타지 않고 HP를 직접 깎는다(반사/방어 버프가 개입하면 안 되므로). 대신 결과를
  `source_labels=("키워드 보정",)`인 대미지 로그 엔트리로 남겨, 답글 표시와
  `write_back_changed_hp()`의 시트 반영이 기존 경로를 그대로 타게 한다.
- **하루 1번 제한**: 일일 의뢰(`daily_quest_date`)와 같은 날짜 비교 방식이다.
  영속 상태는 시트의 `fate_date`이고, 라이브 상태
  (`CombatCharacter.fate_used`)는 배치 시점에
  `CombatCharacterDataFromSpreadsheet.has_used_fate_on(오늘)`으로 한 번
  확정한다 — 전투가 자정을 넘겨도 한 전투 안에서 판정 기준이 바뀌지 않는다.
  봇 계층(`bot/commands/character.py`의 `mark_fate_used_if_needed()`)이 커맨드
  처리 성공 후 시트에 오늘 날짜를 적는다. 하루에 전투가 두 번 이상 열리지
  않는다는 전제 덕에 리셋 절차 자체가 필요 없다는 것이 이 방식의 이점이다.
  **`fate_date` 컬럼은 반드시 테이블 컬럼 타입이 `TEXT`여야 한다** —
  "캐릭터" 시트는 Google Sheets 테이블이고, 컬럼 타입이 `DATE`면
  `valueInputOption`이 RAW든 USER_ENTERED든 상관없이 `"YYYY-MM-DD"`가 날짜
  시리얼(예: 46274)로 저장되어 이후 비교가 영원히 거짓이 된다(2026-09-09에
  실제로 이 상태로 배포돼 하루 1번 제한이 무력화된 적이 있다). RAW 기록은
  방어선이 아니다 — `daily_quest_date`가 무사한 진짜 이유도 그 컬럼 타입이
  `TEXT`이기 때문이다.
- **대련/상시전투 제외**: `BattlefieldContext.allow_fate_intervention`을
  `PracticeBattlefieldContext`가 `False`로 덮는다 — 체력 절반인 임시 캐릭터로
  진행하고 체력 변동을 시트에 반영하지 않아, 되돌릴 수 없는 자원 소비를 걸 수
  없기 때문이다(`allow_item_usage`와 같은 패턴). **결투는 예외로 허용된다** —
  대가를 임시 체력이 아니라 시트의 실제 체력에서 빼기 때문이다(아래 "결투"
  참고).

### 스킬별 보정 모드 (`fate_mode`)

스킬에 붙는 보정은 "스킬_캐릭터" 시트의 `fate_mode`/`fate_value`/
`fate_effect_index` 세 컬럼이 정한다(값 목록은
[SPREADSHEET_SCHEMA.md#fateboostmode](SPREADSHEET_SCHEMA.md#fateboostmode)).
**비워 두면 기존 동작 그대로**라 마이그레이션이 필요 없다 — 대미지가 나오는
스킬은 굴림 +10, 대미지가 없는 스킬은 "+"를 거부한다.

모드별로 반영 지점이 다르다. 대미지·회복은 계산 시점에 값이 만들어지지만,
버프 수치/스택은 부여 데이터를 만드는 전개 시점에만 손댈 수 있고, 대상 수는
전개 전 검증에서 풀어줘야 하기 때문이다.

| 모드 | 반영 지점 |
|---|---|
| `굴림 보정` / `수치 강화` | `command_calculator._apply_fate_boost_modifier()` |
| `버프 수치 강화` / `버프 스택 강화` | `command_expanders._apply_fate_buff_boost()` (`BuffAddData.value_override` / `stack_value`) |
| `대상 추가` | `command_processors.try_expansion_if_valid()`의 `target_count` 검증 |

`수치 강화`가 퍼센트 효과에 걸릴 때는 배율을 하나 더 곱하지 않고 **계수 자체에
%p를 더한다**(`_boost_coefficient()`) — 곱하면 시트에 적은 "+30%p"보다 강해진다.

조합상 동작할 수 없는 설정(입력을 받지 않는 `target_rule`에 `대상 추가` 등)은
`skill/models.py`의 `fate_config_error()`가 잡아 `[전투개시]` 시점에 admin
DM으로 경고한다. 전투를 세우지는 않는다 — 잘못 설정된 스킬도 보정만 빠질 뿐
정상 동작하므로, 전투 전체를 막는 편이 손해가 크다.

---

## 대련 · 결투 · 상시전투 (`PracticeBattleMode`)

셋 다 `PracticeRoundManager`의 선공/후공 2페이즈 구조를 공유하고,
`PracticeBattleMode`(`battle/practice/define.py`)로만 갈린다. 이 enum 하나가
컨텍스트(`PracticeBattlefieldContext.mode`)와 봇 세션
(`PracticeBattleState.mode`), "필드" 시트의 `battle_type`(`FieldBattleType`)을
함께 정한다.

| | 대련 | 결투 | 상시전투 |
|---|---|---|---|
| 임시 체력 | `max_hp // 2` | `max_hp` | `max_hp // 2` |
| 라운드 상한 | `max(3, 인원+1)` | 없음(`round_limit=None`) | `max(3, 인원+1)` |
| 0 체력 자동 탈락 | 없음(`is_duel`) | 없음(`is_duel`) | 적군만 |
| 아이템 | ✗ | ✗ | ✗ |
| 키워드 보정 | ✗ | ✓ (실제 체력 소모) | ✗ |
| 패배 대가 | 없음 | 실제 체력 −20 | 없음 |

### 실제 체력(시트 체력)과 임시 체력

결투만 두 체력을 동시에 들고 있다 — 전장의 `status.curr_hp`(임시)와
`PracticeBattlefieldContext.persistent_hp`("캐릭터" 시트 값). 후자는 배치
시점에 시트에서 읽어 채우고, 자진 기권으로 필드에서 빠져도 지우지 않는다
(패배 대가가 기권자에게도 적용되므로).

- **키워드 보정 대가**: `BattlefieldContext.fate_cost_hp()` /
  `pay_fate_cost_hp()`를 결투 컨텍스트가 덮어 실제 체력에서 뺀다. 시트 반영은
  봇 계층(`main.py`의 `_apply_duel_fate_cost()`)이 커맨드 처리 성공 후에 한다.
- **패배 대가**: `main.py`의 `_apply_duel_defeat_penalty()`가 전투 종료 시점에
  `log_sheets.apply_persistent_hp_delta()`로 시트를 다시 읽어 깎는다. 라이브
  값이 아니라 시트를 다시 읽는 이유는, 전투가 길어지는 동안 GM이 고친 체력을
  덮어쓰지 않기 위해서다. 대상은 현재 필드가 아니라
  `PracticeBattleState.roster_by_side`(시작 시점 명부)다.
- **표시**: 두 체력이 한 답글에 섞이므로, 실제 체력이 바뀐 로그 엔트리는
  `BattleLogEntry.hp_is_persistent=True`로 만들어 체력 뒤에 `※`가 붙고 그
  블록 마지막 줄에 `※ 실제 체력` 각주가 따라붙는다. 이 엔트리는 같은 대상의
  임시 체력 대미지와 합산되지 않는다(`merge_damage_heal_lines`).

---

## 주요 불변식

- `CommandPart`, `CommandPartData`, `SkillData`, `BuffData` 등 핵심 데이터 클래스는 `frozen=True`.
- `BattlefieldContext.characters`에서 제거된 캐릭터는 사망 처리된 것이다 (`remove_character()`).
  라운드 종료 시 자동 제거(`_remove_eliminated_characters()`)는 **적군에만** 적용된다 —
  아군은 체력이 0이 되어도 자동으로 제거되지 않고, admin이 `[탈락/이름]`
  (`force_remove_character()`)으로 명시적으로 제거해야 필드에서 사라진다.
  다만 체력이 0 이하인 캐릭터는 진영과 무관하게 **커맨드를 선언할 수 없다**
  (`try_expansion_if_valid()`). 막는 건 행동 주체뿐이고, 대상으로 지정되는
  것은 그대로 허용된다 — 필드에 남아 계속 피격되는 기존 설계가 유지되어야 한다.
- `try_expansion_if_valid()`에서 검증 실패 시 `CommandValidationError`를 raise하며, 코스트 차감은 검증 통과 후에만 수행한다.
- 스킬 효과 하나당 `CommandPartData` 하나가 생성된다. 즉 `parts_list`의 길이 ≥ 커맨드 파트 수.

---

## 실제 캠페인 데이터(고유명사) 노출 금지

**이 리포지터리는 public이고, 캠페인 데이터는 실제 플레이어들의 캐릭터다.**
검색 엔진·GitHub 코드 검색·`git blame`/`git log` 등으로 누구나 실제 캐릭터를
특정할 수 있는 형태로 노출되면 안 된다. 이 규칙은 **테스트 코드에만 적용되는
게 아니다** — 소스 코드 주석, 커밋 메시지, PR/브랜치 설명, 문서(`README.md`
등) 등 **커밋되거나 GitHub에 올라가는 모든 텍스트**에 동일하게 적용된다.
"테스트니까/주석이니까 실제 실행에 영향 없다"는 이유로 예외를 두지 않는다 —
검색 가능성이 문제이지 실행 여부가 문제가 아니다.

실제 캠페인의 캐릭터 이름·스킬명·패시브명 등 고유명사를 문자열 그대로
코드·주석·커밋 메시지·PR 설명에 박아넣지 않는다.

- **캐릭터 이름**: 일반화된 placeholder(예: `Catastrophe`)를 쓴다.
- **스킬/패시브 id**: 기능을 드러내는 일반 이름(예: `Cost2Skill`, `Cost3Skill`,
  `PassiveSkill`, `PassiveBuff`, `스킬_1`)으로 대체한다. 스킬 설명
  (`description`) 등 메커니즘을 서술하는 텍스트는 그대로 유지해도 된다 —
  문제는 실제 캐릭터를 특정할 수 있는 고유명사이지, 한글 텍스트 자체가 아니다.
- **예시가 필요한 코드 주석**(정규식 문자 집합 설명 등)도 마찬가지다. "실제
  스프레드시트에 이런 사례가 있어서"라는 이유로 실제 캐릭터/스킬명을 예시로
  드는 대신, 지어낸 일반 이름(`스킬_1`, `대상_1` 등)을 쓴다.
- 버프처럼 여러 캐릭터가 공유하는 범용 게임 시스템 명칭(`재앙`/`BuffCatastrophe`,
  `도발`/`BuffTaunt` 등)은 특정 캐릭터를 특정하지 않으므로 예외로 둔다.
- **커밋하기 전에** diff와 커밋 메시지 초안에 실제 고유명사가 없는지 스스로
  확인한다 — 실수로 들어간 뒤 발견하는 것보다 애초에 안 넣는 편이 훨씬 싸다.

### 이미 커밋된 실제 데이터를 발견했을 때

히스토리에 흔적이 남지 않도록 스크럽한 뒤 force-push한다.

- GPG 서명된 병합 커밋이 히스토리에 있으면 `git filter-repo`(심지어
  `--refs`로 범위를 좁혀도)가 그 서명을 벗겨내며 이후 모든 커밋의 해시가
  cascade로 바뀌어 공유 히스토리가 깨진다 — 대신 안전한 공유 지점(다른
  브랜치와의 병합 베이스)에서 `git cherry-pick`으로 커밋을 그대로 재현한 뒤,
  노출된 커밋만 `git commit --amend`로 내용/메시지를 고쳐 안전하게 스크럽한다.
- 노출된 커밋이 이미 `main`에 병합되어 있다면(즉 노출 지점이 정확히 `main`의
  현재 tip이거나 그 조상이라면), 그 커밋의 자식 커밋 없이(cascade 없이)
  `main` 자체도 같은 방식으로 재작성 대상이 될 수 있다 — 다만 `main`은
  공유 브랜치이므로 **재작성 여부와 범위를 반드시 사용자와 먼저 상의하고
  승인을 받은 뒤에만 진행한다.** GitHub 저장소 규칙(ruleset)이 `main`
  force-push를 막아 놓았을 수 있으니, 막혀 있다면 저장소 관리자(사용자)에게
  일시적으로 규칙을 완화하거나 우회(bypass) 권한을 부여해달라고 요청한다.
  스크럽 대상 커밋을 참조하는 다른 브랜치(오래된/닫힌 PR 브랜치 포함)가
  있다면 함께 찾아 동일하게 재작성하고, 그 시점에 열려 있는 PR 브랜치도
  새 `main` 기준으로 rebase해 force-push한다.
- 재작성 후에도 예전 커밋 해시를 아는 사람은 일정 기간(GitHub 기준 최대
  약 90일) 동안 `git fetch <sha>`로 dangling 커밋에 접근할 수 있다는 점을
  사용자에게 알린다 — 브랜치·PR·검색으로는 더 이상 노출되지 않지만 완전한
  즉시 삭제는 아니다.

---

## 환경 변수

→ [README.md#실행](README.md#실행) 참조.

## 스프레드시트 스키마

"버프"/"버프_패시브"/"스킬_캐릭터"/"스킬_에너미"/"스킬_패시브" 시트의 컬럼
스키마, `condition`/`effect_N`에 넣는 클래스 이름, 관련 enum 값 목록은
→ [SPREADSHEET_SCHEMA.md](SPREADSHEET_SCHEMA.md) 참조.

---

## 새 버프/스킬 효과 추가 방법

### 버프 추가

1. `app/battle/objects/buff/buffs/` 에 `BuffBase` 상속 클래스 작성
2. `timing`, `create_event()` 구현. 대상 교체가 필요하면 `get_target_override()` 재정의.
3. `app/battle/objects/buff/buffs/__init__.py`에 export 추가
4. 스프레드시트 "버프" 시트에 `buff_name` 컬럼(데이터클래스 필드명은 `buff_class_name`)에 클래스 이름 등록

같은 부여자가 같은 대상에게 값(예: 열 번호)만 다르게 여러 번 부여했을 때 하나로
병합되지 않고 동시에 여러 개 유지돼야 하는 버프(`BuffIgnite` 등)는
`PARTITION_UID_BY_VALUE: ClassVar[bool] = True`를 오버라이드한다. 기본값
`False`는 기존처럼 (given_by, applied_to, buff_class_name) 기준으로만
재부여를 판정한다(값이 달라도 지속시간만 갱신하고 값을 덮어씀).

### 스킬 효과 추가

1. `app/battle/objects/skill/effects/` 에 `SkillEffectBase` 상속 클래스 작성
2. `_expand()` 구현 (반환: `move_list, damage_list, heal_list, buff_add_list, buff_remove_list`)
3. `app/battle/objects/skill/effects/__init__.py`에 export 추가
4. 스프레드시트 "스킬_캐릭터"/"스킬_에너미" 시트에 `effect_N` 컬럼에 클래스 이름 등록

### 패시브 스킬 추가

1. 새 로직이 필요하면 위 "버프 추가"/"스킬 효과 추가" 순서로 `BuffBase`
   또는 `SkillEffectBase` 구현체를 먼저 만든다. 기존 스킬 효과를 그대로
   재사용할 수 있으면 이 단계는 생략한다.
2. 버프 이벤트를 재사용하려면(버프 모디파이어 경로) "버프_패시브" 시트의
   `buff_name` 컬럼에 등록한다. 스킬 효과 경로를 쓰려면 이 단계는 생략한다.
3. "스킬_패시브" 시트에 `trigger`(`PassiveSkillTrigger`),
   `target_type`(`PassiveSkillTargetType`), (버프 모디파이어 경로라면)
   `buff_id`, (스킬 효과 경로라면) `effect_0`/`effect_1` 등을 등록한다.
4. 캐릭터/에너미 시트의 `passive_skill_id` 컬럼에 등록한 id를 채운다.

### 필드 효과 추가

1. 새 효과 구현체가 필요하면 위 "스킬 효과 추가" 순서로 만들되,
   **`requires_holder_character: ClassVar[bool] = False`를 반드시 켠다** —
   기본값은 "시전자 필요"라 켜지 않으면 필드 효과에서 거부된다. 시전자의
   스탯·위치·진영을 읽는 효과라면 켜면 안 된다.
2. "스킬_패시브" 시트에 행을 추가하고 `target_type`을 필드 범위 값
   (`필드 아군 진영`/`필드 적군 진영`/`필드 전원`/`필드 사건 당사자`) 중
   하나로 채운다. 이 값이 그 행을 필드 효과로 만든다.
3. 거는 방법을 정한다: admin 전용이면 여기까지, 스킬로 걸면 스킬 시트의
   `field_effect_id_N`에, 부적으로 걸면 "아이템" 시트의 `passive_skill_id`에
   이 id를 채운다.

설정이 어긋나면 `[전투개시]` 시점에 admin DM으로 경고가 간다 — 전투를
세우지는 않으므로 경고를 놓치면 그 효과만 조용히 빠진다.
