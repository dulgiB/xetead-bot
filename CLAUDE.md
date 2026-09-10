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
      commands/
        define.py               # RoundPhaseType enum
        models.py               # CharacterCommand, CommandPart, CommandPartData, DamageCalculateData 등
        parser.py               # 문자열 → CharacterCommand 파싱
        admin.py                 # AdminCommand 계열 (강제 이동/대미지/힐/버프 부여·제거)
    exceptions.py                # CommandValidationError, 검증 실패 메시지 생성 함수들
    logger.py                    # Logger, CommandResult (콘솔 디버그 로그)
    practice/                    # 대련/상시전투 전용 축소 라운드 관리
      context.py                 # PracticeBattlefieldContext
      define.py                  # SideType, PracticeRoundPhase
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
      item/
        models.py                # Item, ItemData (소비형 아이템 슬롯)
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
      admin.py                  # Admin 커맨드 핸들러 (본 전투/DM 전투 공통)
      character.py              # 캐릭터 전투 커맨드 핸들러
      noncombat.py              # 비전투 커맨드 핸들러 (판정, 의뢰, 상시조사)
    session.py                  # BattleSession
    practice_state.py           # PracticeBattleState (대련/상시전투)
    dm_battle_state.py          # DmBattleState (DM 전투)
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
- **`BuffBase.get_target_override()`**: `None` 반환이 기본값. `None`이 아니면 `expand_character_command()`에서 대상을 교체한다 (도발 등).

대상 교체가 필요한 버프는 `get_target_override()`를 오버라이드하고, `ON_ACTION` 타이밍을 유지하면 버프 횟수 차감(`deduct_count`)이 자동으로 동작한다.

### 지속 시간

- `remaining_turns`: 라운드 종료 시 차감
- `remaining_count`: 공격 또는 피격 시 차감 (`BuffCountDeductCondition`)
- 둘 다 `None`이면 패시브 (영구)

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

"ATK 굴림/스택 수 × 계수%" 형태의 대미지 항목(반격, 스택 비례 대미지 등)을
새로 만들 때는 `damage_factory.make_coefficient_damage_calc()`를 쓴다.
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
| `SkillTargetRuleNamedWithColumn` | 캐릭터 1명 + 그 캐릭터에 인접한 열 1개(생략 가능) 동시 지정      | `False`                  |
| `SkillTargetRuleColumn`       | 열(column) 기준 광역, 항상 시전자의 `foe_faction`(적 진영)  | `False`                  |
| `SkillTargetRuleAllyColumn`   | 열 기준 광역, 항상 시전자와 같은 진영(아군)                  | `False`                  |
| `SkillTargetRuleColumnRange`  | 열 1개 지정 → ±2열(최대 5열) 광역, 항상 시전자의 `foe_faction`(적 진영) | `False`                  |
| `SkillTargetRuleAllAllies`    | 입력 무시, 시전자와 같은 진영 전원(시전자 자신·동료 제외)         | `True`                   |

`ignores_input_targets=True`인 규칙은 도발 등의 대상 오버라이드를 적용하지 않는다.
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

본 전투/DM 전투(`RoundPhaseType.ENEMY_PRE_ACTION`이 있는 두 경로)에서 에너미가
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

대련/상시전투(`PracticeRoundManager`)는 페이즈 구조가 달라 이 기능 대상이 아니다.

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
  `SELF_AND_SAME_COLUMN_ALLIES`/`ALL_ALLIES`/`ATTACKER_OR_TARGET`/
  `LOWEST_HP_ALLY`. `_resolve_targets()`가 실제 대상 목록으로 변환하며,
  동료(소환수, `context.companion_owners`)는 아군 범위 대상에서 제외된다.

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
  없기 때문이다(`allow_item_usage`와 같은 패턴).

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
