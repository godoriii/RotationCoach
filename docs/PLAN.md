# Rotation Teacher — 기획안

> 상태: 초안 v0.1 (2026-11-18) · 승인 전 본 구현 없음
> 대상: WoW 리테일 한밤 12.1.5 (빌드 70783, TOC 120105) · 사냥꾼 (야수/사격/생존)
> 표기: **[확인]** 1차 출처(Blizzard UI 소스·공식 문서·데이터)로 확인 · **[2차]** 2차 출처 · **[미확인]** 확인 못 함. 출처는 [§9](#9-출처).
> 이전 기획(게임 밖 오버레이 "RotationCoach")은 폐기했다. 내용은 git 이력 `7c0fa8f`에 남아 있다.

## 1. 한 줄 정의

**전투가 끝난 뒤, 내가 실제로 누른 스킬 순서를 기준 로테이션(오프닝·우선순위·상위 로그)과 비교해 "어디가 왜 달랐는지"를 게임 안에서 한국어로 보여 주는 연습용 애드온.**

- 전투 중에는 기록만 하고 아무것도 조언하지 않는다. 결과는 전투가 끝난 뒤에만 보여 준다.
- 허수아비 연습과 실제 전투(던전·레이드·쐐기) 모두 대상이다.

## 2. 조사 결론: 인게임 애드온으로 가능한가

**가능하다. 단, 애드온이 볼 수 있는 것은 "내가 누른 스킬 순서"까지이고, 버프·집중·쿨타임 숫자는 전투 중에 볼 수 없다.** 그래서 분석 항목을 "시전 순서만으로 되는 것"부터 쌓는다.

| 정보 | 한밤 애드온에서 | 근거 |
|---|---|---|
| 내 시전 순서 (주문 ID + 시각), 펫 포함 | **읽을 수 있음. 허수아비·던전·레이드·쐐기 모두** | `UNIT_SPELLCAST_*` 이벤트는 대상이 플레이어·펫이면 비밀 값이 아님 [확인: UI 소스 문서, 12.0 공식 노트 "the player's own spellcasts will no longer be secret (even in combat)"]. 실제 레이드 안 동작은 선례 애드온(Midnight Sensei) 기준 [2차], 직접 시험은 M0에서 |
| 전투 로그 이벤트 | **불가** | `COMBAT_LOG_EVENT(_UNFILTERED)` 등록 시 `ADDON_ACTION_FORBIDDEN` [확인] |
| 집중(현재 값) | **불가** (주 자원은 비밀 값) | [확인: 전투 중], 전투 밖도 비밀이라는 보고 [2차] |
| 버프·디버프 (중첩, 남은 시간) | **전투 중 불가** (어떤 전투든, 허수아비 포함) | 12.1에서 `UNIT_AURA`도 전투 중 전부 비밀 [확인] |
| 쿨타임 남은 시간, 현재 충전 수 | **전투 중 불가** | [확인] |
| 쿨타임이 "도는 중인지" (`isActive`), GCD 중인지, 최대 충전 수 | 읽을 수 있음 | `NeverSecret` 표시 [확인] |
| 스킬 사용 가능 여부, 자원 부족 여부 (`C_Spell.IsSpellUsable`) | 읽을 수 있음 | 비밀 표시 없음 [확인] |
| 발동 효과 반짝임 (`SPELL_ACTIVATION_OVERLAY_GLOW_SHOW/HIDE`) | 읽을 수 있음 | 비밀 표시 없음 [확인] |
| 전투 시작·종료, 보스 전투 ID·이름·난이도 | 읽을 수 있음 | [확인] |
| 가속 | 전투 중 불가 → **전투 직전에 저장** | [확인] |
| 특성·영웅 특성·전문화 | 읽을 수 있음 | [확인] |
| 전투 후 스킬별 총 피해 (`C_DamageMeter`) | **전투가 끝나면** 읽을 수 있음 (시전 횟수·타임라인은 없음) | `SecretWhenInCombat` [확인] |
| 대상 이름·GUID | 야외는 가능 [2차], 인스턴스 안은 비밀 [확인] → 보스는 전투 ID로 구분 | |
| 네트워크·파일 접근 | **불가.** 저장은 SavedVariables뿐 | [확인: API 없음] |

따라서 생기는 설계 제약 두 가지:

1. **애드온은 WCL·가이드 사이트에 접속할 수 없다.** 기준 데이터는 PC에서 따로 만들어 애드온 폴더에 Lua 데이터 파일로 넣어 줘야 한다 (TSM 등이 쓰는 검증된 방식 [2차]).
2. **"그 순간 버프가 몇 중첩이었나"가 필요한 판정은 직접 못 본다.** 시전 기록으로 추론하거나(예: 살상 명령을 쓰면 창끝 +1), 볼 수 있는 신호(반짝임, 쿨타임 도는 중 여부)로 대신한다.

정책 면에서는 Blizzard가 12.0 API 노트에서 "Teaching players how to play their spec at a baseline level … are things we support"라고 밝혔고, 막으려는 것은 전투 중 실시간 최적 판단이다 [확인]. 전투 후 복기는 그 선 안쪽이다. 다만 전투 후 코칭 애드온을 직접 언급한 Blizzard 입장은 찾지 못했다 [미확인].

## 3. 먼저 확인할 것: 비슷한 애드온이 이미 있다

| 애드온 | 하는 일 | 우리와 차이 |
|---|---|---|
| **Midnight Sensei** (12.1.5 지원, 약 1만 다운로드) | 전투 후 A+~F 등급, "Review Fight". 시전 이벤트만 사용 | 기준 오프닝·상위 로그와의 구체적 비교는 없음 [2차] |
| **RecommendedStats** (12.1.5, 2026-11-17 갱신) | WCL 상위 로그에서 뽑은 우선순위·오프닝·쿨기 타이밍을 애드온에 내장, 상위 플레이어와 나란히 비교 | 가장 가까움. 한국어·"왜 틀렸나" 설명·가이드 연결 여부는 미확인 [2차] |
| **CombatAnalytics** | 허수아비·결투 세션, 오프너 랩(첫 5시전) | 규모 작음 |

**M0에서 Midnight Sensei와 RecommendedStats를 직접 써 보고, 부족한 점을 확인한 뒤 진행 여부를 정한다.** 이미 원하는 기능이 있다면 새로 만들 이유가 줄어든다. 만들기로 하면 차별점은 ① 기준과의 차이를 "어느 시전이 무엇과 달랐는지" 단위로 보여 줌 ② 한국어 설명 ③ 가이드 출처 연결 ④ 허수아비 연습 흐름이다.

## 4. 전체 구조

```
┌─ PC: 데이터 빌더 (가끔 실행, 패치·시즌마다) ───────────────┐
│  SimC APL (GitHub, 커밋 고정) ──┐                          │
│  WCL API v2 (상위 로그 시전)  ──┼─→ 기준 데이터 Lua 파일 생성 │
│  가이드 메모 (손으로 옮긴 YAML) ─┘     ↓                    │
└───────────────────────────────────────│───────────────────┘
                                        ▼  Interface/AddOns/RotationTeacher/Data/Generated/*.lua
┌─ 게임 안: 애드온 RotationTeacher ───────────────────────────┐
│  Recorder  : 내 시전 + 볼 수 있는 신호 기록 (전투 중, 표시 없음)│
│  Session   : 전투별 기록 저장 (SavedVariables)               │
│  Analyzer  : 전투 종료 후 기준 데이터와 비교                  │
│  Report UI : 점수, 주요 문제 Top N, 타임라인 (한국어)         │
└────────────────────────────────────────────────────────────┘
(선택, 나중) PC에서 WoWCombatLog.txt를 읽어 버프·집중까지 포함한 정밀 분석 → 결과 Lua로 되돌려 주기
```

- 빌더가 만든 Lua 파일은 `/reload` 또는 다음 접속 때 읽힌다.
- 애드온만으로 동작한다. 빌더는 기준 데이터를 갱신할 때만 필요하다.

### 4.1 애드온이 기록하는 것

| 시점 | 기록 |
|---|---|
| 전투 직전 | 전문화, 영웅 특성, 특성 목록, 가속, 주요 스킬 쿨타임 상태 |
| 시전마다 | 주문 ID, 시각, 시전 종류(즉시/시전/정신 집중), 실패·중단 여부, 그 순간 주요 스킬별 "쿨 도는 중" 여부, 켜져 있는 반짝임, 자원 부족 여부 |
| 전투 종료 | 지속 시간, 보스 전투 ID·난이도(있으면), `C_DamageMeter` 스킬별 피해 |

비밀 값 규칙은 패치마다 바뀌므로, 값을 쓰기 전에 항상 `issecretvalue()`로 확인하고 비밀이면 "모름"으로 기록한다.

### 4.2 분석 항목과 가능 여부

| # | 항목 | 필요한 데이터 | 가능 여부 |
|---|---|---|---|
| 1 | **오프닝 비교**: 첫 8~10시전을 기준 순서와 맞춰 보고 빠짐·순서 바뀜·늦음 표시 | 시전 순서 | ✅ |
| 2 | **공백**: GCD가 비어 있던 시간, 활동 비율 | 시전 시각, 전투 전 가속 | ✅ |
| 3 | **주요 쿨기**: 사용 횟수 대 가능 횟수, 첫 사용 시점, 상위 로그 대비 타이밍 | 시전 시각, "쿨 도는 중" 여부 | ✅ |
| 4 | **분당 시전 수(CPM)**: 스킬별로 상위 로그와 비교 | 시전 횟수 | ✅ |
| 5 | **충전 넘침**: 날카로운 사격·살상 명령·야생불 폭탄 등이 최대 충전으로 방치된 시간 | "충전 회복 중" 여부 | ✅ (추정치) |
| 6 | **발동 효과 대응**: 반짝임이 뜬 뒤 쓰기까지 걸린 시간, 버린 횟수 | 반짝임 이벤트 | ✅ (반짝임이 있는 효과만, M0에서 목록 확인) |
| 7 | **우선순위 위반**: "그 순간 더 높은 우선순위 스킬이 있었는데 다른 걸 씀" | 버프 중첩·집중 | ⚠️ 부분. 시전 기록으로 추론 가능한 규칙만 (예: 창끝 0중첩에서 소모기 사용) |
| 8 | 집중 넘침, 버프 유지율 정밀 측정 | 집중·오라 | ❌ 애드온만으로 불가 → 선택 기능(전투 로그 파일 정밀 분석)에서 |

보고서는 손실이 큰 순서로 상위 3~5개 문제만 먼저 보여 주고, 각 문제에 "무엇을 했고 / 기준은 무엇이었고 / 왜 그런지 한 줄 / 출처 링크 텍스트"를 붙인다.

## 5. 기준 데이터: 출처별 사용 방법

| 출처 | 쓰임 | 가져오는 방법 | 주의 |
|---|---|---|---|
| **SimC APL** (`simulationcraft/simc`, `midnight` 브랜치) | 우선순위 규칙의 기준. 전문화 × 영웅 특성별 단일 대상 목록이 따로 있음 | GitHub에서 커밋 고정으로 받아 파싱 | GPL-3.0. 개인 사용은 문제없음. 공개 배포 시 원문을 그대로 넣으면 GPL 의무가 따름 → 규칙을 자체 형식으로 옮기고 출처 표기 [확인] |
| **WCL 상위 로그** (API v2) | 실제 오프닝(첫 N시전), CPM, 쿨기 타이밍. 보스·난이도·영웅 특성별 | 내 클라이언트로 랭킹 → 리포트 → 시전 이벤트 조회 후 집계 | 요청 한도가 줄어드는 중 (아래). 약관상 캐시·재배포 제한이 있다는 요약 [2차, 원문 미확인] |
| **Wowhead / Icy Veins 가이드** | 사람이 읽는 설명, 오프닝 표기, "왜"의 근거 | **자동 수집하지 않는다.** 핵심 사실만 손으로 옮기고(자체 문장) 출처 링크를 건다 | Wowhead robots.txt는 AI·스크레이퍼 수집을 명시적으로 금지 [확인]. Icy Veins는 봇 차단 + 무단 복제 금지 문구 [2차] |
| Blizzard 보조 전투 목록 (SimC에 미러링) | "기본기" 수준의 쉬운 기준 (선택) | SimC 저장소의 `assisted_combat/` | Blizzard가 일부러 최적이 아니게 만든 목록 [2차] |

- 사격 가이드(Wowhead)와 SimC 사냥꾼 APL은 같은 작성자(Azortharion)가 관리한다 [확인]. 그래서 APL을 규칙 기준으로 삼으면 가이드 우선순위와 대체로 일치한다.
- **허수아비에는 WCL 기준이 없다.** WCL 랭킹은 보스 전투에만 있다 [2차]. 허수아비 연습은 가이드 오프닝 + APL 우선순위 + 단일 대상 보스의 상위 로그 오프닝을 기준으로 쓴다.
- SimC에는 "오프닝" 목록이 따로 없다 (전투 전 목록 + 우선순위의 첫 진행이 오프닝). 오프닝 기준은 WCL 집계와 가이드 메모에서 만든다.

### 5.1 WCL 연동

- **요청 한도**: 기존 무료 한도는 시간당 3,600점이었으나, 2026-10-20부터 한도 개편 베타가 진행 중이고 비구독 키는 시간당 1,000점(랭킹 조회는 그중 250점 별도 한도)으로 줄어든다는 보고가 있다 [2차]. 전투 1건 시전 조회는 약 2~6점 [2차]. → 한 번 실행에 "전문화 1개 × 보스 1개 × 상위 50개 로그" 정도로 나눠 받고, 결과를 로컬에 저장해 다시 받지 않는다.
- **약관**: 본 구현 전에 RPG Logs API 약관 원문을 브라우저로 직접 읽는다. 개인용·비상업·요청 최소화가 전제다.
- **클라이언트 종류 (결정 필요, D-3)**: 올려 주신 클라이언트는 **PKCE 방식**이다. PKCE는 시크릿이 없고, 브라우저 로그인 후 등록된 리디렉션 URL로 돌아와야 토큰을 받는다. 지금 등록된 URL(`…workers.dev`)은 다른 용도의 주소라 이 도구에서 그대로 쓸 수 없다. 선택지는 둘이다.
  - (추천) **Rotation Teacher용 일반 클라이언트를 새로 만든다** (PKCE 체크 해제 → ID + 시크릿). 로그인 없이 공개 데이터(랭킹·공개 로그)를 받을 수 있어 빌더가 단순해진다 [2차].
  - 기존 PKCE 클라이언트에 `http://localhost:8765/callback` 같은 리디렉션 URL을 추가해 브라우저 로그인 방식으로 쓴다. 비공개 로그까지 볼 수 있지만 구현이 늘어난다.

### 5.2 WCL 값 보관 (요청 사항)

- `tools/Save-WclCredential.ps1`을 PC에서 한 번 실행하면 값을 화면에 안 보이게 입력받아 **DPAPI로 암호화한 XML**(`%APPDATA%\RotationTeacher\wcl-client.xml`)로 저장한다. 같은 PC의 같은 Windows 계정에서만 풀린다.
- 저장소에는 값을 넣지 않는다. 빌더는 실행할 때 이 XML을 읽어 복호화한다 (Python에서 XML의 암호문을 Windows `CryptUnprotectData`로 복호화).
- PKCE를 쓰게 되면 로그인 후 받는 토큰도 같은 방식으로 저장한다.
- 이 스크립트는 **Windows에서 아직 실행해 보지 못했다** (작성 환경이 Linux). 첫 실행 때 `-Show`로 저장 확인이 필요하다.

## 6. 범위

| 구분 | 내용 |
|---|---|
| MVP | 사냥꾼 전문화 1개 × 영웅 특성 2개, 단일 대상. 분석 항목 1~6. 허수아비 + 레이드 보스 |
| 그다음 | 나머지 사냥꾼 전문화, 항목 7(추론 가능한 우선순위 규칙), 광역 |
| 선택 | 전투 로그 파일 정밀 분석(항목 8), 다른 직업 |
| 하지 않음 | 전투 중 조언·다음 스킬 표시, 가이드 사이트 자동 수집, 게임 밖 오버레이, 다른 플레이어 분석 |

확장 구조: 전문화별 데이터(`Data/Specs/<class>_<spec>.lua`: 주문 ID, 쿨기 목록, 추론 규칙)와 생성 데이터(`Data/Generated/`)만 추가하면 되도록 코어는 직업을 모르게 만든다.

전문화별 작업량 (12.1.5 기준, SimC 데이터 [확인]):

| 전문화 | 영웅 특성 | 핵심 스킬 | 난이도 |
|---|---|---|---|
| 야수 | 무리의 지도자 / 어둠 순찰자 | 살상 명령, 날카로운 사격, 코브라 사격, 야수의 격노(90초) | 낮음. 즉시 시전, 충전 관리 위주 |
| 사격 | 어둠 순찰자 / 파수꾼 | 조준 사격, 속사, 신비한 사격, 고정 사격, 폭발 사격, 정조준(120초), 연발 사격(45초) | 높음. 시전 시간, 전투 전 조준 사격, 발동 효과 소모 |
| 생존 | 무리의 지도자 / 파수꾼 | 살상 명령, 랩터의 일격, 야생불 폭탄, Boomstick(60초), Takedown(90초) | 중간. 창끝 중첩 추적이 핵심 |

## 7. 진행 단계

| 단계 | 내용 | 완료 기준 |
|---|---|---|
| **M0 검증** | ① Midnight Sensei·RecommendedStats 직접 사용해 보고 차이 정리 ② 검증용 소형 애드온: 시전 이벤트·쿨 상태·반짝임·`C_DamageMeter`가 허수아비/던전/레이드에서 실제로 읽히는지 SavedVariables로 덤프 ③ WCL: 값 저장 스크립트 실행, 조회 1회로 점수 소모 측정, 약관 원문 확인 | 표 §2의 [2차]·"M0에서 확인" 항목이 실측으로 바뀜. 진행/중단 결정 |
| **M1 기록기** | Recorder + Session 저장 + 전투 후 간단 요약(시전 목록, CPM, 공백) | 허수아비 3분 기록이 손으로 센 것과 일치 |
| **M2 기준 데이터 빌더** | APL 파싱 → 우선순위 데이터, WCL 상위 로그 집계 → 오프닝·CPM·쿨기 타이밍, 가이드 메모 → Lua 생성 | 전문화 1개의 기준 데이터 파일 생성, 다시 실행해도 같은 결과 |
| **M3 분석기** | 항목 1~6 비교, 문제 순위, 점수 | 녹화한 세션 고정 데이터로 결과가 재현됨. 본인 판단과 큰 문제 Top 3 일치 |
| **M4 보고 화면** | 전투 후 창: 점수, 주요 문제, 오프닝 나란히 보기, 타임라인. 한국어 | 전투 중 아무 조언도 표시되지 않음을 확인 |
| **M5 확장** | 항목 7, 나머지 전문화·영웅 특성 | 전문화 추가가 데이터 파일만으로 됨 |
| M6 (선택) | 전투 로그 파일 정밀 분석 | — |

테스트 방법: 분석 로직은 게임 밖에서도 돌도록 순수 Lua로 분리하고, 게임에서 덤프한 세션을 고정 데이터로 삼아 Lua 5.1로 회귀 테스트한다. 빌더는 녹화한 WCL 응답으로 오프라인 테스트한다. 화면과 이벤트는 게임에서 직접 확인한다 (이 부분은 사용자 PC 필요).

### 제안 폴더 구조

```
RotationTeacher/                 # 애드온 (Interface/AddOns 로 복사 또는 링크)
  RotationTeacher.toc            # Interface: 120105
  Core/        Recorder.lua  Session.lua  Secrets.lua
  Analyzer/    Opener.lua  Downtime.lua  Cooldowns.lua  Cpm.lua  Capping.lua  Procs.lua  Score.lua
  UI/          Report.lua  Timeline.lua
  Locales/     koKR.lua  enUS.lua
  Data/Specs/  hunter_survival.lua …      # 손으로 관리: 주문 ID, 쿨기, 추론 규칙
  Data/Generated/                         # 빌더 출력: 오프닝, CPM, 쿨기 타이밍, 우선순위
builder/                         # PC 데이터 빌더 (Python): wcl/  apl/  emit_lua/  dpapi.py
references/guides/               # 가이드에서 손으로 옮긴 메모 (YAML, 출처 URL 포함)
tools/Save-WclCredential.ps1     # WCL 값 DPAPI 저장
tests/                           # Lua 분석기 테스트, 빌더 테스트, 고정 데이터
docs/PLAN.md
```

## 8. 결정이 필요한 항목

| ID | 결정 | 추천 |
|---|---|---|
| **D-1** | 구조: 애드온 + PC 데이터 빌더 방식으로 진행 | 승인 |
| **D-2** | 첫 대상 전문화·영웅 특성 | 주로 하는 전문화 (이전 기획 기준이면 생존) |
| **D-3** | WCL 클라이언트: 전용 일반 클라이언트 새로 만들기 vs 기존 PKCE 재사용 | 새로 만들기 |
| **D-4** | 가이드(Wowhead/Icy Veins)는 자동 수집 없이 손으로 옮기고 링크만 건다 | 승인 |
| **D-5** | 배포 범위: 개인용 vs 공개 (공개면 SimC GPL·WCL 약관 대응 필요) | 개인용으로 시작 |
| **D-6** | M0에서 기존 애드온 2종을 먼저 써 보고 진행 여부 결정 | 승인 |
| **D-7** | M0 검증용 소형 애드온 작성 | 승인 요청 |

## 9. 출처

조회일 2026-11-18. warcraftlogs.com·archon.gg·icy-veins.com은 자동 조회가 차단되어 2차 자료로 확인했다.

**애드온 API (Blizzard UI 소스 `Gethe/wow-ui-source` live 12.1.5.70783, `Interface/AddOns/Blizzard_APIDocumentationGenerated/`)**
- `SecretPredicatesDocumentation.lua`, `RestrictedActionsConstantsDocumentation.lua`, `UnitDocumentation.lua`(UNIT_SPELLCAST_*), `SpellSharedDocumentation.lua`(쿨타임·충전 필드), `SpellActivationOverlayDocumentation.lua`, `CombatLogDocumentation.lua`, `DamageMeterDocumentation.lua`, `AssistedCombatDocumentation.lua` — https://github.com/Gethe/wow-ui-source
- 비밀 값·패치별 API 변경 — https://warcraft.wiki.gg/wiki/API_change_summaries · https://warcraft.wiki.gg/wiki/Patch_12.0.0/API_changes · https://warcraft.wiki.gg/wiki/Patch_12.1.5/API_changes
- Blizzard, "Combat Philosophy and Addon Disarmament in Midnight" — https://news.blizzard.com/en-us/article/24246290/combat-philosophy-and-addon-disarmament-in-midnight
- UI Add-On Development Policy — https://us.forums.blizzard.com/en/wow/t/ui-add-on-development-policy/24534

**선례 애드온**
- Midnight Sensei — https://www.curseforge.com/wow/addons/midnight-sensei · https://github.com/MidnightTim/MidnightSensei
- RecommendedStats — https://www.curseforge.com/wow/addons/recommended-stats
- CombatAnalytics — https://github.com/ldilov/combat-analytics
- Hekili 종료 안내 — https://github.com/Hekili/hekili

**기준 데이터**
- SimC APL·보조 전투 목록 — https://github.com/simulationcraft/simc/tree/midnight/ActionPriorityLists
- Wowhead 사냥꾼 로테이션 가이드 — https://www.wowhead.com/guide/classes/hunter/survival/rotation-cooldowns-pve-dps (야수·사격은 경로의 전문화 이름만 다름) · robots.txt — https://www.wowhead.com/robots.txt
- Icy Veins 사냥꾼 가이드 — https://www.icy-veins.com/wow/survival-hunter-pve-dps-rotation-cooldowns-abilities
- WCL API 한도 개편 보고 — https://github.com/katogaming88/WGA-Raid-Hub/issues/1592 · 공지(차단됨) https://www.archon.gg/wow/articles/help/archon-api-updates-beta
- RPG Logs API 약관(차단됨, 원문 미확인) — https://www.archon.gg/wow/articles/help/rpg-logs-api-terms-of-service
- WoWAnalyzer (점검 항목 참고) — https://github.com/WoWAnalyzer/WoWAnalyzer
