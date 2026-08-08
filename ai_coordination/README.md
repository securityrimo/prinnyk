# Prinny Multi-AI Team

Codex가 유일한 작성자입니다. Claude와 Gemini는 사용자가 다시 활성화할 때까지
검토 흐름에서 제외하며, 그동안 봉인 manifest와 빌더의 이중 검증을 사용합니다.

## 설치 확인

```bash
cd "$HOME/PrinnyReverseToolkit"
./CHECK_PRINNY_AI_TEAM.sh
```

## 현재 Prinny 1 작업 실행

```bash
cd "$HOME/PrinnyReverseToolkit"
./RUN_PRINNY_AI_TEAM.sh \
  p1 \
  ai_coordination/tasks/PRINNY1_CURRENT.md
```

## 주요 체크포인트를 포함한 실행

활성 검토자의 BLOCKER가 없고 테스트가 통과한 경우에만
커밋·push합니다.

```bash
./RUN_PRINNY_AI_TEAM.sh \
  p1 \
  ai_coordination/tasks/PRINNY1_CURRENT.md \
  --checkpoint v8.0
```

## 레인 정책

- p1: Codex 코드 작성 허용
- p2: 읽기 전용 분석
- studio: 읽기 전용 분석

## 실행 기록

`ai_coordination/runs/<시각>_<레인>/` 아래에 모든 프롬프트, 결과,
검토, Git diff, 최종 판정을 저장합니다.

## 주의

- 활성 외부 검토자의 인증이 실패하면 오케스트레이터가 즉시 중단합니다.
- ISO는 자동 생성하지 않습니다.
- `--checkpoint`가 없으면 GitHub push를 하지 않습니다.
- x.0 또는 x.5 체크포인트는 동일한 태그도 생성합니다.
