# RotationCoach 기획 문서

WoW 한밤(12.x) 생존 사냥꾼 로테이션 채점 오버레이의 기획·설계 문서 모음. **기획 단계이며 승인 전 본 구현 코드는 없다.**

| 순서 | 문서 | 내용 |
|---|---|---|
| 1 | [REQUIREMENTS.md](REQUIREMENTS.md) | 확정 전제, 기능·비기능 요구사항, ToS 제약, 범위 밖 |
| 2 | [ARCHITECTURE.md](ARCHITECTURE.md) | 모듈 구성, 데이터 흐름, 주요 스키마, 같은 엔진으로 로컬·WCL 처리 |
| 3 | [TECH_DECISIONS.md](TECH_DECISIONS.md) | 언어·오버레이·APL·WCL·Claude 선택 비교, API 키 보안 검토, 로그 포맷 부록, 출처 |
| 4 | [SCORING_SPEC.md](SCORING_SPEC.md) | GCD 판정 규칙, 허용 오차, 점수 산식, 오버레이 지표, 추적 불가 요소 처리 |
| 5 | [RISKS.md](RISKS.md) | 기술·정책 리스크와 대응 |
| 6 | [SPIKES.md](SPIKES.md) | 본 개발 전 검증 실험과 성공 기준 (스크립트는 승인 후 작성) |
| 7 | [ROADMAP.md](ROADMAP.md) | 마일스톤, 완료 기준, 회귀 테스트, 폴더 구조, **결정 필요 항목 전체 목록** |

출처 표기: **[확인]** 1차 출처 · **[2차]** 2차 출처 · **[미확인]** 확인 못 함/추정. 출처 목록은 [TECH_DECISIONS 부록 B](TECH_DECISIONS.md#부록-b-출처)와 [RISKS 추가 출처](RISKS.md#추가-출처).
