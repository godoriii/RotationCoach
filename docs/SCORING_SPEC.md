# SCORING_SPEC — GCD 단위 판정과 점수 명세

> 상태: 기획 초안 v0.1 (2026-10-16) · 대상: 한밤 생존 사냥꾼, 단일 대상, 무리의 지도자·파수꾼
> 기준 APL: simc `midnight` `ActionPriorityLists/default/hunter_survival.simc` @ `76f8118c` (2026-10-15) — 원문과 주문 데이터 출처는 [TECH_DECISIONS §3.1, 부록 B-10/B-11](TECH_DECISIONS.md#31-현재-한밤-생존-apl의-특징-확인-b-10-b-11)
> D-10~D-13은 2026-10-16 승인됨. 이 문서의 수치(반응 시간, 가중치, 동률 그룹, 경미 쌍)는 **승인된 초기값**이며 [SPIKES S9](SPIKES.md#s9-판정-규칙-보정-수동-라벨) 수동 라벨 비교로 조정한다.

## 1. 기본 개념

### 1.1 채점 대상 행동

현재 APL 기준 단일 대상 목록(`plst`, `sentst`)의 GCD 행동만 판정한다.

| action key | 주문 ID | 비고 (simc 데이터 12.1.5) |
|---|---|---|
| `kill_command` | 259489 | 2 충전, 충전 5 s (가속 영향), 집중 +15, Tip of the Spear +1 |
| `raptor_strike` | 186270 (원거리판 265189) | 집중 30. `Raptor Swipe!` 버프(1273155)가 있으면 Raptor Swipe(1262293)로 바뀜 → 같은 행동으로 취급 |
| `wildfire_bomb` | 259495 | 집중 10, 18 s (가속 영향), 1 충전 (Guerrilla Tactics로 2) |
| `takedown` | 1250646 | 90 s (Savagery −15 s), 자기 버프 8 s, 집중 +50 |
| `boomstick` | 1261193 | 60 s, 3 s 정신 집중, 데이터상 50 집중 자원 항목 (비용 여부 S2 확인) |
| `moonlight_chakram` | 1264949 | 파수꾼. Takedown 후 15 s 동안 Takedown 자리를 대체 (창 버프 1264946) |

- 쿨다운 가속 영향: Kill Command·Wildfire Bomb은 사냥꾼 패시브(137014)의 "Hasted Cooldown Duration" 대상이다 [확인 B-11].
- 판정에서 빼는 행동: 장신구(`use_item(s)`), 종족 특성, 물약, `invoke_external_buff`, `muzzle`, `aspect_of_the_eagle`, `retarget`, `auto_attack`, 펫 소환. 이들은 [§3.6](#36-gcd-없는-스킬off-gcd)과 보조 지표로만 다룬다.

### 1.2 결정 지점(DP)

- **t_ready**: 플레이어가 다음 GCD 스킬을 쓸 수 있게 된 시각 = max(직전 GCD 시작 + GCD 길이, 직전 시전·정신 집중 종료).
- **t_action**: 실제 다음 GCD 스킬 시전 시각. 없으면 공백 DP.
- **GCD 길이**: 기본 1.5 s를 가속으로 나눈 값으로 추정한다 (하한 0.75 s로 가정 [미확인]). 가속은 `COMBATANT_INFO` 수치 + 관측된 가속 오라 + 연속 시전 간격의 하한선으로 추정한다.
- **결정 창(decision window)**: `[t_ready − Q, min(t_action, t_ready + R)]`
  - `Q` = 주문 대기열 창(Spell Queue Window). 기본 400 ms (게임 기본값으로 알려짐 [미확인]), 설정에서 사용자 값으로 변경.
  - `R` = 반응 허용 시간. 기본 300 ms.

## 2. 판정 분류

| 판정 | 조건 | 점수 반영 (credit) |
|---|---|---|
| **MATCH** 일치 | 실제 행동이 결정 창 안 어느 시점의 APL top(점 추정 상태 기준)과 같음 | 1.0 |
| **ACCEPTABLE** 허용 | 실제 행동이 동률 그룹(§3.2)에 속하거나, 공정성 허용(반응 시간·경계값·사거리)으로 생긴 후보에 들어감 (§6.3) | 1.0 |
| **MINOR** 경미 | `weights.yaml`의 "경미 쌍"에 해당 (예: 손실이 작은 순서 바꿈) | 0.5 |
| **MISTAKE** 실수 | 위 어디에도 해당 안 되는 다른 GCD 행동 | 0.0 |
| **IDLE** 공백 | 결정 창 안에 GCD 행동이 없고 제외 사유도 없음 | 0.0 (공백 길이에 비례해 가중, §4.2) |
| **EXCLUDED** 제외 | 이동·사거리·대상 없음·사망·다중 대상 구간 등 (§3.3–3.5) | 점수에서 제외 |
| **INDETERMINATE** 불확정 | 엔진의 상태 추정 오차(모델 불확실성) 때문에 실제 행동이 정답인지 가릴 수 없음 (§6.3) | 점수에서 제외, 개수만 보고 |

판정 순서: EXCLUDED 검사 → 행동 존재 여부(IDLE) → MATCH → ACCEPTABLE → INDETERMINATE → MINOR → MISTAKE.

## 3. GCD 단위 판정 규칙

### 3.1 반응 시간과 정보 시점

플레이어에게 "알 수 없었던 정보"로 책임을 묻지 않는 것이 원칙이다.

1. **예측 가능한 변화**(쿨다운이 돌아옴, 충전 회복, 집중 재생, 버프 만료)는 플레이어가 미리 알 수 있다 → t_ready 시점 상태로 평가한다.
2. **예측 불가능한 변화**(확률 발동 오라: `Raptor Swipe!`, `Sentinel's Mark`, `Wallop`, `Wildfire Imbuement` 등. `spells.yaml`에서 `predictable: false`)는 발생 후 `R` 이전에는 반응할 수 없다 → 결정 창 시작 기준으로 `R` 이내에 생긴 이런 변화는 **"생겼다/안 생겼다 둘 다 가능"(불확실 값)**으로 넣어 평가한다. 결과적으로 반응 못 한 경우도, 바로 반응한 경우도 허용된다.
3. **주문 대기열**: 플레이어는 GCD가 끝나기 최대 `Q` 전에 다음 스킬을 미리 누를 수 있다. 그래서 결정 창은 t_ready보다 `Q`만큼 앞에서 시작하고, 그 사이 어느 시점의 top과 같으면 MATCH로 본다.
4. **늦은 시전**: t_action이 t_ready + R보다 늦으면 결정 창은 t_ready + R에서 끝난다 (늦게 눌러 생긴 유리한 상태로 정답을 맞추는 것을 막기 위함). 늦음 자체는 공백 시간(§4.2)으로 따로 반영한다.

### 3.2 우선순위가 사실상 동률인 경우

| 유형 | 규칙 | 예 |
|---|---|---|
| **경계값 허용** | 시간 단위 비교(`remains`, `full_recharge_time`, `cooldown.X.remains < gcd` 등)에서 양쪽 값 차이가 `δ`(기본 150 ms) 이내면 그 비교를 불확실 값으로 처리 | `wildfire_bomb,if=full_recharge_time<4+gcd`에서 4.05 s vs 4.0+GCD |
| **명시적 동률 그룹** | `tie_groups.yaml`에 정의한 집합. 같은 그룹이면 ACCEPTABLE | 초기 후보(사용자 검토 필요): ① 파수꾼 `sentst`에서 Tip of the Spear가 있을 때 `boomstick` ↔ `wildfire_bomb`(Sentinel's Mark 있음) ② `raptor_strike` ↔ `raptor_swipe`(동일 행동, 그룹이 아니라 별칭으로 처리) |
| **같은 줄 다른 대상** | `target_if` 줄은 단일 대상 MVP에서 현재 목표로 축약 | — |
| **곧 준비되는 상위 행동** | top보다 높은 줄의 행동이 `R` 안에 준비되는 경우, 그 행동을 기다린 짧은 공백(≤ R)과 지금 쓸 수 있는 행동 모두 허용 | Kill Command 충전이 0.2 s 뒤 돌아올 때 |

동률 그룹은 "SimC에서도 DPS 차이가 거의 없음"을 근거로만 추가한다. 근거(시뮬 결과 또는 이론 설명)를 `tie_groups.yaml` 주석에 남긴다.

### 3.3 이동 구간

- 위치는 고급 블록의 X/Y로 얻는다. 플레이어 위치는 플레이어 자신이 시전자인 `SPELL_CAST_SUCCESS`에서, 목표 위치는 플레이어가 목표에게 준 피해 이벤트(고급 블록 = 대상)에서 관측한다 [2차, S2에서 확인].
- **사거리 판단**: 근접 행동(`raptor_strike`, `takedown`)은 목표와의 거리가 `melee_range`(기본 5 yd) + 목표 몸집 반경 안일 때만 사용 가능하다. 몸집 반경은 로그에 없으므로 `[0, 5] yd` 구간 값으로 둬서 애매한 거리는 불확실 처리한다. `Aspect of the Eagle` 버프가 있으면 Raptor Strike 원거리판을 사용 가능으로 본다.
- 원거리 행동(`kill_command`는 펫 명령, `wildfire_bomb`)은 이동·원거리 중에도 사용 가능하다.
- **판정**:
  - 사거리 밖이면 근접 행동을 후보에서 빼고 APL을 다시 평가한다. 남은 후보 중 하나를 쓰면 정상 판정한다.
  - 쓸 수 있는 후보가 하나도 없으면(예: Kill Command·Wildfire Bomb 모두 쿨) 그 DP는 **EXCLUDED(`moving`/`out_of_range`)**.
  - 쓸 수 있는 원거리 행동이 있는데 아무것도 안 했으면 IDLE이다. 이동 중에도 할 수 있는 것을 놓친 것이기 때문이다. 다만 설정 `moving_idle_policy`로 "이동 중 공백은 EXCLUDED"를 고를 수 있다.
- `Boomstick`(정신 집중)이 이동으로 끊기는지는 S2에서 확인한다 [미확인].
- 이동 판정: 연속 두 위치 관측의 속도 > 2 yd/s 이면 이동 중으로 본다 (임계값은 S2 실측으로 조정).

### 3.4 대상 없음 구간

다음 중 하나면 그 구간의 DP는 **EXCLUDED(`no_target`)**:

1. 플레이어의 주 목표가 죽었고(`UNIT_DIED`) 다른 적대 유닛에 대한 플레이어의 공격이 아직 없음
2. 모든 아군의 적대 대상 피해가 `no_damage_gap`(기본 2.5 s) 이상 끊김 (보스 이탈·무적·단계 전환)
3. 레이드 단계 전환으로 알려진 구간 (WCL `phases` 또는 사용자 지정 보스 데이터, M7 이후)
4. 허수아비: 마지막 공격 후 `idle_gap`(5 s) 경과 → 풀 종료

### 3.5 사망, 군중 제어, 다중 대상

| 상황 | 탐지 | 처리 |
|---|---|---|
| 플레이어 사망 | `UNIT_DIED` (dest = 플레이어) ~ 부활 | EXCLUDED(`dead`) |
| 기절 등 행동 불가 | `SPELL_CAST_FAILED` 사유 문자열(기절·침묵 계열) 또는 플레이어에게 걸린 알려진 군중 제어 디버프 목록 | EXCLUDED(`cc`) |
| 다중 대상 | 최근 3 s 안에 플레이어가 피해를 준 서로 다른 적대 유닛 수(`active_enemies`)가 2 이상 | **MVP에서는 EXCLUDED(`multi_target`)**. APL은 `active_enemies<3`이면 단일 대상 목록을 쓰지만, 2마리 구간의 판정 정확도를 S9 전에는 믿기 어려움. M7에서 2마리 구간부터 포함 |

### 3.6 GCD 없는 스킬(off-GCD)

- `muzzle`, 종족 특성, 장신구, 물약, `aspect_of_the_eagle` 등은 DP를 만들지 않는다.
- 판정에 영향 없음. 단, 이들 때문에 GCD 행동이 늦어지면 그 늦음은 공백 시간으로 잡힌다 (의도된 비용).
- 보조 지표: 장신구·물약 사용 횟수와 Takedown 버프와 겹친 비율 (점수에는 넣지 않음).

### 3.7 주요 쿨다운 보류 접기 (held-cooldown collapse)

Takedown·Boomstick이 준비됐는데 플레이어가 일부러 아끼면(다음 단계 쫄 대비 등), APL은 매 GCD마다 그 스킬을 top으로 내놓는다. 이걸 GCD마다 MISTAKE로 세면 결정 하나가 수십 개의 실수로 부풀려진다.

규칙:
1. 같은 주요 쿨다운이 연속 DP에서 top인데 쓰지 않으면, 그 구간을 **보류 구간** 하나로 묶는다.
2. 보류 구간 안의 DP는 그 쿨다운을 **사용 불가로 가정하고** APL을 다시 평가해 나머지 로테이션을 정상 판정한다.
3. 보류 구간 전체에 **쿨다운 지연 판정 1건**을 추가한다. 가중치는 지연 시간에 비례하고 상한이 있다 (§4.2). 지연 판정은 `CdDelay` 레코드로 남는다 (`delay_s`, `lost_uses_estimate`).
4. 보류 끝에 실제로 사용했는지, 쿨다운 1회분을 통째로 잃었는지는 쿨다운 효율 지표(§5)에 따로 반영된다.

### 3.8 풀 시작과 끝

- **시작(오프너)**: 첫 DP는 플레이어가 적대 대상에 처음 GCD 행동을 한 시점이다. APL의 `precombat`에 `wildfire_bomb,if=active_enemies=1`이 있으므로 풀 직전·직후 첫 Wildfire Bomb은 MATCH로 본다. 첫 DP의 반응 허용 `R`은 오프너 대기 때문에 기본 1.0 s로 넓힌다.
- **끝**: 보스 사망·`ENCOUNTER_END` 이후 DP는 판정하지 않는다. `fight_remains` 조건을 쓰는 줄은 현재 `cds` 목록뿐이라 MVP 판정에 영향 없음.

### 3.9 영웅 특성별 특이사항

| 영웅 특성 | APL 목록 | 판정상 주의 |
|---|---|---|
| 무리의 지도자 | `plst` | `howl_summon.ready`(Wyvern/Boar/Bear 준비 버프 471878/472324/472325 중 하나) 상태에서 Tip of the Spear < 2면 Kill Command가 최우선. 준비 버프가 로그 오라로 보이는지 S2에서 확인. 보이지 않으면 30 s 주기 타이머(Kill Command −1.5 s, Raptor Strike −1.0 s 단축)로 추론하고 불확실 값 처리 |
| 파수꾼 | `sentst` | `debuff.sentinels_mark.remains`(1253601) 조건으로 Wildfire Bomb 우선. 마크는 확률 발동이므로 §3.1 규칙 2 적용. Takedown 후 15 s 동안 Moonlight Chakram 대체 |

## 4. 점수 산식

### 4.1 풀 점수

판정 가능한 DP 집합(MATCH, ACCEPTABLE, MINOR, MISTAKE, IDLE)과 쿨다운 지연 판정을 합쳐 가중 평균한다.

```
Score = 100 × ( Σ w_i · c_i ) / ( Σ w_i )
```

- `c_i`: [§2](#2-판정-분류)의 credit (MATCH·ACCEPTABLE 1.0, MINOR 0.5, MISTAKE·IDLE 0.0, CdDelay 0.0)
- `w_i`: 판정 가중치 ([§4.2](#42-가중치-초기값))
- EXCLUDED, INDETERMINATE는 분모·분자 모두에서 빠진다.
- **표시 조건**: 판정 가능한 DP가 20개 미만이면 점수 대신 "표본 부족"을 표시한다.
- **신뢰도 표시**: `불확정 비율 = INDETERMINATE / (판정 가능 + INDETERMINATE)`. 10%를 넘으면 점수 옆에 "신뢰도 낮음" 표시.

### 4.2 가중치 초기값

가중치는 **APL이 기대한 행동(expected)** 기준으로 매긴다. 중요한 행동을 놓친 것이 더 큰 손실이기 때문이다.

| 기대 행동 | w |
|---|---|
| `takedown`, `boomstick`, `moonlight_chakram` | 2.0 |
| `kill_command` (충전 2/2 상태, 넘침 직전) | 2.0 |
| `kill_command` (그 외), `wildfire_bomb` | 1.5 |
| `raptor_strike` | 1.0 |
| IDLE | 1.0 × (공백 길이 / GCD), 최대 3.0 |
| CdDelay (보류 구간) | 2.0 × min(지연 s / 10, 3) |

경미 쌍(MINOR) 초기 후보 — 사용자 검토 필요:
- 기대 `raptor_strike`, 실제 `kill_command` (충전 여유 있음, Tip of the Spear 3 미만): 손실 작음
- 기대 `wildfire_bomb`(조건 없는 마지막 줄), 실제 `raptor_strike`: 손실 작음

### 4.3 점수와 따로 보는 지표

점수 하나에 모든 걸 넣으면 원인을 알기 어려우므로, 아래는 점수에 넣지 않고 따로 계산한다. APL 해석 오류가 있어도 이 지표들은 독립적으로 맞다.

| 지표 | 정의 |
|---|---|
| APL 일치율 | (MATCH + ACCEPTABLE) / 판정 가능 DP (가중치 없음) |
| 활성 시간(ABC) | GCD 사용 시간 / 채점 대상 시간(EXCLUDED 제외) |
| 쿨다운 효율 | 주요 쿨다운별 실제 사용 횟수 / 이론 최대 횟수. 이론 최대 = 쿨다운 감소 효과를 반영해 "준비되자마자 썼다면" 쓸 수 있었던 횟수 |
| 쿨다운 평균 지연 | 준비된 뒤 실제 사용까지 평균 시간 |
| Kill Command 충전 넘침 | 충전 2/2 상태로 지난 시간 (충전 낭비 시간) |
| Wildfire Bomb 충전 넘침 | 같은 방식 |
| 집중 넘침 | 최대 집중 상태로 지난 시간 |
| Tip of the Spear 낭비 | 만료되어 사라진 중첩 수 + 3중첩에서 Kill Command로 더 쌓으려다 넘친 수 |
| 무리의 지도자 | Howl 준비 버프가 뜬 뒤 Kill Command로 소비하기까지 평균 지연 |
| 파수꾼 | Sentinel's Mark가 있는 동안 Wildfire Bomb 사용 비율 |
| Raptor Swipe! 지연 | 발동 후 소비까지 평균 시간 |

## 5. 오버레이 핵심 지표 후보

ToS 제약상 **평가 결과만** 표시한다. "다음 행동", "곧 준비될 쿨다운" 같은 정보는 표시하지 않는다.

### 5.1 풀 종료 직후 (주 모드)

| 우선순위 | 항목 | 형식 예 |
|---|---|---|
| 1 | 풀 점수 + 신뢰도 | `82.4` (신뢰도 낮음 표시 가능) |
| 2 | APL 일치율 | `86%` |
| 3 | 실수·공백·불확정 개수 | `실수 9 · 공백 4 · 불확정 3` |
| 4 | 주요 쿨다운 효율 | `Takedown 3/4 · Boomstick 5/6` |
| 5 | 낭비 지표 2개 | `KC 넘침 6.2s · Tip 낭비 4` |
| 6 | 상위 문제 패턴 3개 (엔진이 가중치 합으로 선정) | `Tip 0중첩에서 Raptor Strike 6회` |
| 7 | AI 빠른 요약 3–5줄 | Haiku 결과 |
| 8 | 지난 풀 대비 변화 | `점수 +3.1` |

### 5.2 전투 중 (선택 기능, 기본 꺼짐, 데이터가 도착할 때만)

점수, APL 일치율, 실수 개수만 표시한다. 개별 실수의 내용(무엇을 눌렀어야 했는지)은 전투 중에는 보여주지 않는다 (결정 D-4).

## 6. 로그로 추적이 불가능하거나 부정확한 요소

### 6.1 요소별 처리 방침

관측성: **O** 관측됨(로그에 직접 나옴) · **I** 추론 가능(다른 관측 이벤트로 계산) · **U** 불확정(구간 값) · **X** 알 수 없음.

| 요소 | 관측성 | 근거 | 처리 방침 |
|---|---|---|---|
| Kill Command 충전 수·회복 진행 | I | 충전 이벤트 없음. 한밤에서 무작위 초기화가 사라짐 (11.x에는 있었음) [확인 B-11] | 시전 기록 + 충전 5 s(가속 적용)로 계산. 모델상 0충전인데 시전이 관측되면 가속 추정을 보정하고 해당 구간을 U로 표시 |
| Wildfire Bomb 쿨다운·충전 | I (오차 누적) | 감소 효과가 많음: Wildfire Infusion(Kill Command마다 −1.0 s), Wildfire Shells(Boomstick 적중 시 −3.0 s), Grenade Juggler(8 s 동안 회복 +60%, 오라), Moon's Blessing(마크마다 −6 s), Pack Mentality(야수 소환 시 −6 s), Stalk and Strike(Chakram −10 s) [확인 B-11] | 각 효과를 관측 이벤트에 연결한 `cd_rules.py` 규칙으로 계산. 특성 보유 여부는 `COMBATANT_INFO` 또는 특성 프로필. 실제 시전으로 하한을 확인할 때마다 과거 구간을 좁힘 (§6.2) |
| Boomstick 쿨다운 | I | Lethal Calibration: Wildfire Bomb에 맞은 적마다 −2 s (최대 5) [확인 B-11]. Quick Reload 특성 | Wildfire Bomb 피해 이벤트의 서로 다른 대상 수로 계산 |
| Takedown 쿨다운 | I | 90 s, Savagery −15 s (특성) | 특성으로 고정 계산 |
| Howl of the Pack Leader 주기·준비 | O 또는 I | 준비 버프 3종과 주기 오라 471877이 오라로 기록되는지 [미확인] | 오라가 보이면 O. 안 보이면 30 s 주기 − 단축(Kill Command 1.5 s, Raptor Strike 1.0 s)으로 추론, 누적 오차는 U |
| 확률 발동 (Raptor Swipe!, Sentinel's Mark, Wallop, Wildfire Imbuement) | O (예상) | 모두 오라·디버프로 나타남 [확인 B-11, 로그 표시 여부는 S2] | 관측값 사용 + §3.1 반응 시간 규칙 |
| Tip of the Spear 중첩 | O | 오라 + 중첩 이벤트 | 관측값 사용. 숨은 "잠금" 버프(471536, 1280140)는 판정에 필요 없음 |
| 집중 | O (시점별) | 고급 블록 현재 값 | 관측 사이 구간은 재생률로 보간. 재생률은 관측으로 추정 (가속 반영) |
| 집중 비용 | I | 데이터 덤프 기준 (Raptor Strike 30, Wildfire Bomb 10, Boomstick 50 자원 항목) | `spells.yaml`. 실측 집중 변화로 검증 |
| 가속 | I | `COMBATANT_INFO`는 보스 전투 시작 때만. 허수아비에서는 없음 | 연속 시전 간격 하한 + 오라. 허수아비는 첫 몇 GCD로 추정 |
| GCD 길이 | I | 가속 의존 | 위와 같음. 하한 0.75 s 가정 [미확인] |
| 목표까지 거리 | U | 위치는 있지만 몸집 반경 없음 | §3.3 구간 값 |
| 현재 목표(대상 선택) | I | 대상 선택 이벤트 없음 | 최근 직접 공격 대상 |
| `active_enemies` | I | — | 최근 3 s 플레이어가 피해 준 적 수 |
| `target.time_to_die` | I | 사후에는 실제 사망 시각을 알지만, 사람은 미래를 모름 | **체력 감소 추세로 추정한 값**을 쓴다 (사후 정보 사용 금지). MVP 단일 대상 목록에서는 쓰이지 않음 |
| 펫 상태(생존·거리) | 부분 O | 펫 사망은 `UNIT_DIED`, 거리는 펫 이벤트 위치 | 펫 사망 중 Kill Command는 사용 불가 처리. Kill Command 시전 실패 사유가 기록되면 사용 |
| 주문 대기열·네트워크 지연 | X | — | 결정 창 `Q`, `R`로 흡수 |
| 특성 (허수아비) | I | `COMBATANT_INFO` 없음 | 특성 프로필 + 관측 주문 교차 검증 |
| 장신구·종족 특성 | O (사용) | — | 판정 제외 |
| 전투 중 `/reload`·크래시로 손실된 데이터 | X | 일괄 기록 방식에서 손실 보고 [2차] | 이벤트 공백이 길면 해당 구간 EXCLUDED(`data_gap`) + 경고 |

### 6.2 지연 판정(lookahead)

- "상태 증거"와 "결정 정보"를 구분한다.
  - **상태 증거**: 나중 이벤트가 과거 상태를 확정해 주는 경우. 예: 모델상 Wildfire Bomb 준비가 `[10.2 s, 11.0 s]`였는데 10.4 s에 시전됨 → 10.4 s 이전에 준비됐다는 사실이 확정되어 구간을 `[10.2, 10.4]`로 좁힘. **허용한다.**
  - **결정 정보**: 플레이어가 그 시점에 알 수 없었던 미래 정보. 예: 다음 GCD에 Raptor Swipe!가 뜰 것. **판정에 쓰지 않는다.**
- 풀 종료 후 채점(주 모드)에서는 풀 전체 이벤트가 있으므로 상태 증거를 모두 반영한 뒤 판정한다.
- 전투 중 갱신(선택 기능)에서는 DP마다 보류창(기본 2 s) 동안 판정을 미루고, 그 사이 들어온 상태 증거만 반영한다.

### 6.3 불확실 값이 판정에 미치는 영향

불확실성은 출처가 두 가지이고, 출처에 따라 다르게 처리한다.

| 출처 | 예 | 처리 |
|---|---|---|
| **공정성 허용** (의도적으로 넣은 불확실성) | 반응 시간 안에 뜬 확률 발동(§3.1), 경계값 `δ`(§3.2), 사거리 몸집 반경(§3.3) | 플레이어에게 유리하게 → ACCEPTABLE |
| **모델 불확실성** (엔진이 상태를 정확히 모름) | 쿨다운 감소 누적 오차로 생긴 준비 시각 구간, Howl 주기 추론 오차, 가속 추정 오차 | 판정 보류 → INDETERMINATE (점수 제외) |

절차:
1. **점 추정 상태**(각 불확실 값의 가장 그럴듯한 값)로 APL을 평가해 `top*`를 구한다.
2. **3값 논리**로 APL을 평가해 가능한 top의 집합 `C`를 구한다. 위에서부터 줄을 보며 `unknown` 줄의 행동은 `C`에 넣고 계속 내려가고, 첫 `true` 줄의 행동을 넣고 멈춘다 ([ARCHITECTURE §4.7](ARCHITECTURE.md#47-apl-evaluator-apl-평가기)).
3. 판정:
   - 실제 = `top*` → MATCH
   - 실제 ∈ `top*`의 동률 그룹 → ACCEPTABLE
   - 실제 ∈ `C` − {`top*`}: 그 후보를 만든 `unknown`이 **공정성 허용**에서만 왔으면 ACCEPTABLE, **모델 불확실성**이 하나라도 끼었으면 INDETERMINATE
   - 실제 ∉ `C` → 어떤 가능성에서도 정답이 아님 → MINOR 또는 MISTAKE
   - 데이터 공백·미등록 항 때문에 `C` 자체를 정할 수 없음 → INDETERMINATE
   - 예: `C` = {Kill Command, Raptor Strike}, 실제 Wildfire Bomb → MISTAKE (불확실성과 무관하게 틀림)
4. 불확정 판정은 진단 탭에 "어떤 항(term) 때문에 불확정인지"로 집계해 모델 개선 대상으로 삼는다.

## 7. 판정 근거 기록

모든 판정은 다음을 남긴다 ([ARCHITECTURE §3.5](ARCHITECTURE.md#35-judgement)):
- 평가한 APL 줄 번호·원문 조건식·평가 결과(true/false/unknown)
- 판정에 쓴 상태 값 (Tip of the Spear 중첩, 충전, 쿨다운 남은 시간, 집중, 관련 오라)
- 적용된 허용 규칙 코드 (`reaction_window`, `queue_window`, `boundary_tolerance`, `tie_group:<id>`, `held_cd_collapse`)
- 원본 이벤트 참조(`raw_ref`)

이 기록은 AI 해설의 근거, 사용자 이의 확인(제어판 타임라인), 회귀 테스트 비교 대상으로 쓴다.

## 8. 결정 항목 (2026-10-16 승인)

- **D-10** 반응 허용 `R`(300 ms), 경계값 `δ`(150 ms), 주문 대기열 `Q`(400 ms) 초기값 승인.
- **D-11** 이동 중 공백 처리 기본값: IDLE(원거리 행동이 있었으면 감점) vs EXCLUDED.
- **D-12** 동률 그룹·경미 쌍 초기 목록 검토 (생존 이론 관점에서 사용자 확인 필요).
- **D-13** MVP에서 2마리 구간 제외 여부 (기본: 제외).
