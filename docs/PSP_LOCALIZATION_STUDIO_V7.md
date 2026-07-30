# PSP Localization Studio V7

## 현재 실전 대상

1. 프리니 1의 런타임 표시 오류와 BOOT/EBOOT UI 미번역 수정
2. 프리니 2가 프리니 1 공통 엔진으로 한글화 가능한지 A/B/C 판정
3. 프리니 1·2를 첫 프로필로 사용하는 PSP 한글화 종합툴 구축

## 번역 보존

캐릭터 말투, 어미, 감탄사, 반복, 말줄임표는 번역자가 정한 표현을 우선합니다.
자동 수정은 바이트 초과, 미등록 글리프, 종료·포인터·제어코드 오류,
명백한 일본어 잔존과 Expected Write 불일치 등 기계적으로 증명되는 결함에 제한합니다.

## 우선 참고 자료

- https://github.com/mcpads/create-kr-patch-template
- https://font.emulog.app/#fonts
- https://github.com/yazzang-homelab/hancharacter/blob/master/GUIDE.ko.md
- https://github.com/yazzang-homelab/hanpatch
- 사용자 제공 SRWF_F_CUE_BIN_Translation_Editor_v5_2.html은 UI와 작업 흐름 참고용이며 SRW-F 전용 코드는 포함하지 않습니다.

## 호환성 등급

- A: 공통 엔진 재사용, 게임별 번역·주소·Expected Write만 분리
- B: 공통 코어 재사용, 프리니 2 전용 프로필 설정과 일부 파서 추가
- C: 프리니 2 전용 플러그인 구현 필요

A 또는 B라도 프리니 1 번역문과 고정 오프셋을 프리니 2에 직접 복사하지 않습니다.
