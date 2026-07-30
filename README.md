# PSP Localization Toolkit

PSP 게임의 **비파괴 분석 → 번역 QA → 게임별 구조 비교 → 폰트/리소스 빌드 → 보고서 생성**을 한 번에 처리하는 통합 도구다. 프리니 1은 첫 번째 실전 프로필이고, 프리니 2는 같은 엔진을 재사용할 수 있는지 자동으로 판정한다.

SRW-F/PS1 전용 기능은 포함하지 않는다. 참고 HTML에서는 번역 목록, 바이트 용량 표시, 코드맵, 저장 전 검사 같은 작업 흐름만 참고했다.

## 가장 쉬운 실행

프로젝트 루트에 다음 파일을 둔다.

```text
game.iso     프리니 1
game2.iso    프리니 2
```

백그라운드 자동 실행:

```bash
./START_PSP_TOOLKIT_BACKGROUND.sh
```

작업은 터미널을 닫아도 계속되며 상태는 다음으로 확인한다.

```bash
./CHECK_PSP_TOOLKIT_STATUS.sh
```

포그라운드에서 로그를 보려면:

```bash
./RUN_PSP_TOOLKIT.sh
```

원본 ISO는 덮어쓰지 않는다. 추출물, 수정 ISO, CSV/JSON/HTML 보고서는 `workspace/` 아래에 별도로 생성한다.

## 저용량 모드

기본 실행은 ISO 전체를 두 개 동시에 풀지 않는다. 호환성 판정에 필요한 다음 파일만 **한 게임씩 순서대로** 추출한다.

```text
PARAM.SFO
BOOT.BIN 또는 EBOOT.BIN
SYSTEM.DAT
SCRIPT.DAT
```

각 게임 분석이 끝나면 임시 추출본을 자동 삭제하고 JSON/CSV/HTML 보고서만 남긴다. 실행 전에는 다음 재생성 가능 자료만 정리한다.

```text
workspace/strings
workspace/translations/recovered
대용량 이전 PPSSPP 로그
중복 catalog.jsonl/translation_template.json
Python 캐시
```

`game.iso`, `game2.iso`, 번역 마스터, 한글 배정표, V4/V5 빌드 산출물은 보호한다.

정리 미리보기:

```bash
python3 psp_toolkit.py cleanup
```

실제 정리:

```bash
python3 psp_toolkit.py cleanup --apply
```

## 자동 처리 내용

1. Python, 7z, Galmuri14, PPSSPP, 남은 디스크 공간 점검
2. 재생성 가능한 대용량 중간 자료 안전 정리
3. 프리니 번역 CSV의 바이트 용량, 미등록 글자, 제어 토큰, 일본어 잔존, 화면 폭 검사
4. 기존 번역 마스터에 포함되지 않은 START 자원 일본어 후보 추출
5. BOOT.BIN/EBOOT.BIN의 메뉴·튜토리얼·HUD 일본어 후보 추출
6. `game.iso`, `game2.iso`의 핵심 파일만 순차 추출 및 PARAM.SFO/구조 분석
7. SYSTEM.DAT → start.lzs → start.dat 및 런타임 폰트 구조 확인
8. 프리니 1/2의 SYSTEM, START, SCRIPT, 폰트 호환 등급 판정
9. 검증된 V4 입력이 있으면 Galmuri14 V5 ISO 생성
10. HTML 대시보드와 검수 CSV 생성

## 프리니 2 판정

- **A**: 프리니 1 프로필 엔진을 거의 그대로 재사용 가능. 번역 데이터와 오프셋은 프리니 2에서 새로 추출한다.
- **B**: 공통 엔진은 재사용 가능하지만 프리니 2 설정/파서 조정이 필요하다.
- **C**: 프리니 2 전용 프로필이 필요하다.

A 등급이어도 프리니 1의 번역 바이트나 고정 오프셋을 프리니 2에 그대로 복사하지 않는다.

## 주요 명령

```bash
python3 psp_toolkit.py doctor
python3 psp_toolkit.py cleanup --apply
python3 psp_toolkit.py analyze game.iso --low-space --cleanup-extracted
python3 psp_toolkit.py strings workspace/iso/PSP_GAME/SYSDIR/BOOT.BIN
python3 psp_toolkit.py prinny-qa
python3 psp_toolkit.py compare game.iso game2.iso
python3 psp_toolkit.py build-v5
python3 psp_toolkit.py all --game1 game.iso --game2 game2.iso
```

## 주요 보고서

```text
workspace/reports/psp_toolkit/index.html
workspace/reports/psp_toolkit/all_report.json
workspace/reports/psp_toolkit/prinny_compatibility.json
workspace/reports/psp_toolkit/pre_run_cleanup.json
workspace/reports/psp_toolkit/game1_executable_strings/strings.csv
workspace/reports/psp_toolkit/game2_executable_strings/strings.csv
workspace/reports/prinny_qa/review_queue.csv
workspace/reports/prinny_qa/uncovered_candidates.csv
workspace/reports/prinny_qa/boot_screenshot_matches.csv
workspace/reports/prinny_qa/screenshot_findings.csv
```

## 현재 프리니 1 QA 결과

- 번역 마스터: 4,110개
- 안전 자동 수정: 2개
  - `돌려드림다.` → `돌려드림.`
  - `본명, 아사기리(朝霧) 아사기.` → `본명, 아사기리 아사기.`
- 자동 수정 후 번역 QA: 오류 0, 경고 0
- 기존 마스터 밖 START 일본어 후보: 80개
- 과거 BOOT 문자열 스캔에서 추출한 일본어 UI 후보: 566개

화면에 남은 일시정지 메뉴, 튜토리얼, 스테이지 결과 등의 일본어는 주로 START 번역 누락만이 아니라 **BOOT.BIN 실행 파일 문자열**에 존재한다. 다음 구현 단계는 BOOT 문자열의 번역·재삽입과 포인터/용량 검증이다.

## V5 빌드 안전 규칙

`build_galmuri14_v5.py`는 다음을 확인한다.

- 검증된 V4 START/SYSTEM/ISO SHA1
- Galmuri14가 실제 선택됐는지
- 폰트 TXP 크기 보존
- START에서 예상한 리소스만 변경됐는지
- start.lzs 왕복 해제
- SYSTEM.DAT 크기와 보호 영역 보존
- ISO 주입 전후 영역 무결성
- 선택적 `7z t` 검사
- 원본보다 짧은 2개 확정 문자열 안전 수정

V4 기준 산출물이 없으면 ISO 빌드를 거짓 성공으로 처리하지 않고 `skipped_missing_inputs`로 보고서에 기록한다.

## 테스트

```bash
pytest -q
python3 -m compileall -q psp_localization profiles core/nsf_string.py psp_toolkit.py build_galmuri14_v5.py
```

현재 자동 테스트는 11개다.

## D: 드라이브 작업 공간 (V3)

기본 실행은 D: 볼륨을 자동 탐지합니다. Linux에서 자동 탐지가 안 되면 다음처럼 마운트 경로를 지정합니다.

```bash
PSP_D_ROOT=/media/$USER/D bash START_PSP_TOOLKIT_BACKGROUND.sh
```

외부 작업 폴더는 `D:/PSP_Localization_Work`에 해당하며, `game2.iso`, 프리니 1/2 임시 추출본, 통합 분석 보고서가 이곳에 저장됩니다. 원본 `game.iso`와 프리니 1의 V4/V5 핵심 파일은 프로젝트 폴더에 유지됩니다.

## 한글패치 프로젝트 필수 정책

이 저장소의 빌드·번역·폰트·배포 작업은
[`docs/PRIMARY_REFERENCE_POLICY.md`](docs/PRIMARY_REFERENCE_POLICY.md)를 우선 적용합니다.
0.5 단위 버전 체크포인트는 `bash RELEASE_CHECKPOINT.sh <버전>`으로 기록합니다.
