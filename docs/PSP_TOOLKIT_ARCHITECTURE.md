# PSP 통합 한글패치 툴 구조

```text
psp_toolkit.py
├─ psp_localization/
│  ├─ iso.py          전체/저용량 선택 추출, 분석, 추출본 정리
│  ├─ maintenance.py  허용 목록 기반 안전 공간 정리
│  ├─ sfo.py          PARAM.SFO 파서
│  ├─ compare.py      게임 이미지 구조 비교
│  ├─ string_scan.py  범용 Shift-JIS 후보 스캔
│  ├─ reporting.py    독립 실행 HTML 보고서
│  └─ util.py         해시와 원자적 파일 저장
└─ profiles/
   └─ prinny/
      ├─ probe.py          SYSTEM/START/SCRIPT/폰트 구조 분석
      ├─ executable_qa.py  BOOT/EBOOT UI 문자열 후보 추출
      └─ qa.py             번역·글리프·폭·미포함 문자열 검사
```

## 설계 원칙

- PSP 공통 기능과 게임별 포맷을 분리한다.
- 원본 이미지를 절대 덮어쓰지 않는다.
- 포인터/오프셋은 게임별 프로필 안에서만 사용한다.
- 입력 해시가 달라지면 자동 패치를 중단한다.
- 추출·분석·QA는 다시 실행해도 같은 결과를 내도록 한다.
- 화면 검수는 사람이 담당하지만 후보 수집과 위치 연결은 자동화한다.
- 저용량 환경에서는 핵심 파일만 순차 추출하고 즉시 정리한다.
- 삭제는 프로젝트 내부의 명시적 허용 목록에만 적용한다.

## 현재 작업 흐름

```text
안전 정리
→ 번역 QA
→ game.iso 핵심 파일 추출/분석/정리
→ game2.iso 핵심 파일 추출/분석/정리
→ 프리니 1/2 호환성 등급
→ V5 입력이 있으면 Galmuri14 빌드
→ HTML/CSV/JSON 보고서
```

## 다음 구현 순서

1. BOOT.BIN 번역 템플릿과 원본 바이트/종료문자/참조 위치 색인
2. 동일 길이 안전 패치와 포인터형 재배치 패치 분리
3. PPSSPP 스크린샷 회귀 테스트 연결
4. 브라우저 기반 통합 편집기
5. 추가 PSP 게임 프로필 SDK
