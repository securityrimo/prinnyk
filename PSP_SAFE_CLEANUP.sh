#!/usr/bin/env bash
# PSP/Prinny 프로젝트 안전 정리 스크립트
# - 현재 터미널을 종료하지 않습니다.
# - game.iso, game2.iso, 번역 마스터, 폰트 배정표, 빌드 스크립트는 삭제하지 않습니다.
# - 다시 생성 가능한 대용량 중간 산출물만 정리합니다.

PROJECT="$HOME/PrinnyReverseToolkit"
LOG="$HOME/Prinny_safe_cleanup.log"

{
  echo "========================================"
  echo "PSP 프로젝트 안전 정리"
  date
  echo "프로젝트: $PROJECT"
  echo "========================================"

  if [ ! -d "$PROJECT" ]; then
    echo "[오류] 프로젝트 폴더를 찾지 못했습니다: $PROJECT"
    echo "아무 파일도 삭제하지 않았습니다."
    echo "로그: $LOG"
    exit 0
  fi

  echo
  echo "[정리 전 용량]"
  du -sh "$PROJECT" 2>/dev/null || true
  df -h "$HOME" 2>/dev/null | tail -n 1 || true

  safe_remove_dir() {
    target="$1"
    label="$2"
    case "$target" in
      "$PROJECT"/workspace/strings|\
      "$PROJECT"/workspace/translations/recovered|\
      "$PROJECT"/workspace/psp_toolkit/game1|\
      "$PROJECT"/workspace/psp_toolkit/game2)
        if [ -d "$target" ]; then
          echo "[삭제] $label: $target"
          rm -rf -- "$target"
        else
          echo "[건너뜀] 없음: $target"
        fi
        ;;
      *)
        echo "[보호] 허용 목록 외 경로라 삭제하지 않음: $target"
        ;;
    esac
  }

  safe_remove_file() {
    target="$1"
    label="$2"
    case "$target" in
      "$PROJECT"/workspace/translations/catalog/catalog.jsonl|\
      "$PROJECT"/workspace/translations/catalog/translation_template.json|\
      "$PROJECT"/workspace/reports/ppsspp_v4_smoke_console.txt|\
      "$PROJECT"/workspace/reports/ppsspp_v4_smoke.log)
        if [ -f "$target" ]; then
          echo "[삭제] $label: $target"
          rm -f -- "$target"
        else
          echo "[건너뜀] 없음: $target"
        fi
        ;;
      *)
        echo "[보호] 허용 목록 외 파일이라 삭제하지 않음: $target"
        ;;
    esac
  }

  safe_remove_dir "$PROJECT/workspace/strings" "문자열 스캔 중간 결과"
  safe_remove_dir "$PROJECT/workspace/translations/recovered" "번역 복구 중간 결과"

  # 이전 통합 분석에서 생긴 ISO 추출본은 다시 생성 가능
  safe_remove_dir "$PROJECT/workspace/psp_toolkit/game1" "프리니 1 임시 추출본"
  safe_remove_dir "$PROJECT/workspace/psp_toolkit/game2" "프리니 2 임시 추출본"

  safe_remove_file "$PROJECT/workspace/translations/catalog/catalog.jsonl" "중복 카탈로그"
  safe_remove_file "$PROJECT/workspace/translations/catalog/translation_template.json" "재생성 가능한 템플릿"
  safe_remove_file "$PROJECT/workspace/reports/ppsspp_v4_smoke_console.txt" "이전 PPSSPP 콘솔 로그"
  safe_remove_file "$PROJECT/workspace/reports/ppsspp_v4_smoke.log" "이전 PPSSPP 로그"

  echo "[정리] Python 캐시"
  find "$PROJECT" -type d -name '__pycache__' -prune -exec rm -rf -- {} + 2>/dev/null || true
  find "$PROJECT" -type f -name '*.pyc' -delete 2>/dev/null || true

  sync

  echo
  echo "[보호 확인]"
  for f in \
    "$PROJECT/game.iso" \
    "$PROJECT/game2.iso" \
    "$PROJECT/build_galmuri14_v5.py" \
    "$PROJECT/workspace/translations/export/translation_master.csv" \
    "$PROJECT/workspace/font/audited_allocation_977/hangul_allocation.json"
  do
    if [ -e "$f" ]; then
      echo "[유지됨] $f"
    else
      echo "[현재 없음] $f"
    fi
  done

  echo
  echo "[정리 후 용량]"
  du -sh "$PROJECT" 2>/dev/null || true
  df -h "$HOME" 2>/dev/null | tail -n 1 || true
  echo
  echo "완료했습니다. 이 스크립트는 터미널을 종료하지 않습니다."
  echo "로그: $LOG"
} 2>&1 | tee "$LOG"

exit 0
