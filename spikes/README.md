# 스파이크 실행 안내

기획 문서: [docs/SPIKES.md](../docs/SPIKES.md). 이 폴더의 코드는 **검증용 일회성 코드**이며 본 구현에 그대로 쓰지 않습니다.
모든 스크립트는 **읽기 전용**입니다. 게임에 입력을 보내거나 게임 프로세스·메모리에 접근하지 않습니다.

| 스크립트 | 스파이크 | 어디서 | 상태 |
|---|---|---|---|
| `s1_log_latency.py` | S1 기록 지연 + S7 tail 검증 | 🧑 Windows + WoW | 준비됨 (가짜 작성기로 검증 완료) |
| `s2_inventory.py` | S2 상태 재구성 가능성 | 🧑 녹화 → 🧑/🤖 분석 | 준비됨 (합성 로그로 검증 완료) |
| `anonymize_log.py` | 로그 익명화 (공유 전 필수) | 🧑 | 준비됨 |
| `s3_overlay.py` | S3 오버레이 | 🧑 Windows + WoW | 준비됨 (오프스크린 렌더 확인, Win32 부분은 Windows에서 확인 필요) |
| `s4_apl_parse.py` | S4 APL 파싱 | 🤖 | **완료** → [results/S4.md](results/S4.md) |

## 0. 준비 (한 번만)

1. **uv 설치** (Python 설치·가상환경 관리 도구). PowerShell에서:
   ```powershell
   powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
   ```
   새 터미널을 열고 `uv --version`이 나오면 됩니다. uv가 Python 3.12+를 알아서 받아 씁니다.
2. 저장소를 받습니다: `git clone https://github.com/godoriii/RotationCoach` → `cd RotationCoach` → `git checkout claude/friendly-mendel-m6ujoa`
3. WoW 설정: **설정 > 시스템 > 네트워크 > "고급 전투 기록" 켜기**. 디스플레이 모드는 평소대로 "창 모드(전체 화면)".
4. 아래 명령의 `LOGS`는 본인 경로로 바꿉니다. 기본값 예:
   ```powershell
   $LOGS = "C:\Program Files (x86)\World of Warcraft\_retail_\Logs"
   ```

## 1. 게임 세션 1회로 S1 + S7 + S2 녹화 (약 1–2시간)

터미널 하나에서 기록기를 켜 둡니다 (`--mirror`는 S7 검증용):

```powershell
uv run spikes/s1_log_latency.py record --logs $LOGS --out spikes/results/s1_session1 --mirror
```

- 이 터미널에 **라벨을 입력하고 Enter**를 치면 그 순간이 표시됩니다. 전투 직전 `start dummy1`, 전투에서 빠진 직후 `end dummy1`처럼 `start 이름` / `end 이름` 짝으로 입력해 주세요. 게임 안에서 할 일은 평소처럼 `/combatlog`로 기록을 켜는 것뿐입니다.
- 끝낼 때는 이 터미널에서 `Ctrl+C`.

### 게임 안 순서

| # | 할 일 | 터미널 라벨 | 확인 대상 |
|---|---|---|---|
| 1 | `/combatlog` 켜기 (채팅에 "전투 기록 중" 확인) | — | 새 파일 생성 (S7) |
| 2 | 도시 허수아비 60초 공격 → 전투 이탈 → 30초 대기. **3회** 반복 | `start dummyA1` / `end dummyA1` … | S1-A |
| 3 | 허수아비 5분 공격 (평소 로테이션) | `start dummy5m` / `end dummy5m` | S1-B, S2-1 |
| 4 | Kill Command만 30초 연타 (충전 다 쓰고 회복 대기 반복) | `start kc` / `end kc` | S2-2 충전 모델 |
| 5 | Wildfire Bomb을 쿨이 돌아오는 즉시 사용 60초 (키를 계속 눌러도 됨), 나머지 GCD는 평소대로 | `start wfb` / `end wfb` | S2-3 감소 효과 |
| 6 | Boomstick 정신 집중 중 이동 1회 | `boomstick move` | S2-4 |
| 7 | 사거리 밖에서 Raptor Strike 시도 몇 번 | `out of range` | S2-5 실패 사유 |
| 8 | 허수아비 30초 공격 중 `/reload` | `start reload` / `end reload` | S1-E 데이터 손실 |
| 9 | `/combatlog` 끄기 → 다시 켜기. **3회** | `toggle` | S7 파일 교체 |
| 10 | 던전(추종자 던전 가능) 보스 1회 + 잡몹 1구간 | `start dungeonboss` / `end dungeonboss` | S1-C, S2-6 `COMBATANT_INFO` |
| 11 | (가능하면) 레이드 보스 1회 (공격대 찾기 이상) | `start raidboss` / `end raidboss` | S1-D |
| 12 | 게임 종료 → 재실행 → `/combatlog` 켜고 허수아비 10초 | `restart` | S7 재시작 |
| 13 | 영웅 특성을 바꿔(무리의 지도자 ↔ 파수꾼) 3–5번을 한 번 더 | `start dummy5m-other` … | 두 영웅 특성 |

### 기록 후

```powershell
# S1 보고서 (spikes/results/s1_session1/report.md 생성)
uv run spikes/s1_log_latency.py analyze spikes/results/s1_session1
# S7: 읽은 바이트가 실제 파일과 같은지
uv run spikes/s1_log_latency.py verify spikes/results/s1_session1 --logs $LOGS
# S2: 녹화된 로그마다 (파일 이름은 Logs 폴더에서 확인)
uv run spikes/anonymize_log.py "$LOGS\WoWCombatLog-XXXXXX_XXXXXX.txt" spikes/results/S2_session1.anon.txt --me "내캐릭이름"
uv run spikes/s2_inventory.py spikes/results/S2_session1.anon.txt --player Me --out spikes/results/S2_session1.md
```

### 저에게 넘겨줄 것

- `spikes/results/s1_session1/` 안의 `report.md`, `chunks.csv`, `markers.csv`, `events.csv`, `meta.json` (`mirror/` 폴더는 원본 로그 사본이라 **넘기지 않습니다**)
- `verify` 출력 결과 (복사해서 붙여넣기)
- `spikes/results/S2_*.anon.txt` (익명화된 로그)와 `S2_*.md`
- 넘기는 방법: 이 브랜치에 커밋·푸시하거나 대화에 첨부. `.map.txt`(익명 대응표)는 `.gitignore`에 들어 있어 커밋되지 않습니다.
- 수치 외에 눈으로 본 것도 적어 주세요: 전투 종료 순간 끊김이 있었는지, `/reload` 후 데이터가 남았는지 등.

## 2. S3 오버레이 (약 1시간)

```powershell
uv run --with PySide6 spikes/s3_overlay.py                 # 왼쪽 위에 표시
uv run --with PySide6 spikes/s3_overlay.py --x 1500 --y 900 --screen 0
uv run --with PySide6 spikes/s3_overlay.py --check         # 창 스타일만 출력하고 종료
```

- 실행하면 콘솔에 `extended style: ... LAYERED|TRANSPARENT|NOACTIVATE|TOOLWINDOW|TOPMOST`, `required present: True`가 나와야 합니다. 10초마다 `foreground_is_overlay=False`(포커스를 가져가지 않음)를 출력합니다.
- 종료는 콘솔에서 `Ctrl+C` (오버레이는 클릭·포커스가 안 되는 것이 정상입니다).
- 확인 항목 9개는 [docs/SPIKES.md S3](../docs/SPIKES.md#s3-창-모드전체-화면-wow-위-클릭-통과-오버레이) 표를 따라 주세요. 성능은 [PresentMon](https://github.com/GameTechDev/PresentMon)으로 같은 장소에서 2분씩 오버레이 있음/없음 3회 측정합니다.
  ```powershell
  PresentMon.exe --process_name Wow.exe --timed 120 --terminate_after_timed --output_file spikes\results\s3_on_1.csv
  ```
- 결과는 체크리스트 통과 여부와 PresentMon CSV를 넘겨 주세요.

## 문제가 생기면

- `uv`가 PySide6를 못 받으면: `uv run --python 3.12 --with PySide6 ...`로 버전을 고정해 보세요.
- `record`가 "following ..."을 출력하지 않으면 `--logs` 경로가 틀린 것입니다 (`WoWCombatLog*.txt`가 있는 폴더).
- 백신이 스크립트를 막으면 알려 주세요 (스크립트는 파일 읽기 외에 아무것도 하지 않습니다).

## 데이터 출처

`spikes/data/*.simc`는 [SimulationCraft](https://github.com/simulationcraft/simc)(GPL-3.0)의 `ActionPriorityLists/default/hunter_survival.simc` 사본입니다. 파일 이름의 `@` 뒤가 커밋 해시입니다 (`76f8118c` = midnight, `4588b135` = thewarwithin).
