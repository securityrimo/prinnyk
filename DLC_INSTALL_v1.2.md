# DLC v1.2 설치 안내

프리니 2는 `Prinny2_Korean_Final_v1.2_EASY.zip`을 사용하는 방법이 가장
간단합니다. ZIP을 풀고 Windows에서는 `START_PATCH.bat`, Linux에서는
`START_PATCH.sh`를 실행한 뒤 `1. 본편 + DLC 모두 패치`를 선택하십시오.

아래는 개별 DLC 통합팩을 직접 적용할 때의 방법입니다.

각 게임의 통합 DLC ZIP은 xdelta 패치, 안전 적용기, 원본·결과 해시 manifest를 포함합니다.

1. 해당 게임의 DLC 통합 패치 ZIP을 별도 폴더에 풉니다.
2. 프리니 1은 원본 `ULJS00150.zip`, 프리니 2는 다음 중 보유한 원본 하나를 준비합니다.
   - 일본판 DLC `NPJH50211.zip` 또는 압축을 푼 `NPJH50211` 폴더
   - 유럽판 `Prinny 2 - Dawn of Operation Panties Dood (Europe) (DLC).zip`
3. `apply.sh` 또는 `apply.bat`에 원본과 출력 경로를 지정합니다.
4. 출력된 `PSP` 폴더를 메모리스틱 루트에 복사합니다.

```bash
./apply.sh "/path/to/ULJS00150.zip" "/path/to/output"
```

프리니 1 통합팩은 `DL0000`, `DL0001`, `DL0002`와 `PARAM.PBP`를 한 번에
처리합니다. 프리니 2 통합팩은 일본판 `NPJH50211`과 유럽판 `NPEH00101` 구조를
자동 판별합니다. 어느 쪽을 입력해도 `JP00.EDAT`, `RADISH.EDAT`, `TICKET.EDAT`,
일본판용 `PARAM.PBP`를 하나의 `PSP/GAME/NPJH50211/` 폴더에 출력합니다.
유럽판 원본 폴더는 메모리스틱에 따로 설치하지 마십시오.

게임별 적용 구성은 다음과 같습니다.

- 프리니 1: 본편 xdelta 한 개 + DLC 통합팩 한 개
- 프리니 2: 일본판 본편 xdelta 한 개 + 일본판·유럽판 겸용 DLC 통합팩 한 개

필요 도구는 Python 3와 xdelta3입니다. Windows에서는 `xdelta3.exe`를 패치팩을
푼 폴더에 놓아도 됩니다.
