# CLAUDE.md

## 프로젝트 개요

TRPG 캠페인의 전투를 자동 정산하는 Discord 봇. 전투 로직(`app/battle/`)과 봇 인터페이스(`app/bots/discord_bot/`)가 분리되어 있다.

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
      command_process_helpers.py# 이동/대미지/힐/버프 개별 처리 + 버프 이벤트 적용
      buff_container.py         # 버프 생명주기 (추가/제거/라운드 훅)
      commands/
        define.py               # RoundPhaseType enum
        models.py               # CharacterCommand, CommandPart, CommandPartData 등
        parser.py               # 문자열 → CharacterCommand 파싱
    objects/
      buff/
        buff_base.py            # BuffBase, BuffDurationCounter, BuffAddData
        buff_events.py          # BuffEvent 추상 기반
        buffs/                  # 개별 버프 구현체
        models.py               # BuffData (스프레드시트 행 대응)
        conditions.py           # 버프 적용 조건
      skill/
        models.py               # SkillData, SkillEffectBase, Skill
        target_functions.py     # SkillTargetRule 구현체
        effects/                # 개별 스킬 효과 구현체
        define.py               # SkillValueType
      character/
        combat_character.py     # CombatCharacter
        combat_stats.py         # CombatStats
      models.py                 # CharacterId, DamageData, HealData, ValueWithModifiers 등
      define.py                 # 주요 enum (ActionType, BuffApplyTiming, CombatStatType 등)
  bots/discord_bot/             # Discord 슬래시 커맨드 봇
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

스프레드시트 "버프" 시트 → `BuffData.from_dict()` → `buff_class_name` 문자열로 `importlib` dispatch → `BuffBase` 구현체 인스턴스화.

### 타이밍

| `BuffApplyTiming` | 트리거                               |
|-------------------|-----------------------------------|
| `ON_ROUND_START`  | `buff_container.on_round_start()` |
| `ON_ACTION`       | `_apply_buff_events()` (공격/피격 시)  |
| `ON_ROUND_END`    | `buff_container.on_round_end()`   |

### 버프 이벤트 vs 대상 오버라이드

- **`BuffEvent.apply()`**: `CommandPartCalculator`를 받아 대미지/힐 수치를 변경하는 계산 시점 훅.
- **`BuffBase.get_target_override()`**: `None` 반환이 기본값. `None`이 아니면 `expand_character_command()`에서 대상을 교체한다 (도발 등).

대상 교체가 필요한 버프는 `get_target_override()`를 오버라이드하고, `ON_ACTION` 타이밍을 유지하면 버프 횟수 차감(`deduct_count`)이 자동으로 동작한다.

### 지속 시간

- `remaining_turns`: 라운드 종료 시 차감
- `remaining_count`: 공격 또는 피격 시 차감 (`BuffCountDeductCondition`)
- 둘 다 `None`이면 패시브 (영구)

---

## 스킬 시스템

### 데이터 흐름

스프레드시트 "스킬" 시트 → `SkillData.from_dict()` → `to_skill_instance()` → `Skill(target_rule, data)`.

### SkillTargetRule

| 구현체                     | 설명              | `ignores_input_targets` |
|-------------------------|-----------------|-------------------------|
| `SkillTargetRuleSelf`   | 시전자 자신 고정       | `True`                  |
| `SkillTargetRuleNamed`  | 이름 지정 대상        | `False`                 |
| `SkillTargetRuleColumn` | 열(column) 기준 광역 | `False`                 |

`ignores_input_targets=True`인 규칙은 도발 등의 대상 오버라이드를 적용하지 않는다.

### SkillEffect

`SkillEffectBase.expand(context, holder, targets) → (move_list, damage_list, heal_list, buff_add_list)`

스킬 하나에 effect 최대 3개까지 정의 가능 (`effect_0`, `effect_1`, `effect_2` 컬럼).

---

## 주요 불변식

- `CommandPart`, `CommandPartData`, `SkillData`, `BuffData` 등 핵심 데이터 클래스는 `frozen=True`.
- `BattlefieldContext.characters`에서 제거된 캐릭터는 사망 처리된 것이다 (`remove_character()`).
- `try_expansion_if_valid()`에서 검증 실패 시 `CommandValidationError`를 raise하며, 코스트 차감은 검증 통과 후에만 수행한다.
- 스킬 효과 하나당 `CommandPartData` 하나가 생성된다. 즉 `parts_list`의 길이 ≥ 커맨드 파트 수.

---

## 환경 변수

| 변수                               | 용도                |
|----------------------------------|-------------------|
| `DISCORD_BOT_TOKEN`              | Discord 봇 토큰      |
| `GOOGLE_SPREADSHEET_CREDENTIALS` | 서비스 계정 JSON (문자열) |
| `DB_SPREADSHEET_KEY`             | 스프레드시트 ID         |

---

## 새 버프/스킬 효과 추가 방법

### 버프 추가

1. `app/battle/objects/buff/buffs/` 에 `BuffBase` 상속 클래스 작성
2. `timing`, `create_event()` 구현. 대상 교체가 필요하면 `get_target_override()` 재정의.
3. `app/battle/objects/buff/buffs/__init__.py`에 export 추가
4. 스프레드시트 "버프" 시트에 `buff_class_name` 컬럼에 클래스 이름 등록

### 스킬 효과 추가

1. `app/battle/objects/skill/effects/` 에 `SkillEffectBase` 상속 클래스 작성
2. `expand()` 구현 (반환: `move_list, damage_list, heal_list, buff_add_list`)
3. `app/battle/objects/skill/effects/__init__.py`에 export 추가
4. 스프레드시트 "스킬" 시트에 `effect_N` 컬럼에 클래스 이름 등록
