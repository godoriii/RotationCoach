# TECH_DECISIONS — 기술 선택 비교와 추천안

> 상태: 기획 초안 v0.1 (2026-10-16)
> 표기: **[확인]** 1차 출처(공식 문서·소스 코드·데이터)로 확인, **[2차]** 신뢰할 만한 2차 출처, **[미확인]** 출처로 확인하지 못함 또는 추정. 출처 번호는 [부록 B](#부록-b-출처)를 가리킨다.

## 0. 요약

| 항목 | 추천안 | 핵심 이유 |
|---|---|---|
| 언어·런타임 | **Python 3.12+ 단일 언어**, `uv`로 가상환경 관리, 패키징 없이 로컬 실행 | 엔진·오버레이·API 클라이언트를 한 프로세스에서. 1인 사용이라 배포 부담 없음 |
| 오버레이 | **PySide6 (Qt Widgets + QPainter)** + Win32 확장 스타일 재확인 | Qt 플래그가 필요한 `WS_EX_*` 조합에 1:1 대응 [확인 B-20], 같은 프로세스, 메모리 적음 |
| APL 처리 | **혼합안: SimC APL 부분 인터프리터 + 생존 스펙 어댑터(데이터·핸들러)** | 한밤 생존 APL은 표현식 종류가 적어 인터프리터 부담이 작음 [확인 B-10]. Hekili가 같은 구조로 검증됨 [확인 B-14] |
| WCL | OAuth2 client credentials(공개 로그) + PKCE(비공개 로그는 선택), GraphQL v2, SQLite 단기 캐시 | 무료 3,600점/시간이면 1인 사용에 충분 [2차 B-31] |
| Claude | 빠른 요약 **Haiku 5.5**(effort low, 구조화 출력), 상세 **Sonnet 5.5**(기본) / Opus 5.5(선택), 정적 접두부 프롬프트 캐싱 | 풀당 약 $0.001(빠른 요약), 상세 1회 약 $0.13(Sonnet) |
| 비밀 값 저장 | **Windows 자격 증명 관리자(`keyring`)** + Console 작업공간 지출 한도 | 평문 파일보다 유출 경로(커밋·동기화·백업)가 적고, 피해 상한을 한도로 묶음 |

> **가장 큰 전제 변화**: WoW는 패치 10.2부터 전투 로그를 메모리에 모았다가 전투가 끝날 때 몰아서 쓰는 방식으로 바꿨다고 보고됐다 [2차 B-1, B-2]. 2025년 8월에는 "수 분까지 지연된다"는 개발자 보고도 있다 [2차 B-3]. Blizzard는 이 변경을 **게임 밖 실시간 오버레이를 막으려는 조치**라고 설명했다 [2차 B-1, B-4]. 그래서 이 문서의 모든 선택은 **"풀 종료 직후 채점·표시"를 주 모드**로, "전투 중 갱신"은 데이터가 실제로 들어올 때만 동작하는 부가 기능으로 둔다. 한밤 12.x에서 실제 동작은 [SPIKES S1](SPIKES.md#s1-로그-기록-지연과-뭉침-측정)에서 실측한다.

---

## 1. 구현 언어와 런타임

| 기준 | Python 3.12 | TypeScript (Node/Electron) | C# (.NET 8) |
|---|---|---|---|
| 로그 파싱 처리량 | 순수 Python 토크나이저는 대략 수십만 줄/초 [미확인, S1에서 벤치]. 사전 필터로 대부분의 줄을 부분 문자열 검사만 하고 버림 | V8 JIT로 빠름 | 가장 빠름 |
| 오버레이 | PySide6 같은 프로세스 | Electron 같은 런타임 | WPF/WinUI interop 필요 |
| 데이터 분석·회귀 테스트 | pytest, hypothesis, pandas 자유 | 가능하나 생태계 약함 | 보통 |
| SimC/Hekili 참고 코드 이식 | Hekili 구조(Lua) → Python 이식이 자연스러움 | 가능 | 가능 |
| Claude/WCL SDK | `anthropic` 공식 SDK [확인], `httpx`·`gql` | 공식 SDK [확인] | 공식 SDK [확인] |
| 사용자 숙련도 | Lua 경험자에게 문법 진입 쉬움 | 보통 | 보통 |

**추천: Python.** 1인용이라 배포 크기·백신 오탐 문제(PyInstaller 빌드에서 흔함 [2차 B-23])도 패키징을 안 하면 사라진다. `uv run rotationcoach`로 실행한다. 성능이 부족하면 토크나이저만 Rust(PyO3) 확장으로 바꿀 수 있게 경계를 둔다 (M1 벤치 결과로 판단).

---

## 2. 오버레이 기술

### 2.1 요구 동작과 Win32 대응

| 요구 | Win32 | PySide6 | Electron |
|---|---|---|---|
| 클릭 통과 | `WS_EX_TRANSPARENT` + `WS_EX_LAYERED` | `Qt.WindowTransparentForInput` → 두 스타일을 모두 설정 [확인 B-20] | `setIgnoreMouseEvents(true)` → 같은 스타일 [확인 B-25] |
| 포커스 비탈취 | `WS_EX_NOACTIVATE`, `SW_SHOWNOACTIVATE` | `Qt.WindowDoesNotAcceptFocus`, `WA_ShowWithoutActivating` [확인 B-20] | `focusable:false`, `showInactive()` [확인 B-24] |
| 작업표시줄·Alt-Tab 제외 | `WS_EX_TOOLWINDOW` | `Qt.Tool` [확인 B-20] | `skipTaskbar`, `focusable:false`가 함의 [확인 B-24] |
| 항상 위 | `SetWindowPos(HWND_TOPMOST, SWP_NOACTIVATE)` | `Qt.WindowStaysOnTopHint` [확인 B-20] | `setAlwaysOnTop(true,'screen-saver')` [확인 B-24] |
| 투명 배경 | 레이어드 창 | `WA_TranslucentBackground` → CPU 페인트 + `UpdateLayeredWindowIndirect` [확인 B-21] | `transparent:true` (프레임 없는 창에서만) [확인 B-24] |

- `WS_EX_TRANSPARENT`가 있으면 창 전체가 클릭 통과된다 (픽셀 알파와 무관) [확인 B-22].
- `WS_EX_TOPMOST`는 `SetWindowLongPtr`가 아니라 `SetWindowPos`로 바꿔야 한다 [확인 B-22].
- 테두리 없는 창 모드(flip model) 게임 위에는 DWM이 최상위 창을 합성하므로 보인다. 독점 전체 화면에서는 보이지 않는다. WoW는 8.0 사전 패치에서 독점 전체 화면을 없애고 창 모드와 "창 모드(전체 화면)"(borderless)만 남겼다 [확인 B-26b, 2차 B-26]. 12.x에서 다시 생겼다는 자료는 없으며 S3에서 실제 화면 모드를 확인한다.
- 게임 위에 다른 창이 있으면 DWM이 독립 플립(Independent Flip)에서 합성 모드로 돌아가거나 MPO를 써서 유지하는데, GPU·드라이버에 따라 약간의 지연·효율 손실이 생길 수 있다 [확인 B-27]. → S3에서 PresentMon으로 측정.

### 2.2 비교

| 기준 | PySide6 (추천) | Electron | 기타 |
|---|---|---|---|
| 투명·최상위·클릭 통과 구현 난이도 | 쉬움. Qt 플래그만으로 필요한 조합이 나오고, 보험으로 `ctypes`로 한 번 더 강제 | 쉬움. Awakened PoE Trade 등 선례 많음 [확인 B-28] | Tauri: 클릭 통과 관련 열린 이슈 [2차 B-29]. WPF: interop 필요. ImGui/GLFW: 직접 구현 많음 |
| 메모리 | 약 40–80 MB [미확인] | 약 120–170 MB (주·렌더러·GPU 프로세스) [2차 B-30] | Tauri 약 80–110 MB [2차] |
| 렌더링 경로 | CPU 페인트, 변경 시에만 갱신 → GPU 경합 거의 없음 | Chromium GPU 프로세스가 게임과 GPU 공유 [미확인, 측정 필요] | — |
| 엔진 연동 | 같은 프로세스, Qt 시그널 | 별도 Python 프로세스 + IPC(stdio/WebSocket) 필요 | 사이드카 + IPC |
| 배포 | 1인용: 패키징 불필요. 필요 시 PyInstaller onedir 30–80 MB [2차 B-23] | electron-builder 85–150 MB [2차] | — |
| UI 표현력 | QPainter로 충분 (숫자, 막대, 짧은 텍스트) | HTML/CSS로 화려한 UI 쉬움 | — |
| 주의점 | `setWindowFlags`를 보이는 창에 다시 호출하면 창이 재생성·깜빡임 → 첫 `show()` 전에 설정 [2차 B-20b]. Qt Quick 투명 버그 → Widgets 사용 | `forward:true` 옵션은 시스템 전역 저수준 마우스 훅(`WH_MOUSE_LL`)을 설치함 [확인 B-25] → 사용 금지 | — |

**추천: PySide6 Qt Widgets.** 결정 근거는 같은 프로세스·같은 언어, 낮은 메모리, 변경 시에만 그리는 CPU 경로다. Electron은 기능상 동등하지만 런타임이 둘이 되고 IPC가 필요하다.

### 2.3 구현 메모 (본 구현 시)

```python
# 생성 시 1회 (show() 전에)
flags = (Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool
         | Qt.WindowTransparentForInput | Qt.WindowDoesNotAcceptFocus)
w = QWidget(None, flags)
w.setAttribute(Qt.WA_TranslucentBackground)
w.setAttribute(Qt.WA_ShowWithoutActivating)
# showEvent 이후: GetWindowLongPtrW(GWL_EXSTYLE) | (LAYERED|TRANSPARENT|NOACTIVATE|TOOLWINDOW)
#                 SetWindowPos(HWND_TOPMOST, …, SWP_NOMOVE|SWP_NOSIZE|SWP_NOACTIVATE)
```

- **최상위 유지**: 다른 최상위 창(Discord, 게임 바)과 경쟁할 수 있으므로 `SetWinEventHook(EVENT_SYSTEM_FOREGROUND)` 콜백 또는 2 s 타이머로 `HWND_TOPMOST`를 다시 설정한다 [2차, B-22 기반 추론].
- **DPI**: Qt 6는 기본으로 Per-Monitor DPI Aware V2다. Win32 좌표(물리 픽셀)를 Qt 좌표(논리 픽셀)로 바꿀 때 `devicePixelRatio()`로 나눈다 [확인 B-21b].
- **위치**: 기본은 모니터 기준 프리셋 + 오프셋. WoW 창 위치를 따라가는 기능(`FindWindow` + `GetWindowRect`)은 OS 창 정보만 읽고 게임 메모리는 읽지 않는다. 다만 필요성이 낮아 기본 비활성.
- **편집 모드 없음**: 오버레이를 드래그로 옮기는 "상호작용 모드"를 만들지 않는다. 위치는 제어판에서 숫자·프리셋으로 바꾸고 미리보기한다 (C-4를 예외 없이 지킴).
- **대체 경로**: S3에서 PySide6가 실패하면 `ViewModelPublisher`(127.0.0.1 WebSocket)를 추가하고 Electron 오버레이로 교체한다 ([ARCHITECTURE §2.1](ARCHITECTURE.md#21-프로세스스레드-모델-단일-프로세스)).

---

## 3. APL 처리 방식

### 3.1 현재 한밤 생존 APL의 특징 [확인 B-10, B-11]

- 위치: simc 저장소 기본 브랜치 `midnight`, 생성 파일 `ActionPriorityLists/default/hunter_survival.simc` (원본은 `engine/class_modules/apl/hunter/sv.txt`, C++ `apl_hunter.cpp`). 조사 시점 HEAD `76f8118c`(2026-10-15), 데이터 12.1.5.70391.
- 행동 목록 7개: `precombat`, 기본, `cds`, `plst`, `plcleave`, `sentst`, `sentcleave`. 영웅 특성 분기는 `talent.howl_of_the_pack_leader`로 한다.
- 단일 대상 목록(`plst`, `sentst`)이 쓰는 표현식은 적다: `buff.tip_of_the_spear.stack/up`, `buff.raptor_swipe.up`, `debuff.sentinels_mark.remains`, `cooldown.takedown.remains`, `full_recharge_time`(그 줄의 Wildfire Bomb), `gcd`, `talent.twin_fangs`, `talent.lethal_calibration`, `howl_summon.ready`.
- 쓰지 않는 것: `variable`, `run_action_list`, `focus`/`focus.deficit`, `prev_gcd`, `in_flight`, `charges`. 즉 **집중이 충분한지는 SimC 내부 `ready()`가 판단**하므로 엔진이 직접 모델링해야 한다.
- `cds` 목록은 장신구·종족 특성·물약·`invoke_external_buff`처럼 로그로 평가하기 어려운 줄이 대부분이다.
- 변동 빈도: 최근 6개월 생성 파일 재생성 8회, 사람 커밋 약 15회. 패치 시기에 몰리고 그 사이는 조용하다 [확인 B-12].

### 3.2 선택지 비교

| 기준 | A. SimC APL 텍스트 부분 인터프리터 | B. 생존 규칙 수동 코드화 | **C. 혼합안 (추천)** | D. SimC를 오라클로 직접 실행 |
|---|---|---|---|---|
| 개요 | APL 원문을 파싱해 일반 표현식 엔진으로 평가 | 우선순위를 Python 함수로 직접 작성 | A + 스펙 어댑터(주문 데이터, 쿨 변경 핸들러, 고유 표현식, 패치 레이어, 동률 그룹) | 매 DP의 상태로 SimC를 돌려 정답을 받음 |
| APL 갱신 대응 | 원문 교체 + 새 항 경고 | 매번 수동 이식, 누락 위험 | 원문 교체, 새 항만 어댑터에 추가 | 자동 |
| SimC 충실도 | 높음 (상태가 맞으면) | 작성자 해석에 의존 | 높음 + 사람 기준 보정 가능 | 가장 높음 |
| 사람에게 공정한 판정(반응 시간 등) | 별도 계층 필요 | 자유롭게 넣음 | 패치 레이어·판정 계층에서 처리 | 어려움 |
| 숨은 상태 처리 | 별도 필요 | 자유 | 어댑터 핸들러 + 불확실 값 | SimC는 임의 중간 상태에서 시작하는 기능이 없음 [미확인] → 사실상 불가 |
| 초기 비용 | 중 (파서 + 표현식 엔진) | 낮음 | 중 | 매우 높음 |
| 다른 스펙 확장 | 좋음 | 스펙마다 처음부터 | 좋음 | 좋음 |
| 선례 | hero-rotation-generator (Python, 2020 이후 정체) [확인 B-15] | — | **Hekili**: SimC 텍스트 + 스펙별 Lua 데이터·핸들러 + 범용 상태 에뮬레이터 [확인 B-14] | — |

**추천: C.** 한밤 생존 APL은 표현식 종류가 적어 A의 비용이 작고, 숨은 상태·사람 기준 보정은 B의 유연함이 필요하다. Hekili(한밤 출시와 함께 종료 [확인 B-13])가 같은 분할로 오래 동작했다는 점이 설계 근거다.

### 3.3 혼합안 세부

1. **파서**: SimC 조건식 문법(`& | ! = != < <= > >= + - * % %% <? >?`, 괄호)을 우선순위 기반 파서로 구현한다. 연산자 우선순위는 SimC 위키 기준 [확인 B-16]. `&`가 `|`보다 강하게 묶이는지는 위키 문구로 재확인 필요 [미확인].
2. **목록 실행 의미**: `call_action_list`는 하위 목록에서 실행 가능한 행동이 없으면 다음 줄로 돌아온다. `run_action_list`는 돌아오지 않는다 (현재 APL은 미사용).
3. **사용 가능성(`ready`)**: 쿨다운·충전, 집중 비용, 사거리(근접 5야드 계열), 시전 중 여부를 어댑터의 `spells.yaml`로 판정한다. 비용 값은 SimC 데이터 덤프를 기준으로 한다 (예: Raptor Strike 30, Wildfire Bomb 10) [확인 B-11].
4. **채점 범위**: `cds` 목록 중 장신구·종족 특성·물약·외부 버프 줄은 GCD 판정에서 제외(`ignore_actions`)하고, Takedown 같은 주요 쿨기는 단일 대상 목록 쪽 판정과 별도 "쿨다운 효율" 지표로 다룬다. `retarget`, `auto_attack`, `snapshot_stats`, `summon_pet`도 제외한다.
5. **APL 고정**: `apl.lock`에 저장소·브랜치·커밋·가져온 날짜를 기록한다. 갱신 도구(`tools/apl_update.py`)는 새 원문을 받아 **표현식 항 차이**와 **줄 차이**를 보고서로 만든다.
6. **참고 기준선(선택)**: Blizzard "보조 전투(Assisted Combat)" 우선순위도 simc에 미러링되어 있다 (`ActionPriorityLists/assisted_combat/hunter_survival.simc`) [확인 B-10]. 초보용 "간이 기준" 모드나 판정 비교용으로 같은 인터프리터에서 돌릴 수 있다. MVP에서는 쓰지 않는다.

---

## 4. WCL 연동

### 4.1 인증 [확인 B-32 스키마, 2차 B-33]

| 용도 | 방식 | 엔드포인트 |
|---|---|---|
| 공개·비공개 링크(unlisted) 리포트, 랭킹 | OAuth2 client credentials | 토큰 `https://www.warcraftlogs.com/oauth/token`, API `https://www.warcraftlogs.com/api/v2/client` |
| 내 비공개(private) 리포트 | Authorization Code + PKCE (클라이언트 생성 시 PKCE 체크) | 인가 `https://www.warcraftlogs.com/oauth/authorize`, API `https://www.warcraftlogs.com/api/v2/user` |

- client credentials 토큰 수명은 `expires_in: 31104000`(360일)로 관측됨 [2차]. 401이면 재발급한다.
- unlisted 리포트는 `report(code:, allowUnlisted: true)`로 client 토큰에서도 읽힌다 [확인 B-32].
- 약 2년 넘은 보관(archived) 리포트의 이벤트는 구독 + 사용자 인증이 필요하다 [확인 B-32 스키마 설명, 기간은 2차].
- **추천**: MVP는 client credentials만. 내 로그를 unlisted로 올리면 충분하다. PKCE는 M6 후반 선택 기능.

### 4.2 요청 한도

- 무료: **시간당 3,600점(클라이언트당)**, Gold 9,000, Platinum 18,000 [2차 B-31]. 별도로 분당 요청 상한(`x-ratelimit-limit: 800`)이 있다는 관측이 있다 [2차].
- 점수 계산식은 공개되지 않았다 [미확인]. 관측값: 요청당 1–2점 + 이벤트 페이지당 약 1점 [2차].
- `rateLimitData { limitPerHour pointsSpentThisHour pointsResetIn }`로 잔량을 확인한다 [확인 B-32].
- **예상 사용량**: 플레이어 1명 × 5분 전투 1회 = 캐시 없을 때 약 5–15점 [2차, 추정] → 무료 한도로 시간당 수백 회. 1인 사용에 충분하다.

### 4.3 필요한 쿼리

```graphql
# 1) 리포트 메타
query Meta($code: String!) {
  reportData { report(code: $code, allowUnlisted: true) {
    startTime
    archiveStatus { isArchived isAccessible }
    fights(killType: Encounters) { id encounterID name startTime endTime kill difficulty fightPercentage }
    masterData(translate: false) {
      actors { id name type subType petOwner gameID server }
      abilities { gameID name type }
    }
  } }
}

# 2) 대상 플레이어 이벤트 (페이지 반복: nextPageTimestamp가 null일 때까지)
query Ev($code: String!, $fid: Int!, $start: Float!, $end: Float!, $src: Int!) {
  reportData { report(code: $code, allowUnlisted: true) {
    events(fightIDs: [$fid], startTime: $start, endTime: $end, sourceID: $src,
           dataType: All, includeResources: true, limit: 10000, translate: false) {
      data nextPageTimestamp
    }
  } }
}
# + dataType: Buffs, sourceID: $src  → 그 플레이어에게 걸린 오라 (적용자 무관) [2차]
# + dataType: CombatantInfo          → 특성·장비·풀 시작 시 오라

# 3) 상위 로그 검색
query Top($enc: Int!, $page: Int!) {
  worldData { encounter(id: $enc) { name
    characterRankings(className: "Hunter", specName: "Survival", metric: dps,
                      difficulty: 5, page: $page)
  } }
}
# 결과 JSON: rankings[i].report.code, rankings[i].report.fightID, name, amount, duration …

# 4) 지역·보스 ID는 하드코딩하지 않고 조회
query { worldData { expansions { id name zones { id name frozen encounters { id name } } } } }
```

- `events`의 `limit`은 100–10000, 기본 300 [확인 B-32]. `startTime`만 주고 `endTime`을 빼면 빈 결과가 온다는 관측이 있으므로 항상 둘 다 보낸다 [2차].
- `includeResources: true`면 자원 필드가 이벤트에 평평하게 붙는다: `classResources[{amount,max,type,cost}]`, `hitPoints`, `x`, `y`(1/100야드), `facing`, `mapID`. `amount`는 **비용 차감 전** 값이다 [2차 B-34]. 로컬 로그와 의미가 같은지 S5에서 확인한다.
- `cast` 중 `fake: true`는 WCL이 파생시킨 시전이므로 시전 횟수에서 뺀다 [2차].
- `characterRankings`는 형식이 고정되지 않은 JSON 스칼라다 [확인 B-32]. 문자열·객체·`{error}` 모두 처리한다.
- `characterRankings`의 talents 형식은 `combatantinfo.talentTree`와 다르다 [2차]. 특성 판단은 항상 이벤트의 `combatantinfo`로 한다.

### 4.4 캐시와 이용 약관

- WCL API 약관(RPG Logs API Terms)은 자동 요청이 403(Cloudflare)이라 원문을 직접 확인하지 못했다 **[미확인]**. 커뮤니티 요약에 따르면 상업적 이용은 승인 필요, 한도 우회 금지(여러 자격 증명으로 할당량 늘리기 포함), 스크래핑·영구 데이터베이스 구축 금지다 [2차 B-35].
- **방침**: 요청은 사용자가 고른 리포트에 대해서만 한다. 캐시는 비교 작업용 단기 캐시(기본 14일, 설정 가능)로 두고 다른 플레이어 데이터를 모아 두는 기능은 만들지 않는다. **본 구현 전에 약관 원문을 브라우저로 직접 확인한다** ([결정 필요 D-9](#7-결정이-필요한-항목)).

---

## 5. Claude API 호출

### 5.1 모델별 역할

| 역할 | 모델 | 설정 | 입력 | 출력 |
|---|---|---|---|---|
| 빠른 요약 (풀 종료 자동) | `claude-haiku-5-5` | `output_config.effort: "low"`, 구조화 출력(JSON 스키마), 스트리밍 없음, `max_tokens` ~2,000 | `PullReport` 요약판 (≤ 6k 토큰) | 한국어 3–5줄 + 근거 ID |
| 상세 해설 (요청 시) | `claude-sonnet-5-5` (기본) | adaptive thinking, effort `medium`, 스트리밍, `max_tokens` ~16,000, 서버측 거절 대체(`fallbacks: "default"`, beta `server-side-fallback-2026-07-01`) | `PullReport` 전체 + 비교 결과 (≤ 30k 토큰) | 한국어 섹션형 해설 (마크다운) + 근거 ID |
| 상세 해설 (고급) | `claude-opus-5-5` | effort `medium` 명시 (기본값이 medium), 스트리밍, 서버측 거절 대체 | 위와 같음 | 위와 같음 |

- 모델 ID와 파라미터 규칙은 Claude API 문서 기준 [확인 B-40]. Opus 5.5는 thinking을 끌 수 없고 effort로만 조절한다. Haiku 5.5는 effort 기본값이 `medium`이므로 `low`를 명시한다 [확인 B-40].
- Haiku 5.5에는 서버측 거절 대체가 없다 [확인 B-40]. 게임 성능 요약에서 거절될 가능성은 낮지만, `stop_reason == "refusal"`이면 규칙 기반 요약만 표시한다.
- 빠른 요약에서 thinking을 끌지(effort `high` 이하에서 `disabled` 허용 [확인 B-40]) 켤지는 S6에서 지연·품질을 비교해 정한다.

### 5.2 프롬프트 구성과 캐싱

```
[tools: 없음]
[system]  ① 역할·규칙 (판정을 바꾸지 말 것, 입력에 없는 수치 금지, 근거 ID 필수)     ┐
          ② 채점 규칙 요약 (SCORING_SPEC 판정 분류·지표 정의)                    │ 정적 접두부
          ③ 생존 사냥꾼 용어집 ko (glossary_ko.yaml) + 한밤 생존 기본 개념          │ ← cache_control
          ④ 출력 형식 예시 1–2개                                               ┘
[user]    PullReport JSON (가변)
```

- **캐싱 사용: 예.** 정적 접두부(약 3–5k 토큰)는 최소 캐시 길이(이 모델들은 512 토큰 [확인 B-41])를 넘는다. 비용 이득은 작지만 첫 토큰 지연이 줄고 공짜에 가깝다.
- TTL: 기본 5분. 레이드 트라이 간격이 5분을 넘기는 경우가 많으면 1시간 TTL(쓰기 2배)로 바꾼다. 어느 쪽이든 월 비용 차이는 몇 센트 수준이다.
- **무효화 주의**: 접두부에 날짜·풀 ID 같은 가변 값을 넣지 않는다. JSON은 키 정렬 직렬화. 용어집·규칙 버전이 바뀌면 캐시가 새로 써지는 것은 정상이다. `usage.cache_read_input_tokens`로 적중 여부를 진단 탭에 표시한다.
- 상세 해설과 빠른 요약은 모델이 달라 캐시를 공유하지 않는다 (캐시는 모델별) [확인 B-41].

### 5.3 출력 검증 (FR-43)

- 빠른 요약 스키마 예: `{"headline": str, "points": [{"text": str, "refs": [str], "numbers": [number]}], "confidence_note": str|null}`.
- 검증기: `refs`의 ID(`dp:*`, `I*`, `cd:*`)가 입력에 있는지, `numbers`의 값이 입력 수치와 같은지(반올림 허용) 확인한다. 실패한 항목은 버리고 "검증 실패 1건"으로 표시한다.
- 상세 해설은 마크다운이므로, 본문의 `[dp:42]` 같은 인용 표기를 같은 방식으로 검사한다.

### 5.4 예상 비용 [가격: 확인 B-42, 토큰 수: 추정]

가격(USD/MTok): Haiku 5.5 입력 $0.10, 5분 캐시 쓰기 $0.125, 캐시 읽기 $0.01, 출력 $0.50 (프롬프트 10만 토큰 이하) · Sonnet 5.5 $2 / $2.50 / $0.10 / $10 · Opus 5.5 $4 / $5 / $0.20 / $20.

| 호출 | 가정 토큰 | 1회 비용 |
|---|---|---|
| Haiku 빠른 요약 (캐시 적중) | 정적 3k(읽기) + 가변 4k + 출력 1.2k | 3k×0.01 + 4k×0.10 + 1.2k×0.50 ≈ **$0.0010** |
| Haiku 빠른 요약 (캐시 쓰기) | 정적 3k(쓰기) + 가변 4k + 출력 1.2k | ≈ $0.0014 |
| Sonnet 상세 | 정적 5k(읽기) + 가변 25k + 출력 8k(thinking 포함) | 5k×0.10 + 25k×2 + 8k×10 ≈ **$0.13** |
| Opus 상세 | 같은 가정 | 5k×0.20 + 25k×4 + 8k×20 ≈ **$0.26** |

월간 예시: 레이드 주 3회 × 40풀 + 허수아비 주 50풀 ≈ 월 700풀 → Haiku 약 $0.7. 상세 해설 월 30회 → Sonnet 약 $4 / Opus 약 $8. **합계 월 $5–10 수준.** 작업공간 지출 한도를 월 $15–20으로 두면 키 유출 시 피해 상한도 같이 정해진다 (§6).

### 5.5 지연 목표와 측정

- 빠른 요약 p95 ≤ 8 s (목표 5 s). S6에서 effort·thinking 설정별로 측정한다. 지연이 길면 입력을 줄인다(상위 패턴 3개 + 지표만).
- 상세 해설은 스트리밍으로 첫 토큰 ≤ 5 s.

### 5.6 전송 데이터 범위

- 보내는 것: 엔진의 구조화 결과(수치, 판정, 스킬 key, 보스 이름, 영웅 특성).
- 보내지 않는 것: 원본 로그 줄, GUID, 다른 플레이어 이름(비교 대상은 "비교 플레이어"로 익명화), 서버·길드명.

---

## 6. API 키 로컬 저장 보안 검토

> 사용자 질문: "혼자 쓸 건데 개인 API 키를 로컬 설정에 저장하는 게 보안에 문제 있는지"

### 6.1 결론

**개인 PC에서 혼자 쓰는 경우, 키를 로컬에 두는 것 자체는 일반적이고 받아들일 수 있는 수준이다.** 다만 **평문 설정 파일은 권하지 않는다.** 실제 위험은 "로컬에 있다"는 것보다 **다른 곳으로 새는 경로**(Git 커밋, OneDrive 등 클라우드 동기화, 백업, 화면 공유, 로그 출력)에서 온다. 그래서 다음 세 가지를 같이 적용한다.

1. 키는 **Windows 자격 증명 관리자**에 저장한다 (Python `keyring`의 Windows 백엔드).
2. 이 앱 전용 키를 **별도 작업공간(Workspace)**에서 만들고 **월 지출 한도**를 건다.
3. 저장소에는 비밀 값이 들어갈 길을 막는다 (`.gitignore`, 커밋 전 비밀 스캔).

### 6.2 저장 방식 비교

| 방식 | 디스크에 평문? | Git 커밋·클라우드 동기화로 샐 위험 | 같은 사용자 권한의 악성 프로그램 | 평가 |
|---|---|---|---|---|
| 설정 파일(TOML)에 평문 | 예 | 높음 (`Documents`가 OneDrive 동기화되는 경우가 흔함, 실수로 저장소에 복사) | 바로 읽힘 | 비추천 |
| 환경 변수(사용자 변수) | 레지스트리에 평문 | 중간 | 바로 읽힘, 모든 자식 프로세스에 상속 | 개발 중 임시로만 |
| `.env` 파일 | 예 | 높음 (`.gitignore` 필수) [확인 B-43] | 바로 읽힘 | 비추천 |
| **Windows 자격 증명 관리자 (`keyring`)** | 아니오 (DPAPI 암호화) | 낮음 (파일 동기화·커밋 경로에 없음) | **읽힘** (아래 참고) | **추천** |
| DPAPI로 직접 암호화한 파일 | 아니오 | 낮음 | 읽힘 | 추천안과 동급, 직접 구현 필요 |

- `keyring`의 Windows 백엔드는 자격 증명 관리자에 암호화해 저장한다 [2차 B-44].
- DPAPI는 "같은 로그온 자격 증명을 가진 사용자"만 복호화할 수 있고 보통 같은 컴퓨터에서만 가능하다 [확인 B-45]. 그러므로 **디스크를 떼어가거나 파일이 복사돼 나가도 키를 못 읽는다**는 점이 평문 파일보다 낫다.
- 한계: **같은 Windows 계정으로 실행되는 다른 프로그램(악성 코드 포함)은 자격 증명 관리자 값을 읽을 수 있다** (DPAPI가 사용자 단위 보호이기 때문, B-45 문구에서 도출 [추론]). 이건 어떤 로컬 저장 방식으로도 완전히 막을 수 없다. 그래서 피해 상한을 지출 한도로 묶는 것이 실질적인 방어다.

### 6.3 추가 조치

| 조치 | 근거 |
|---|---|
| 앱 전용 작업공간 + 월 지출 한도 (예: $20). 한도에 닿으면 요청이 400 오류로 막힌다 | 작업공간별 지출 한도 설정 가능, 조직 한도보다 낮게만 설정 가능 [확인 B-46, B-47] |
| 키는 앱 전용으로 하나만, 이름을 붙여 관리. 정기 교체(예: 90일), 유출 의심 시 즉시 Console에서 삭제 | Anthropic 키 관리 권장사항 [확인 B-43] |
| 공개 저장소에 노출된 Claude 키는 GitHub 비밀 스캔으로 탐지되어 자동 비활성화된다. 그래도 커밋 자체를 막는 것이 우선 | [확인 B-43] |
| 저장소: `.gitignore`에 `*.env`, `config.local.*`, `secrets*`. 커밋 전 `gitleaks` 실행 | [확인 B-43] 권장 |
| 앱 로그·진단 화면에 키를 출력하지 않음. HTTP 디버그 로그에서 `x-api-key`, `Authorization` 헤더 마스킹 | NFR-S1 |
| WCL client secret, WCL 사용자 refresh token도 같은 방식으로 자격 증명 관리자에 저장 | 같은 위협 모델 |
| 제어판의 "키 입력" 화면은 붙여넣기 후 마스킹 표시, 확인 호출(`GET /v1/models` 1회)로 검증 | — |

---

## 7. 결정이 필요한 항목

| ID | 항목 | 추천 |
|---|---|---|
| D-1 | 언어·오버레이: Python + PySide6 | 추천안 승인 |
| D-2 | APL 처리: 혼합안(C) | 추천안 승인 |
| D-7 | 빠른 요약 thinking 끄기 여부 | S6 측정 후 결정 |
| D-8 | 캐시 TTL 5분/1시간 | 5분으로 시작 |
| D-9 | WCL API 약관 원문 확인 (사용자가 브라우저로) | M6 착수 전 필수 |

---

## 부록 A. 전투 로그 포맷 요약

> 이 부록은 설계 가정을 정리한 것이다. 출처끼리 다르게 말하는 부분이 있어 **최종 레이아웃은 S2에서 실제 12.x 로그로 확정**한다.

### A.1 파일과 헤더

| 항목 | 내용 | 신뢰도 |
|---|---|---|
| 위치 | `World of Warcraft\_retail_\Logs\` | [확인 B-5] |
| 켜기 | `/combatlog` 또는 `LoggingCombat(true)`. 고급 데이터는 CVar `advancedCombatLogging 1` (설정 > 시스템 > 네트워크 > 고급 전투 기록) | [확인 B-5], [2차 B-6] |
| 파일 이름 | `WoWCombatLog-*.txt`처럼 타임스탬프가 붙은 이름이 쓰인다 (외부 미터가 이 패턴을 읽음). 정확한 패턴(`MMDDYY_HHMMSS` 등)과 새 파일이 생기는 조건(토글마다/게임 실행마다)은 **[미확인]** | [2차 B-7] |
| 자동 로깅 | 기본 설정으로는 확인 못 함 [미확인]. `LoggingCombat`을 부르는 애드온(예: RaidLogAuto, Interface 120005)은 12.x에서도 동작한다고 보고됨 | [2차 B-8] |
| 헤더 | `COMBAT_LOG_VERSION,<n>,ADVANCED_LOG_ENABLED,<0/1>,BUILD_VERSION,<x.y.z>,PROJECT_ID,1` (1 = 리테일). 예전 예: `COMBAT_LOG_VERSION,19,…,BUILD_VERSION,9.1.5,PROJECT_ID,1` | [확인 B-5] |
| 현재 버전 | 11.x·12.x 모두 `COMBAT_LOG_VERSION,22`로 보고됨 | [2차 B-6] |
| 헤더 재등장 | 로깅이 다시 시작되면 파일 중간에 헤더가 다시 나옴 → 상태 초기화 | [2차 B-6] |

**설계 결론**: 디렉터리를 감시해 가장 최신 `WoWCombatLog*.txt`를 따라간다. 파일 이름 패턴에 의존하지 않는다.

### A.2 줄 형식

```
5/8/2026 21:47:12.841-5  SPELL_DAMAGE,Player-1168-0A234B,"Name-Realm",0x514,0x0,<dest…>,<spellId>,"<spellName>",0x1,<advanced…>,<suffix…>
```

| 부분 | 내용 | 신뢰도 |
|---|---|---|
| 타임스탬프 | `M/D/YYYY H:MM:SS.fff` + 정수 UTC 오프셋(양수는 부호 없음). 0 채움 없음. 예전 형식은 `MM/DD HH:MM:SS.fff`(연도·오프셋 없음) | 현재 형식 [2차 B-6], 예전 형식 [확인 B-5] |
| 구분 | 타임스탬프와 본문 사이 공백 2개(가끔 탭) | [2차 B-6] |
| 기본 필드 | event, sourceGUID, sourceName, sourceFlags, sourceRaidFlags, destGUID, destName, destFlags, destRaidFlags | [확인 B-5] |
| 주문 접두 | `SPELL_`/`RANGE_`/`SPELL_PERIODIC_`: spellId, "spellName"(클라이언트 언어), school | [확인 B-5] |
| 고급 블록 | 위키: infoGUID, ownerGUID, curHP, maxHP, AP, SP, armor, absorb, powerType, curPower, maxPower, powerCost, posX, posY, uiMapID, facing, level(플레이어는 아이템 레벨). 12.x 기준 다른 자료는 absorb 뒤에 항상 0인 필드 2개가 더 있고 powerCost가 1/10 단위라고 함. 자원이 여럿이면 `|`로 연결 | 위키 [확인 B-5], 12.x 변형 [2차 B-6] — **불일치, S2에서 확정** |
| 고급 블록 대상 | `SPELL_CAST_SUCCESS`: 시전자. `SPELL_DAMAGE`·`SPELL_PERIODIC_DAMAGE`·`RANGE_DAMAGE`·`SPELL_HEAL`·`SPELL_ENERGIZE`·`SPELL_DRAIN` 등: 대상. `SWING_DAMAGE`: 공격자. 없음: `SPELL_CAST_START`, `SPELL_CAST_FAILED`, 오라 이벤트, `SPELL_SUMMON`, `SPELL_EMPOWER_*` | [2차 B-6] |
| 시전 | 즉시 시전은 `SPELL_CAST_START` 없이 `SPELL_CAST_SUCCESS`만. `SPELL_CAST_FAILED`는 클라이언트 언어의 실패 사유 문자열("Not yet recovered", "Out of range" 등)을 붙임. 로깅하는 플레이어 자신의 실패만 기록된다는 것은 [미확인] | [2차 B-6, B-9] |
| 오라 | `SPELL_AURA_APPLIED/REMOVED/REFRESH`: + `BUFF`/`DEBUFF` + 선택적 수치(보호막 흡수량, 중첩 아님). `SPELL_AURA_APPLIED_DOSE/REMOVED_DOSE`: + 유형 + 중첩 수 | [확인 B-5], [2차 B-6] |
| 자원 | `SPELL_ENERGIZE`: amount, overEnergize, powerType, maxPower | [2차 B-6] |
| COMBATANT_INFO | `ENCOUNTER_START`·`CHALLENGE_MODE_START` 뒤 플레이어마다 1회 (일반 전투에는 없음). GUID, 진영, 능력치, 12.0에서 index 7에 새 필드, 전문화 ID(12.x에서 index 25), 특성 `[(nodeId, entryId, rank),…]`, PvP 특성, 장비, 오라 | 기록 시점 [확인 B-5], 필드 위치 [2차 B-6] |
| 전투 경계 | `ENCOUNTER_START,id,"name",difficulty,groupSize,instanceId` / `ENCOUNTER_END,id,"name",difficulty,groupSize,success,durationMs` / `CHALLENGE_MODE_*` / `ZONE_CHANGE` / `MAP_CHANGE` / `UNIT_DIED` | [확인 B-5] |
| 펫 | `SPELL_SUMMON`이 소유 관계의 주 신호. 로깅 전에 소환된 펫은 고급 블록의 ownerGUID로 판단 | [2차 B-6] |
| 쿨다운·충전 | 쿨다운 초기화나 충전 변화를 직접 나타내는 이벤트는 없음 | [2차 B-6, 추정] |

**설계 결론**: 주문은 ID로만 식별(이름은 한국어로 기록됨). 실패 사유는 언어별 문자열이므로 한국어·영어 사전을 두고, 모르는 문자열은 "기타 실패"로 처리한다.

### A.3 기록(flush) 동작

| 사실 | 출처 | 신뢰도 |
|---|---|---|
| Blizzard(Kaivax, 2023-08-21): "We intend to make changes to how the Advanced Combat Log is populated, in advance of Dragonflight Season 3" — 레이드 오버레이에 쓰이지 못하게 하려는 목적, EULA 1-C 언급 | B-4b, B-4 | [확인] |
| 10.2부터 전투 중 이벤트를 메모리에 두고 **전투 종료 시 한 번에 기록**. 기록된 이벤트 순서가 섞일 수 있고, 전투 중 크래시·`/reload` 시 해당 데이터 손실, 일괄 기록 시 순간 끊김 가능 | B-1, B-2, B-2b | [2차] — 한밤 12.x에서 그대로인지 **[미확인]** |
| WCL 도움말(오래된 문구): "레이드 밖에서는 일정 개수의 이벤트가 쌓여야 파일에 기록된다" | B-7b | [확인, 단 10.2 이전 문구일 수 있음] |
| 2025-08 개발자 보고: 파일에 반영되기까지 "수 분"의 지연 | B-3 | [확인, 사용자 보고] |
| 버퍼 크기, 기록 주기, 이를 바꾸는 CVar | — | [미확인] (찾지 못함) |

**설계 결론**: 전투 종료 시 대량 배치 도착을 기본으로 가정하고([ARCHITECTURE 원칙 5](ARCHITECTURE.md#1-설계-원칙)), 실제 동작(인스턴스 안/밖, 허수아비, 레이드)은 S1에서 측정한다. 기록을 앞당기는 우회는 하지 않는다 (REQUIREMENTS C-6).

### A.4 한밤(12.0) 변경점

| 사실 | 출처 | 신뢰도 |
|---|---|---|
| 12.0.0부터 애드온이 `COMBAT_LOG_EVENT(_UNFILTERED)`를 등록하면 `ADDON_ACTION_FORBIDDEN`. 전투 정보는 "비밀 값"으로만 제공 | B-5c | [확인] |
| 이후 제한은 활성 레이드 전투·쐐기 진행 중으로 좁혀짐 (2025-10-03 발표) | B-5d | [2차] |
| 로그 파일 자체(`/combatlog`, 고급 전투 기록, 외부 도구로 내보내기)는 변경 없음이라고 발언했다는 보도 | B-5e | [2차, 원문 미확인] |
| 12.x에서 파일을 지연·제한·난독화하겠다는 계획은 찾지 못함 | — | [미확인 = 찾지 못함] |
| 게임 디렉터 글(Hazzikostas): "Addons should no longer offer a competitive advantage in WoW combat", 애드온이 전투 정보를 처리해 "combat decisions and recommendations"를 내는 것을 막는 것이 목적. 게임 밖 프로그램·전투 로그 파일은 언급 없음 | B-5f | [확인] |
| 고급 로그의 치유량이 게임 UI보다 낮게 기록된다는 사용자 보고 (생존 채점에는 영향 적음) | B-5g | [사용자 보고] |

### A.5 창 모드

- 독점 전체 화면은 8.0 사전 패치(2018)에서 제거되고 창 모드와 "창 모드(전체 화면)"(borderless)만 남았다 [확인 B-26b]. 12.x에서 다시 생겼다는 자료는 없다 [2차, 부재 근거].

## 부록 B. 출처

확인 날짜는 모두 2026-10-16.

**전투 로그·정책**
- B-1 Wowhead, "Combat Log Changes with Patch 10.2 - Measures to Prevent Out of Game Overlays" (2023-11-06) — https://www.wowhead.com/news/combat-log-changes-with-patch-10-2-measures-to-prevent-out-of-game-overlays-335813 (본문은 자동 조회로 읽지 못했고 제목·게시 정보만 확인)
- B-2 WowCarry, "WoW Patch 10.2 Combat Log Change: How Blizzard Stopped Overlays" — https://wowcarry.com/blog/wow/patch-102-introduces-updates-to-combat-logs-measures-against-out-of-game-overlays (2차, "전투 중 메모리 보관 후 전투 종료 시 일괄 기록" 주장)
- B-3 Blizzard 포럼, "WoW Combat Log Delay – Seeking API or Workaround" (2025-08-28) — https://us.forums.blizzard.com/en/blizzard/t/wow-wow-combat-log-delay-%E2%80%93-seeking-api-or-workaround/55869 ("수 분의 지연" 보고)
- B-4 Yahoo Tech, "WoW's UI arms race rages…" (2023-08-22) — https://tech.yahoo.com/gaming/articles/wows-ui-arms-race-rages-132338676.html (Blizzard가 EULA 1.C를 근거로 고급 전투 로그 실시간 이용을 막겠다는 취지 보도)
- B-4b Blizzard 포럼 Kaivax 블루 포스트 (2023-08-21, "Nerfing Combat Logs: Will It Happen? Should It Happen?") — https://us.forums.blizzard.com/en/wow/t/1654695/11 · MMO-Champion 요약 — https://www.mmo-champion.com/content/11654-Advanced-Combat-Log-Changes-Coming-to-Prevent-Overlays
- B-2b mein-mmo, 10.2 전투 로그 변경 기사 — https://mein-mmo.de/wow-kleiner-trick-gegen-addons-und-programme/
- B-5 warcraft.wiki.gg COMBAT_LOG_EVENT — https://warcraft.wiki.gg/wiki/COMBAT_LOG_EVENT
- B-5c warcraft.wiki.gg Patch 12.0.0/API changes — https://warcraft.wiki.gg/wiki/Patch_12.0.0/API_changes · Planned API changes — https://warcraft.wiki.gg/wiki/Patch_12.0.0/Planned_API_changes
- B-5d Icy Veins, "Combat addon restrictions eased in Midnight" — https://www.icy-veins.com/wow/news/combat-addon-restrictions-eased-in-midnight/
- B-5e boosting-ground (Hazzikostas 발언 인용 보도) — https://boosting-ground.com/wow-boosting/news/midnight-addon-ban
- B-5f Blizzard News, Ion Hazzikostas, "Combat Philosophy and Addon Disarmament in Midnight" — https://news.blizzard.com/en-us/article/24246290/combat-philosophy-and-addon-disarmament-in-midnight
- B-5g Blizzard EU 포럼, 고급 로그 치유량 불일치 — https://eu.forums.blizzard.com/en/wow/t/healing-data-mismatch-in-game-uiaddons-vs-advanced-combat-log-in-midnight/612267
- B-6 WowCoach 전투 로그 명세(2026-10-10 갱신) — https://wowcoach.gg/docs/combat-log/spec.yaml · https://wowcoach.gg/docs/combat-log/line-format · https://wowcoach.gg/blog/wow-combat-log-format-complete-field-reference · https://wowcoach.gg/blog/how-to-enable-combat-logging-wow (3자 자료, 2차)
- B-7 wowdps (외부 미터, `WoWCombatLog-*.txt` 읽기) — https://github.com/kriswill/wowdps · 고급 블록 해석 차이 — https://github.com/kriswill/wowdps/pull/92
- B-7b Warcraft Logs 도움말 — https://www.warcraftlogs.com/help/start (자동 조회 차단, 검색 요약으로만 확인)
- B-8 RaidLogAuto — https://github.com/Xerrion/RaidLogAuto
- B-9 SPELL_CAST_FAILED 샘플 로그 — https://pastebin.com/NhRB2vZL
- B-26b DSOGaming, WoW DX12 지원·독점 전체 화면 제거 — https://www.dsogaming.com/news/world-of-warcraft-now-supports-directx-12-does-no-longer-support-fullscreen-exclusive-mode/

**SimC·APL**
- B-10 simc `midnight` 브랜치 `ActionPriorityLists/default/hunter_survival.simc` (HEAD 76f8118c, 2026-10-15) — https://raw.githubusercontent.com/simulationcraft/simc/midnight/ActionPriorityLists/default/hunter_survival.simc · Assisted Combat 미러: `ActionPriorityLists/assisted_combat/hunter_survival.simc`
- B-11 simc `SpellDataDump/hunter.txt`, `engine/class_modules/sc_hunter.cpp` (midnight, 데이터 12.1.5.70391) — https://github.com/simulationcraft/simc/tree/midnight
- B-12 simc git log (생성 파일·`sv.txt`·`apl_hunter.cpp` 커밋 이력, 2026-04~10)
- B-13 Hekili README ("Goodbye… ended with the launch of the Midnight prepatch, version 12.0, on January 20th 2026") — https://github.com/Hekili/hekili
- B-14 Hekili `thewarwithin` 브랜치 `TheWarWithin/HunterSurvival.lua`, `Scripts.lua`(SimToLua), `State.lua` — https://github.com/Hekili/hekili
- B-15 hero-rotation-generator (Python APL 파서, 마지막 커밋 2020-05-02) — https://github.com/herotc/hero-rotation-generator
- B-16 SimC 위키 "Action List Conditional Expressions" — https://github.com/simulationcraft/simc/wiki/Action-List-Conditional-Expressions

**오버레이**
- B-20 qtbase `src/plugins/platforms/windows/qwindowswindow.cpp` (dev) — https://raw.githubusercontent.com/qt/qtbase/dev/src/plugins/platforms/windows/qwindowswindow.cpp · B-20b QtCentre 스레드(setWindowFlags 재생성) — https://www.qtcentre.org/threads/72127-(PyQt)-setWindowFlag-without-hiding-window
- B-21 qtbase `qwindowsbackingstore.cpp` — https://raw.githubusercontent.com/qt/qtbase/dev/src/plugins/platforms/windows/qwindowsbackingstore.cpp · B-21b Qt High DPI — https://doc.qt.io/qt-6/highdpi.html
- B-22 Microsoft, Window Features / Extended Window Styles / SetWindowPos — https://learn.microsoft.com/en-us/windows/win32/winmsg/window-features · https://learn.microsoft.com/en-us/windows/win32/winmsg/extended-window-styles · https://learn.microsoft.com/en-us/windows/win32/api/winuser/nf-winuser-setwindowpos
- B-23 pythonguis, 패키지 크기 FAQ — https://www.pythonguis.com/faq/packaged-installer-file-sizes/ · PyInstaller 오탐 — https://discuss.python.org/t/pyinstaller-false-positive/43171
- B-24 Electron BaseWindow 옵션 / BrowserWindow — https://www.electronjs.org/docs/latest/api/structures/base-window-options · https://www.electronjs.org/docs/latest/api/browser-window
- B-25 Electron `native_window_views_win.cc` (setIgnoreMouseEvents, forward 시 WH_MOUSE_LL) — https://github.com/electron/electron/tree/main/shell/browser
- B-26 Guru3D, WoW DX12 지원 — https://guru3d.com/story/world-of-warcraft-now-supports-directx-12
- B-27 Microsoft, "For best performance, use DXGI flip model" — https://learn.microsoft.com/en-us/windows/win32/direct3ddxgi/for-best-performance--use-dxgi-flip-model
- B-28 electron-overlay-window (Awakened PoE Trade) — https://github.com/SnosMe/electron-overlay-window
- B-29 Tauri 이슈 #9250, #11461 — https://github.com/tauri-apps/tauri/issues/9250
- B-30 Better Stack, Tauri vs Electron 비교 — https://betterstack.com/community/guides/scaling-nodejs/tauri-vs-electron-vs-deno-vs-electrobun/

**WCL** (warcraftlogs.com 문서는 자동 조회 시 403이라 아래 2차 자료와 스키마로 확인)
- B-31 요청 한도 실측 노트 — https://raw.githubusercontent.com/Dudesons/wowperf/HEAD/.claude/skills/wcl-api/SKILL.md · https://raw.githubusercontent.com/TheDastard/KhadBot/HEAD/docs/wcl-api.md · https://github.com/Erilla/SlashWho/pull/281
- B-32 WCL GraphQL 스키마 (내부 조회로 커밋된 사본) — https://raw.githubusercontent.com/math280h/go-wcl/main/schema/schema.graphql
- B-33 WCL 포럼 (PKCE, API v2 정보) — https://forums.combatlogforums.com/t/401-unauthorized-pkce-code-flow/10701 · https://forums.combatlogforums.com/t/api-v2-info-documentation/9975 · warcraft_cli 문서 — https://github.com/aurokin/warcraft_cli/blob/main/docs/warcraftlogs/README.md
- B-34 이벤트 모델 타입 — https://raw.githubusercontent.com/gpolcode/warcraft-learner/HEAD/frontend/src/app/domains/raid-analysis/data/wcl/wcl.models.ts
- B-35 RPG Logs API 약관 (원문 403, 미확인) — https://articles.warcraftlogs.com/help/rpg-logs-api-terms-of-service

**Claude API·보안**
- B-40 Claude API 레퍼런스(모델·thinking·effort·fallbacks 규칙), Claude Code `claude-api` 스킬 문서 2026-10-06 캐시 + https://platform.claude.com/docs/en/about-claude/models/overview
- B-41 Prompt caching — https://platform.claude.com/docs/en/build-with-claude/prompt-caching
- B-42 Pricing — https://platform.claude.com/docs/en/about-claude/pricing (2026-10-16 조회: Sonnet 5.5 캐시 읽기 $0.10/MTok)
- B-43 Anthropic, "API Key Best Practices" — https://support.claude.com/en/articles/9767949-api-key-best-practices
- B-44 Python keyring Windows 백엔드 (WinVaultKeyring 소스) — https://gemfury.com/duality-group/python:keyring/-/content/backends/Windows.py
- B-45 Microsoft, CryptProtectData — https://learn.microsoft.com/en-us/windows/win32/api/dpapi/nf-dpapi-cryptprotectdata
- B-46 Claude Docs, Workspaces — https://platform.claude.com/docs/en/manage-claude/workspaces
- B-47 Claude Docs, Rate limits (지출 한도 도달 시 400) — https://platform.claude.com/docs/api/rate-limits
