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
  bot/                          # Mastodon 봇 인터페이스
    main.py                     # 봇 진입점 (MastodonBotListener)
    commands/
      admin.py                  # Admin 커맨드 핸들러
      character.py              # 캐릭터 전투 커맨드 핸들러
      noncombat.py              # 비전투 커맨드 핸들러 (판정, 의뢰, 상시조사)
    session.py                  # BattleSession
    practice_state.py           # PracticeBattleState (대련/상시전투)
    noncombat_state.py          # NonCombatState
    load_data.py                # 스프레드시트 데이터 로딩
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
