# 스프레드시트 스키마 참고

[README.md](README.md)에 문서화된 "캐릭터"/"에너미"/"아이템"/"인벤토리"/의뢰
시트와 달리, 지금까지 컬럼 단위로 문서화되지 않았던 "버프"/"버프_패시브"/
"스킬_캐릭터"/"스킬_에너미"/"스킬_패시브" 시트의 컬럼과, 이 시트들의 컬럼값에
들어가는 클래스 이름·enum 값 목록을 정리한다.

로딩 코드: `app/bot/load_data.py`. 모델 정의: `app/battle/objects/buff/models.py`
(`BuffData`/`PassiveBuffData`), `app/battle/objects/skill/models.py`
(`SkillData`/`SkillEffectBase`), `app/battle/objects/passive_skill/models.py`
(`PassiveSkillData`).

---

## 버프 시트 (`버프`)

`BuffData.from_dict()`가 읽는다. 실제 캐릭터에게 부여되는 일반 버프/디버프
전용이며, 아군·에너미 구분 없이 이 시트 하나를 함께 쓴다.

| 컬럼                                | 설명                                                                              |
|-----------------------------------|---------------------------------------------------------------------------------|
| `id`                               | 버프 id (고유)                                                                     |
| `buff_name`                        | **버프 클래스 이름** (`BuffBase` 구현체, [버프 클래스 참고](#버프-buffbase-클래스-참고)). 데이터클래스 필드명은 `buff_class_name`이지만 시트 컬럼명은 `buff_name`이다. |
| `duration_turn_value`              | 지속 턴 수. 비우면 `None`(턴 지속 없음)                                                     |
| `duration_count_value`             | 지속 횟수. 비우면 `None`(횟수 지속 없음)                                                     |
| `duration_count_deduct_condition`  | 횟수 차감 시점: `공격 시` / `피격 시` (`BuffCountDeductCondition`)                          |
| `value_type`                       | `정수` / `퍼센트`. **비우면 `value`는 무시되고 항상 0으로 처리된다** — 값이 필요 없는 순수 마커 버프는 비워둔다.       |
| `value`                            | 수치 (버프 클래스마다 의미가 다름 — 각 클래스 docstring 참고)                                       |
| `condition`                        | 적용 조건 클래스 이름 ([Condition 클래스 참고](#condition-클래스-참고)). 비우면 조건 없이 항상 적용            |
| `condition_value`                  | `condition`이 참조하는 정수값 (예: 퍼센트 임계값, 명수 등 — 조건 클래스마다 의미가 다름)                       |
| `is_debuff`                        | 디버프 여부 (boolean). `TargetHasDebuffCondition` 등에서 조회                             |
| `description`                     | 표시용 설명                                                                          |
| `max_stack`                        | 최대 적층 스택 수. 비우면 적층 불가(재부여 시 지속시간만 갱신, 스택은 그대로)                                 |
| `reference_buff_id`                | 다른 버프 id를 참조해야 하는 버프 전용 (스택 수 기반 대미지 등). 대부분의 버프에는 필요 없음                       |

지속시간(`duration_turn_value`/`duration_count_value`)을 둘 다 비우면 패시브
(영구) 버프가 된다.

## 버프_패시브 시트 (`버프_패시브`)

`PassiveBuffData.from_dict()`가 읽는다. "스킬_패시브" 시트가 기존 버프
이벤트를 재사용하는 "버프 모디파이어 경로" 전용의 축소판 — 지속시간/적층/
디버프 여부 개념이 없다(항상 켜져 있는 수정자로 취급).

| 컬럼                 | 설명                                                    |
|--------------------|-------------------------------------------------------|
| `id`                | 버프 모디파이어 id (고유)                                       |
| `buff_name`         | 버프 클래스 이름 (위 "버프" 시트와 동일한 `BuffBase` 구현체를 그대로 재사용)      |
| `value_type`        | `정수` / `퍼센트`                                          |
| `value`             | 수치                                                    |
| `condition`         | 적용 조건 클래스 이름 (선택)                                      |
| `condition_value`   | `condition`이 참조하는 정수값                                  |
| `description`       | 표시용 설명                                                 |
| `reference_buff_id` | 다른 버프 id 참조 (선택)                                       |

## 스킬_캐릭터 / 스킬_에너미 시트

`SkillData.from_dict()`가 읽는다. 두 시트는 같은 스키마를 공유하며,
"스킬_캐릭터"는 캐릭터의 `skill_1_id`~`skill_N_id`가, "스킬_에너미"는
에너미의 `skill_1_id`~`skill_N_id`가 참조한다. "스킬_에너미" 시트 자체가
없으면 봇은 경고만 남기고 에너미 스킬 없이 로드한다.

| 컬럼            | 설명                                                    |
|---------------|-------------------------------------------------------|
| `id`           | 스킬 id (고유)                                             |
| `target_rule`  | 대상 규칙 클래스명 ([README.md#스킬-대상-규칙](README.md#스킬-대상-규칙) 참조) |
| `target_count` | 지정 가능한 대상 수 상한                                         |
| `cost`         | 코스트                                                   |
| `description`  | 봇이 그대로 노출할 스킬 설명                                       |
| `effect_0`~`effect_2` (및 부속 컬럼) | 효과 최대 3개, [`effect_N` 컬럼 패턴](#effect_n-컬럼-패턴-스킬아이템-공용) 참조 |

## 스킬_패시브 시트 (`스킬_패시브`)

`PassiveSkillData.from_dict()`가 읽는다. 시트 자체가 없으면 봇은 경고만
남기고 패시브 스킬 없이 로드한다. 캐릭터/에너미 시트의 `passive_skill_id`
컬럼이 이 시트의 `id`를 참조한다.

| 컬럼                                 | 설명                                                                          |
|------------------------------------|-----------------------------------------------------------------------------|
| `id`                                | 패시브 스킬 id (고유)                                                              |
| `trigger`                           | 발동 시점 (`PassiveSkillTrigger`, [값 목록](#passiveskilltrigger))                 |
| `target_type`                       | 효과 대상 범위 (`PassiveSkillTargetType`, [값 목록](#passiveskilltargettype))       |
| `description`                       | 표시용 설명                                                                     |
| `buff_id`                           | (선택) "버프_패시브" 시트의 `id` — 버프 모디파이어 경로. `effect_0`/`effect_1`과 동시에 채울 수 있다 |
| `effect_0`~`effect_1` (및 부속 컬럼) | 효과 최대 2개(`MAX_PASSIVE_EFFECT_COUNT`), [`effect_N` 컬럼 패턴](#effect_n-컬럼-패턴-스킬아이템-공용) 참조 |

`buff_id`(버프 모디파이어 경로)와 `effect_N`(스킬 효과 경로)은 상호 배타적이지
않다 — 둘 다 채우면 서로 다른 `BuffApplyTiming`이 필요할 수 있어 내부적으로
역할별 버프 인스턴스 2개로 나뉘어 등록된다 (`PassiveSkillWrapperBuff.create()`,
[CLAUDE.md#패시브-스킬-시스템](CLAUDE.md#패시브-스킬-시스템) 참고).

---

## `effect_N` 컬럼 패턴 (스킬/아이템 공용)

"스킬_캐릭터"/"스킬_에너미"/"스킬_패시브"/"아이템" 네 시트 모두
`parse_skill_effect()`(`skill/models.py`)로 이 컬럼 묶음을 파싱한다. `N`은
효과 순번(스킬은 0~2, 패시브 스킬은 0~1, 아이템은 0 하나만).

| 컬럼                        | 설명                                                                          |
|---------------------------|-----------------------------------------------------------------------------|
| `effect_N`                 | 스킬 효과 클래스명 ([SkillEffectBase 클래스 참고](#skilleffectbase-클래스-참고))              |
| `value_source_N`           | 수치 산출 방식 (`ValueSourceType`, [값 목록](#valuesourcetype))                       |
| `value_N`                  | 수치 (계수/고정값 등, `value_source_N`과 조합해 해석)                                     |
| `value_type_N`              | `정수` / `퍼센트` / `버프` (`SkillValueType`)                                      |
| `buff_id_N` (스킬_캐릭터/스킬_패시브) 또는 `buff_name_N` (스킬_에너미) | 버프 부여 효과일 때 부여할 버프 id                              |
| `buff_add_timing_N`        | (선택) 에너미 스킬 전용, 버프가 언제 부여되는지 (`RoundPhaseType`, [값 목록](#roundphasetype)) |
| `target_override_N`        | (선택) 대상을 강제로 치환 — 현재 `자신`(`SkillTargetOverrideType.SELF`)만 지원               |
| `effect_apply_timing_N`     | (선택) 에너미 스킬 전용, 이 effect가 어느 페이즈에 적용되는지 (`RoundPhaseType`). 비우면 아군 스킬 동작(페이즈별 기본값) |
| `buff_stack_cap_N`          | (선택) 적층형 버프 부여/제거 시 한 번에 적용할 스택 상한                                        |
| `condition_N`               | (선택) 이 effect가 발동하는 조건 클래스명 ([Condition 클래스 참고](#condition-클래스-참고)). `ConsumedBuffStackCountCondition`은 예외적으로 지연 게이트(`gate_value_source`/`gate_value`)로 변환되어 커맨드 처리 중간값을 참조한다 |
| `condition_value_N`         | (선택) `condition_N`이 참조하는 정수값                                                |
| `reference_buff_id_N`       | (선택) 다른 버프 id를 참조해야 하는 효과 전용(예: holder가 보유한 다른 버프의 스택 수를 새 버프의 수치로 스냅샷). `BuffData.reference_buff_id`와 동일한 목적                |
| `required_target_buff_id_N` | (선택) 대상이 이미 보유하고 있어야 이 effect가 적용되는 버프 id(선행 디버프 존재를 요구하는 콤보용 게이트). `buff_id_N`(이 effect가 부여/조회하는 버프)과는 별개다 |

`effect_N` 컬럼이 비어 있으면 그 순번의 효과는 없는 것으로 처리된다(아이템은
`effect_0`이 비어 있으면 로드 자체가 실패한다).

---

## Condition 클래스 참고

`condition`/`condition_N` 컬럼에 넣는 클래스 이름 목록
(`app/battle/objects/buff/conditions.py`). `value`(스프레드시트의
`condition_value`)의 의미는 클래스마다 다르다.

| 클래스                                    | 참(True) 조건                                                          | `value` 의미        |
|----------------------------------------|------------------------------------------------------------------------|--------------------|
| `IsInSameColumnCondition`               | holder와 대상이 같은 열                                                    | (없음)              |
| `WasNotAttackedCondition`               | 직전 라운드에 holder가 공격받지 않음                                            | (없음)              |
| `SelfHpBelowCondition`                  | holder 체력 비율이 `value`% 미만                                           | 퍼센트 임계값          |
| `HolderHasBuffCondition`                | holder에게 패시브 아닌 버프가 1개 이상                                          | (없음)              |
| `TargetHasDebuffCondition`              | 대상에게 패시브 아닌 디버프가 1개 이상                                             | (없음)              |
| `AllyInSameColumnCondition`             | holder와 같은 열에 같은 진영(자신 제외)이 1명 이상                                  | (없음)              |
| `TargetAttackedHolderLastRoundCondition`| 직전 라운드에 대상이 holder를 공격함                                            | (없음)              |
| `HolderDidNotMoveThisTurnCondition`     | 이번 라운드 holder가 이동하지 않음                                              | (없음)              |
| `SameTargetAsLastRoundCondition`        | 직전 라운드에도 holder가 같은 대상을 공격함                                        | (없음)              |
| `HealedNonSelfCondition`                | holder가 자신 외 대상에게 회복을 부여하는 상황                                      | (없음)              |
| `EnemyInRangeCountCondition`            | holder 사거리 내 적 수가 `value`명 이상                                       | 명수                |
| `AllyInRangeCountCondition`             | holder 사거리 내 아군(자신 제외) 수가 `value`명 이상                              | 명수                |
| `TargetIsInRangeCondition`              | 대상이 holder 사거리 내                                                    | (없음)              |
| `HolderWasAttackedCondition`            | holder가 이번 라운드에 피격함                                                 | (없음)              |
| `AllyInSameColumnWasAttackedCondition`  | 같은 열·같은 진영(자신 포함) 중 이번 라운드 피격자가 1명 이상                              | (없음)              |
| `TargetIsAllyCondition`                 | 대상이 holder와 같은 진영                                                   | (없음)              |
| `AllyInRangeWasAttackedCondition`       | 사거리 내·같은 진영(자신 포함) 중 이번 라운드 피격자가 1명 이상                             | (없음)              |
| `OtherAllyInRangeWasAttackedCondition`  | 사거리 내·같은 진영(자신 제외) 중 이번 라운드 피격자가 1명 이상                             | (없음)              |

`ConsumedBuffStackCountCondition`은 이 표에 없다 — 스킬 효과의
`condition_N`에만 쓰는 특수 값으로, 일반 `Condition`이 아니라 파싱 시점에
지연 게이트(`gate_value_source`/`gate_value`)로 변환된다.

---

## 버프(`BuffBase`) 클래스 참고

전체 목록과 효과는 [README.md#구현된-버프-목록](README.md#구현된-버프-목록)
참고.

## SkillEffectBase 클래스 참고

`effect_N` 컬럼에 넣는 클래스 이름 목록 (`app/battle/objects/skill/effects/`).

| 클래스                                            | 효과                                                              |
|-------------------------------------------------|-------------------------------------------------------------------|
| `SkillEffectDamage`                              | 대미지                                                              |
| `SkillEffectDamageReverse`                       | 시전자의 공격 속성과 반대 속성으로 대미지                                         |
| `SkillEffectHeal`                                | 회복                                                                |
| `SkillEffectMove`                                | 이동                                                                |
| `SkillEffectAddBuff`                             | 대상에게 버프 부여                                                       |
| `SkillEffectAddBuffIfTargetHasReferencedBuff`    | 대상이 reference_buff_id 버프를 이미 보유하고 있을 때만 buff_id 버프 부여(선행 디버프 요구 콤보) |
| `SkillEffectAddBuffWithReferencedStackValue`     | holder의 reference_buff_id 버프 스택 수 × value%를 스냅샷한 수치로 buff_id 버프 부여. required_target_buff_id가 있으면 그 버프를 보유하고 아직 buff_id가 없는 대상에게만 |
| `SkillEffectRemoveDebuffs`                       | 대상의 패시브가 아닌 디버프를 전부 제거                                         |
| `SkillEffectAddBuffIfHolderHasFormationBuff`     | 시전자가 [Formation] 버프를 보유한 상태일 때만 대상에게 버프 부여                     |
| `SkillEffectShieldOrReflectIfTargetHasFormationBuff` | 대상이 [Formation] 보유 시 대체 버프(보통 [반사]), 아니면 기본 버프(보통 [방어막]) 부여 |
| `SkillEffectConsumeStackForDamage`               | 시전자 자신의 적층형 버프 스택을 소모하며 그 소모량 × value%만큼 대미지                  |
| `SkillEffectHealAndFillBuffStack`                | 적층형 버프의 여유 스택 수 × value%만큼 회복 + 시전자 스택을 즉시 최대치로 채움          |
| `SkillEffectDamageByDebuffStackTier`             | 대상의 적층형 디버프 스택 수(최대 5 기준 3단계)에 따라 대미지 계수/처리 방식이 갈림          |
| `SkillEffectDamageOrTauntIfCompanionAbsent`      | 동료 생존 시 대미지+버프(도발 등) 부여, 없으면 도발 없이 더 강한 고정 계수로 대미지          |
| `SkillEffectSpendCompanionHpOrSummon`            | 동료 생존 시 동료 체력을 소모(고정 대미지, 부족해도 0으로 clamp)하고 holder에게 버프 부여 |
| `SkillEffectSplashAlongPath`                     | 시전자의 원래 위치~주대상 위치 사이 전체 열(양 끝 포함)에 대미지, 주대상 본인은 제외          |
| `SkillEffectSummonCompanionAtBattleStart`        | 전투 시작 시 동료를 소환 (패시브 전용 효과)                                     |

---

## 관련 Enum 값 목록

### ValueSourceType

`value_source`/`value_source_N` 컬럼에 넣는 값 (`app/battle/objects/define.py`).

| 값                        | 의미                          |
|--------------------------|-----------------------------|
| `고정값`                    | 정해진 수치 그대로                   |
| `공격력`                    | 캐릭터의 공격력 스탯                  |
| `공격 굴림값`                 | `nd6(마일스톤N, 공격력)` 주사위 굴림 결과 |
| `사거리`                    | 캐릭터의 사거리 스탯                  |
| `최대 체력`                  | 캐릭터의 최대 체력 스탯                |
| `턴당 코스트`                 | 캐릭터의 턴당 코스트 스탯               |
| `자신의 현재 체력`              | 시전 시점 시전자의 현재 체력             |
| `자신의 현재 위치`              | 시전 시점 시전자의 열 위치              |
| `상대의 현재 체력`              | 시전 시점 대상의 현재 체력              |
| `상대의 현재 위치`              | 시전 시점 대상의 열 위치               |
| `해당 공격으로 입힌 대미지`         | 같은 커맨드에서 이 공격이 실제로 입힌 대미지    |
| `해당 행동으로 부여한 회복량`        | 같은 커맨드에서 이 행동이 실제로 부여한 회복량   |
| `해당 행동으로 소모한 버프 스택 수`     | 같은 커맨드에서 소모한 버프 스택 수 (스택 제거) |
| `해당 행동으로 증가한 버프 스택 수`     | 같은 커맨드에서 증가한 버프 스택 수         |
| `참조 버프의 현재 스택 수`         | `reference_buff_id`가 가리키는 버프의 현재 스택 수 (스택 소모 없음) |
| `공격자 방향으로`                | 이동 효과 전용 — 공격자 쪽으로 이동        |
| `공격자 반대 방향으로`             | 이동 효과 전용 — 공격자 반대쪽으로 이동      |
| `지정한 열`                  | 이동 효과 전용 — 입력으로 지정한 열로 이동    |

### SkillValueType / ValueType

`value_type`/`value_type_N` 컬럼: `정수` / `퍼센트` / `버프`(`SkillValueType`만
해당, 이동 효과 등에서 버프 대상 지정에 씀). 버프 시트의 `value_type`은
`ValueType`으로 `정수`/`퍼센트`만 지원한다.

### BuffCountDeductCondition

`duration_count_deduct_condition` 컬럼: `공격 시` / `피격 시`.

### SkillTargetOverrideType

`target_override_N` 컬럼: `자신`(`SELF`)만 지원.

### RoundPhaseType

`buff_add_timing_N`/`effect_apply_timing_N` 컬럼(에너미 스킬 전용):
`적 행동 선언` / `아군 행동` / `적 공격 정산` / `라운드 종료`.

### PassiveSkillTrigger

"스킬_패시브" 시트의 `trigger` 컬럼: `전투 시작` / `라운드 시작` / `라운드 종료`
/ `행동 시` / `적 이동 시` / `적 후행 시` / `아군 피격 시` /
`사거리 내 아군 피격 시`.

일반 버프의 `BuffApplyTiming`과 비슷하지만 완전히 같은 목록은 아니다 — 값
표기도 일부 다르고(예: `전투 시작` vs `전투 시작 시`), `사거리 내 아군 공격 시`
(`ALLY_IN_RANGE_ATTACKED`)는 패시브 스킬 트리거로 아직 제공되지 않는다.

### PassiveSkillTargetType

"스킬_패시브" 시트의 `target_type` 컬럼: `자신` / `같은 열 아군` /
`자신을 포함한 같은 열 아군` / `전체 아군` / `공격자 또는 대상` /
`체력 최저 아군`. 동료(소환수)는 아군 범위 대상에서 항상 제외된다.
