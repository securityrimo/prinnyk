# Prinny 1 현재 작업

TITLE: V7.14.17 xdelta BOOT 디코더 최소 이식
LANE: p1
CHECKPOINT: no

## 목표

사용자가 작성한 시작·난이도 화면 번역 중 게임 내부 텍스트를 먼저 적용한다.
이미지 한국어화는 후순위로 분리하며 PPSSPP 외부 텍스처 교체는 사용하지 않는다.
V7.14.14를 기준으로 BOOT 번역과 누락 글리프를 봉인·독립 검토한다. 승인된
V7.14.16의 런타임 실패 원인을 xdelta 참고본의 BOOT 실행 코드와 비교해 분리하고,
검증되지 않은 코드는 적용하지 않는다. 테스트 ISO는 사용자의 2026-08-01 자동
승인 지시에 따라 필수 게이트 PASS 뒤 생성하고 구조·런타임 검증까지 계속한다.

## 입력

- /home/hyuk/사진/테스트.png 및 테스트1.png~테스트24.png
- evidence/prinny1_v7_8_screenshots/issue_context_manifest.csv
- workspace/reports/prinny_qa/qa_rows.csv
- workspace/build/prinny1_v7_14_9_prologue_full_punctuation/start.dat
- workspace/font/audited_allocation_977/hangul_allocation.json
- docs/PRINNY1_PRIORITY_RULES_V2.md
- workspace/reports/prinny1_v7_14_11_speaker_ligature_plan/expected_write_confirmed.csv
- workspace/reports/prinny1_v7_14_12_screenshot_alignment_plan/expected_write_confirmed.csv
- workspace/reports/prinny1_v7_14_13_sealed_patch_manifest/sealed_expected_writes.csv
- workspace/reports/prinny1_v7_14_13_sealed_patch_manifest/all_report.json
- workspace/translations/ui_v7_14_15/title_difficulty_translation.csv
- workspace/font/audited_allocation_980/hangul_allocation.json
- workspace/reports/prinny1_v7_14_15_text_patch_manifest/sealed_expected_writes.csv
- workspace/reports/prinny1_v7_14_15_text_patch_review/all_report.json
- /home/hyuk/다운로드/Prinny_ULJS00150_KR_20260729.xdelta
- workspace/reports/prinny1_v7_14_15_xdelta_import_audit/all_report.json
- workspace/reports/prinny1_v7_14_15_xdelta_reference_comparison/all_report.json
- workspace/reports/prinny1_v7_14_15_text_resource_build/all_report.json
- workspace/reports/prinny1_v7_14_15_text_resource_build_review/all_report.json
- workspace/reports/prinny1_v7_14_15_text_test_iso/all_report.json
- workspace/reports/prinny1_v7_14_15_text_test_iso_review/all_report.json
- workspace/reports/prinny1_v7_14_15_runtime_test/all_report.json
- workspace/reports/prinny1_v7_14_16_boot_alias_plan/all_report.json
- workspace/reports/prinny1_v7_14_16_boot_alias_review/all_report.json
- workspace/reports/prinny1_v7_14_16_text_test_iso/all_report.json
- workspace/reports/prinny1_v7_14_16_text_test_iso_review/all_report.json
- workspace/reports/prinny1_v7_14_16_runtime_test/all_report.json
- workspace/reports/prinny1_v7_14_16_xdelta_boot_code_audit/all_report.json
- workspace/reports/prinny1_v7_14_17_boot_decoder_plan/all_report.json
- workspace/reports/prinny1_v7_14_17_boot_decoder_review/all_report.json
- workspace/reports/prinny1_v7_14_17_text_resource_build/all_report.json
- workspace/reports/prinny1_v7_14_17_text_resource_build_review/all_report.json
- workspace/reports/prinny1_v7_14_17_text_test_iso/preflight_report.json
- workspace/translations/pending_user/boot_executable_translation_queue_v7_15_2_user_only.csv
- workspace/reports/prinny1_v7_15_2_boot_translation_shortening/all_report.json
- workspace/reports/prinny1_v7_15_2_boot_translation_shortening_review/all_report.json

## 수행

1. 두 입력 계획과 봉인 CSV의 해시·행 수·합집합을 검증한다.
2. V7.14.9 start.dat에서 68개 before 바이트를 새로 읽어 일치시킨다.
3. 자원 경계, 동일 길이, 종료 바이트, 패딩, 범위 겹침을 검증한다.
4. 선언 변경과 메모리 모의 적용의 실제 변경 범위를 비교한다.
5. 번역 문구 변경 0건과 ISO 변경 0건을 확인한다.
6. Claude와 Gemini는 사용자 지시에 따라 제외한다.
7. V7.14.11 결합 글리프 28개는 제목·난이도 화면 런타임 손상으로 폐기한다.
8. V7.14.14는 V7.14.9 기준에 사진18~24 정렬 수정 40개만 유지해 빌드됐고,
   PPSSPP에서 제목·난이도 화면의 폰트/텍스처 손상 복구를 확인했다.
9. 시작 메뉴 일본어 텍스처와 난이도 BOOT.BIN 일본어 문자열 번역은 다음
   Expected Write 대상으로 분리한다.
10. 사용자 번역 10개 중 BOOT 대상 5개를 사용자 문구 그대로 줄 배치한다.
11. 누락 글리프 `탠`, `닿`, `벤`은 기존 977자를 교체하지 않고 감사된 미사용
    슬롯 3개에 추가한다.
12. 텍스트 manifest는 font.txp 3개와 BOOT.BIN 9개, 총 12개 Expected Write다.
13. 이미지 대상 5개는 내부 이미지 편집·재삽입 단계로 연기하고 외부 텍스처
    교체를 사용하지 않는다.
14. Codex가 봉인 manifest와 빌더의 사전·사후 검사를 별도 경로로 재실행한다.
15. 이 검토 작업 자체에서는 ISO를 생성하거나 수정하지 않는다.
16. 2026-07-29 xdelta는 요구 원본 SHA-256과 보유 game.iso가 불일치하므로 강제
    디코드 결과를 배포 후보로 승격하지 않는다.
17. xdelta 후보의 BOOT·SYSTEM·폰트·텍스트·내부 이미지를 분리 추출하고 현재판과
    자원별로 비교한다. 후보의 F0 40~F5 6E 독립 코드맵은 현재 980자 매핑과 섞지
    않으며, 이미지 자원은 텍스트 완료 뒤로 연기한다.
18. xdelta 후보에 없는 현재판 `PrinnyName.dat` 변경 40건을 보존하고 후보 텍스트
    바이트를 현재판에 직접 적용하지 않는다.
19. 정확한 xdelta 원본 ISO는 추가로 요구하지 않는다. 강제 해제 후보는 참고 전용으로
    유지하고 현재판과 동일 QA 슬롯 4,110개를 교차 비교한다.
20. 비교 결과 4,070개 슬롯은 양쪽 모두 변경됐지만 인코딩 또는 문구가 다르고,
    후보만 변경된 기존 QA 슬롯은 0개다. 따라서 현재 사용자 번역을 우선한다.
21. 후보 BOOT는 난이도 문자열 블록 5개의 위치 확인에만 사용하고, 현재 봉인된
    BOOT 9개와 폰트 3개 Expected Write를 변경하지 않는다.
22. 봉인된 12개 Expected Write만 적용한 BOOT.BIN, START.DAT, START.LZS,
    SYSTEM.DAT 내부 자원을 별도 빌드 디렉터리에 생성한다.
23. 빌더와 분리된 사후 검사에서 기준 ISO를 다시 추출하고 START/BOOT 실제 변경,
    LZS 왕복, SYSTEM.DAT 보호 영역, 출력 해시를 검증한다.
24. 내부 자원 독립 검토 PASS 뒤 사용자 명시 승인을 받아 V7.14.15 텍스트 테스트
    ISO를 별도 경로에 생성한다.
25. 실제 PSP 실행 경로를 위해 봉인 BOOT.BIN을 EBOOT.BIN에 평문 ELF로 미러링하고,
    xdelta 참고본의 동일 방식을 근거로 ISO 디렉터리 길이 필드 8바이트를 갱신한다.
26. 생성 ISO에서 BOOT, EBOOT, SYSTEM, START와 12개 Expected Write를 재추출하고
    허용 ISO 범위 밖 변경 0건을 독립 검증한다.
27. PPSSPP 1.20.4에서 외부 텍스처 교체·덤프를 끄고 V7.14.14, V7.14.15,
    xdelta 참고본의 동일 난이도 화면을 같은 입력으로 비교한다.
28. V7.14.15의 동적 한글은 가로줄·누락 글리프로 깨지므로 배포 후보에서 제외한다.
    V7.14.14 기준과 xdelta F0~F5 참고본은 동일 설정에서 읽을 수 있다.
29. 사용자 번역은 유지하고 xdelta 번역 문구는 가져오지 않는다. 다음 수정은 현재
    980자 글리프에 F0 계열 별칭을 추가해 난이도 UI 전용 인코딩을 분리한다.
30. 난이도 UI 사용 한글 54자에 F0 40~F0 75 별칭을 배정하고 기존 글리프 인덱스를
    font.fnt에서 가리킨다. 기존 분산 SJIS 매핑과 font.txp는 보존한다.
31. F0 별칭 font.fnt 1개와 사용자 문구 BOOT 9개, 총 10개 Expected Write를
    독립 검토한다. xdelta 문구·폰트·텍스트 바이트는 적용하지 않는다.
32. 사용자 승인을 받아 V7.14.16 테스트 ISO를 생성하고, font.txp 3개를 포함한 최종
    13개 Expected Write와 BOOT/EBOOT 미러, ISO 허용 변경 범위를 독립 검토한다.
33. 동일한 PPSSPP 1.20.4·소프트웨어 렌더러·외부 텍스처 비활성 조건에서 난이도
    화면을 재시험한다. F0 별칭 적용 뒤에도 가로줄·누락 글리프가 유지되어 BLOCKER다.
34. xdelta 참고본 BOOT 차이를 실행 `.text`, 기존 0 패딩 주입 코드, 번역·런타임
    데이터로 분리한다. 원본 대비 15,936바이트·717구간이며 직접 적용하지 않는다.
35. 0x613F4와 0x6143C의 JAL이 0xCCE20과 0xCCEA4의 주입 함수를 호출함을 확인한다.
    두 함수의 문자 폭 계산·멀티바이트 복사 역할은 잠정 추론이며 호출 규약과 모든
    의존성을 추가 검증하기 전에는 새 Expected Write를 만들지 않는다.
36. 후보 BOOT의 실행 메커니즘 차이만 명령어 경계로 분리한다. `.text` 변경 12개
    명령어와 0xCCE20~0xCCF74의 두 leaf 함수로 한정하며 후보 번역·폰트·이미지·일반
    데이터는 가져오지 않는다.
37. BOOT 코드 10개 Expected Write의 before/after, RWE LOAD 포함 여부, JAL 대상,
    leaf 반환 2개, 외부 절대 호출 0개, 모든 상대 분기의 함수 영역 내 종결을 독립
    검토한다. 실제 변경은 167바이트다.
38. V7.14.16 내부 자원에 코드 10건만 적용해 V7.14.17 BOOT를 생성한다. start.dat,
    start.lzs, SYSTEM.DAT은 바이트 동일하게 보존하고 사용자 문구 13건과 합친 23건
    manifest를 봉인·독립 검토한다.
39. V7.14.17 ISO 사전 검사를 실행해 기준 ISO, 네 내부 자원, 고정 슬롯 크기,
    SYSTEM 내부 START 왕복과 출력 ISO 부재를 확인한다.
40. 사용자가 V7.14.17 생성과 이후 테스트 ISO 자동 승인을 지시했다. 필수 게이트
    PASS 뒤 V7.14.17 ISO를 생성하고 독립 구조 검증과 PPSSPP 테스트를 계속한다.
41. 사용자가 V7.15.2 BOOT 번역 큐의 슬롯 초과 56건을 번역 규칙에 따라 줄여서
    적용하도록 승인했다. 승인 범위 56건만 최소 축약하고 나머지 486건은 보존한다.
42. 축약 전 사용자 큐를 해시가 포함된 별도 파일로 보존하고, 스프레드시트에서
    변형된 바이너리 증거 열은 봉인된 기준 큐에서 복원한다.
43. 최종 542건의 인코딩·슬롯·플레이스홀더·원문 BOOT 바이트를 독립 검증한다.
    줄바꿈으로 이어지는 0387·0388은 개별 NUL 쓰기를 금지하고 전체 포맷 문자열
    단위 Expected Write 대상으로 분리한다. 이 단계에서는 ISO를 생성하지 않는다.
44. 사용자 지시에 따라 2026-07-29 xdelta를 보유 game.iso에 체크섬 비활성화로
    다시 강제 적용한다. 원본과 기존 강제 해제본은 덮어쓰지 않고 새 경로에 생성해
    해시·ISO 구조·기존 결과 동일성을 검사한 뒤 후보 자원을 다시 추출한다.
45. V7.15.2에서 초과였던 56건은 모두 xdelta 후보 문구를 선택하고, 나머지 문구는
    원문·사용자 번역·후보 번역을 비교해 UI 문맥과 게임 분위기에 맞는 쪽을 선택한다.
46. 후보 BOOT에서 통계 코드북 밖의 35개 코드를 문맥 교차로 복구하고, 최종 542건의
    후보 바이트·원본 바이트·플레이스홀더·일본어 잔존·용량을 독립 검토한다.
47. 최종 선택에 필요한 신규 글리프 8자와 줄바꿈 복합 포맷 4행은 별도 Expected
    Write 계획으로 검증한다. 이 두 조건을 통과하기 전에는 BOOT나 ISO에 쓰지 않는다.
48. 복합 문자열의 옛 내부 오프셋을 그대로 사용해 `플레이 시간`이 `이 시간`으로
    잘린 0390을 전체 xdelta 포맷 문자열 기준으로 교정하고 선택·독립 검토를 갱신한다.
49. 감사 완료 미사용 글리프 슬롯 8개로 988자 코드맵을 만들고, 선택 542행을 538개
    고정 슬롯과 2개 전체 포맷 그룹의 BOOT Expected Write로 봉인한다. START.LZS의
    후단 0 패딩 확장, font.fnt 연결, 비폰트 START 자원 동일성을 독립 검토한다.
50. V7.15.1을 기준으로 BOOT/EBOOT/SYSTEM만 교체한 새 V7.15.3 테스트 ISO를 자동
    승인 범위에서 생성하고 7z, 재추출, 허용 범위 밖 동일성, 542행 재디코딩과 988자
    글리프 연결을 독립 사후 검토한다. PPSSPP는 자동 실행하지 않는다.
51. 사용자 지시에 따라 후속 기준을 강제 해제 xdelta ISO로 변경한다. xdelta에 한국어가
    있는 541건은 사용자 문구와 달라도 바이트 그대로 유지하고, xdelta에 한국어가 없는
    1건만 사용자 번역으로 보충한다.
52. BOOT/EBOOT의 동일한 fallback 슬롯 1개 외에는 xdelta ISO의 어떤 데이터도 바꾸지
    않는다. SYSTEM·ANIME·BG·SCRIPT·STAGE·SOUND 포함 전 범위 동일성을 사전·사후
    독립 경로로 검증한다.
53. V7.15.4 ISO에서 직접 PNG, SYSTEM NISPACK PNG, BG TXP, START TXP, anime 내부
    텍스처를 원본 수정 없이 PNG로 추출한다. 모든 항목에 컨테이너·오브젝트·페이지·
    크기·해시를 기록하고 연락판과 사용자 번역 작업표를 만든다.
54. 추출 PNG 747개, 번역 검토 큐 746개, 연락판 42개의 ID·해시·크기·원본 연결을
    독립 검토한다. 사용자 편집 전 `translated/`는 비워 두고 ISO에는 재삽입하지 않는다.
55. 사용자 승인에 따라 V7.15.4 xdelta 기준 `Demo00.dat` 1,572개 레코드를 화자와
    원본 일본어에 다시 연결한다. 한국어 코드가 있는 1,510개 중 현재 말투가 맞는
    레코드는 유지하고, 행동 주체 또는 캐릭터 어미가 명확히 잘못된 9개만 수정한다.
56. 프리니·프리니 부대 9개와 아사기 2개, 총 11개 고정 슬롯을 Expected Write로
    봉인한다. 10바이트 슬롯의 `돌려드림다.`는 의미·주체를 보존한 `돌려드림.`으로
    축약하고 나머지 문구는 원래 QA 용량 안에 둔다.
57. xdelta 폰트의 통계 확정 735자만 인코딩에 사용하고 11개 슬롯을 재디코드한다.
    START 내부 변경 자원은 `Demo00.dat` 1개, 실제 변경은 117바이트로 제한한다.
58. 254바이트 LZS 창의 최장 일치를 선택하는 결정적 압축 경로로 START.LZS를
    3,576,699바이트에서 3,467,147바이트로 재조립하고 압축 왕복을 독립 검증한다.
59. V7.15.4를 부모로 SYSTEM.DAT만 교체한 V7.15.5 테스트 ISO를 자동 승인 범위에서
    생성한다. SHA-256은 `bf0cd291...3400c`이며 ISO 외부 범위, BOOT/EBOOT,
    비대사 START 자원, 7z 구조와 11개 문구 재디코딩을 독립 사후 검토한다.

## 완료 조건

- 텍스트 Expected Write 12건이 V7.14.14 기준 ISO와 일치함
- 예상 변경이 font.txp와 BOOT.BIN의 선언 범위 안으로 한정됨
- 봉인 manifest와 빌더의 사전·사후 재검증이 모두 통과함
- Codex의 번역 문구 변경과 이미지 적용, ISO 변경이 0건임
- 빌드 가능 또는 차단 사유가 명확히 기록됨
- 외부 xdelta의 요구 원본·결과 해시가 일치하거나 불일치 차단이 기록됨
- 텍스트 내부 자원 4개가 봉인 해시와 일치하고 독립 사후 검토 PASS
- 테스트 ISO 구조 검증 PASS지만 난이도 화면 런타임 BLOCKER로 승격 금지
- V7.14.16 F0 별칭 54자와 Expected Write 10개 독립 검토 PASS
- 승인된 V7.14.16 ISO 구조 검토 PASS 및 런타임 BLOCKER가 각각 봉인됨
- xdelta BOOT 실행 코드·주입 코드·데이터 차이가 분리되고 직접 적용 0건임
- V7.14.17 코드 Expected Write 10건과 내부 자원 결합 23건 독립 검토 PASS
- V7.14.17 ISO preflight PASS
- 테스트 ISO는 사용자 철회 전까지 자동 승인으로 생성·검증
- V7.15.2 사용자 번역 542건 중 승인된 초과 56건만 축약되고 최종 초과가 0건임
- V7.15.2 복합 포맷 문자열 2건이 개별 쓰기에서 제외되고 그룹 재배치 대상으로 기록됨
- V7.15.3 최종 542건 중 540건이 xdelta 문구와 일치하고 기존 초과 56건이 모두 포함됨
- 신규 글리프 8자와 복합 포맷 4행이 8개 폰트·2개 그룹 Expected Write로 검증됨
- V7.15.3 BOOT Expected Write 540개와 실제 변경 14,902바이트가 독립 검토 PASS
- V7.15.3 테스트 ISO `00de856f...b8d7ca`가 구조·재추출·범위 검토 PASS
- V7.15.3 PPSSPP 런타임과 프롤로그 보스 상호작용 회귀 확인은 미완료
- V7.15.4는 xdelta 한국어 541건을 그대로 사용하고 사용자 fallback 1건만 적용함
- V7.15.4 ISO `63c5f213...e2f2b7`의 xdelta 기준 외부 데이터 동일성 검토 PASS
- 강제 해제 xdelta의 공식 선언 해시 불일치 때문에 V7.15.4는 테스트 기준으로 한정됨
- V7.15.4 이미지/UI PNG 747개와 번역 검토 큐 746개 추출·독립 검토 PASS
- 이미지 번역본의 동일 팔레트·캔버스 검증과 ISO 내부 재삽입은 사용자 편집 후 진행
- V7.15.5 대사 레코드 1,572개 감사, 9개 레코드·11개 슬롯 말투 교체 독립 검토 PASS
- V7.15.5 ISO `bf0cd291...3400c`는 SYSTEM.DAT만 변경되고 START 내부 Demo00.dat만
  117바이트 달라졌으며 구조 검토 PASS, 실제 게임 장면 말투 확인은 미완료
