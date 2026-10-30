#!/bin/bash
# Поддельный GigaCode CLI для тестов. Команду читает из stdin.
# По тексту команды понимает, кто его вызвал:
#   ревьюер («независимый ревьюер»)     → поведение из FAKE_REVIEW (через запятую — по вызовам: changes,approve)
#   доработка («доработай задачу»)      → FAKE_REWORK
#   исследование («/opsx:explore»)      → FAKE_EXPLORE
#   генерация (всё остальное)           → FAKE_MODE
# FAKE_PROMPT_FILE — сохранить команду генерации; FAKE_PROMPT_DIR — сохранять все команды по видам.
if [[ "$*" == *"stream-json"* && "$FAKE_STREAM_WRAPPED" != "1" ]]; then
  exec python3 "$(dirname "$0")/fake_stream_wrapper.py" "$0" "$@"
fi
prompt="$(cat)"
commit() { git add -A && git commit -q -m "$1"; }

kind=generate
case "$prompt" in
  *"доработай задачу"*)    kind=rework ;;   # раньше ревью: в команде доработки тоже упомянут ревьюер
  *"Ты — независимый ревьюер"*) kind=review ;;
  *"/opsx:explore"*|*"FAKE_EXPLORE_PROMPT"*) kind=explore ;;
  *"Это твоя ретроспектива"*) kind=retro ;;
esac
if [ -n "$FAKE_PROMPT_DIR" ]; then
  n=$(ls "$FAKE_PROMPT_DIR" 2>/dev/null | grep -c "^$kind-")
  printf '%s' "$prompt" > "$FAKE_PROMPT_DIR/$kind-$n.txt"
fi
[ "$kind" = generate ] && [ -n "$FAKE_PROMPT_FILE" ] && printf '%s' "$prompt" > "$FAKE_PROMPT_FILE"

# Значение из списка «a,b,c» по номеру вызова (последнее — для всех следующих)
pick() {
  local list="$1" counter="${FAKE_STATE_DIR:-/tmp}/fake-$2-calls" i
  i=$(cat "$counter" 2>/dev/null || echo 0); echo $((i + 1)) > "$counter"
  IFS=',' read -ra items <<< "$list"
  [ "$i" -ge "${#items[@]}" ] && i=$((${#items[@]} - 1))
  echo "${items[$i]}"
}

if [ "$kind" = review ]; then
  case "$(pick "${FAKE_REVIEW:-approve}" review)" in
    approve) printf 'Смотрю код...\nREVIEW_VERDICT: APPROVE\nREVIEW_NOTES_START\nВсё по задаче, тесты есть.\nREVIEW_NOTES_END\n';;
    changes) printf 'REVIEW_VERDICT: REQUEST_CHANGES\nREVIEW_NOTES_START\n- Добавь тест на пустой список\n- Убери отладочный print\nREVIEW_NOTES_END\nLESSONS_START\n- Тесты запускаются командой make test\nLESSONS_END\n';;
    vandal)  echo "x" > reviewer_was_here.py; git add -A; git commit -qm "reviewer"; printf 'REVIEW_VERDICT: APPROVE\n';;
    none)    echo "Не смог разобраться";;
    hang)    sleep 60;;
  esac
  exit 0
fi
if [ "$kind" = rework ]; then
  case "${FAKE_REWORK:-fix}" in
    fix)     echo "def test_empty(): pass" > test_fix.py; commit "fix review"; echo "CODE_GENERATION_SUCCESS";;
    nothing) echo "Ничего не сделал";;
  esac
  exit 0
fi
if [ "$kind" = retro ]; then
  case "${FAKE_RETRO:-ok}" in
    ok)    printf 'вспоминаю...\nRETRO_START\nT-1: люди добавили проверку на null — я её пропустил.\nВывод: проверять пустые значения.\nRETRO_END\nLESSONS_START\n- Всегда проверять входные данные на null\nLESSONS_END\n';;
    empty) ;;
  esac
  exit 0
fi
if [ "$kind" = explore ]; then
  case "${FAKE_EXPLORE:-ok}" in
    ok)        echo "думаю..."; printf 'EXPLORE_START\n## Вопросы\n1. Что делать с **пустым** списком?\n- Затронет `api/{id}`\nEXPLORE_END\nLESSONS_START\n- Сборка: make build\nLESSONS_END\n';;
    nomarkers) echo "Предлагаю разбить задачу на две части и уточнить формат ответа API.";;
    vandal)    echo "x" > explorer_was_here.txt; printf 'EXPLORE_START\nПредложения: всё понятно, можно делать.\nEXPLORE_END\n';;
    empty)     ;;
  esac
  exit 0
fi

case "$FAKE_MODE" in
  marker)          echo "print(1)" > feature.py; commit "agent work"; echo "CODE_GENERATION_SUCCESS";;
  marker_lessons)  echo "print(1)" > feature.py; commit "agent work"; echo "CODE_GENERATION_SUCCESS"
                   printf 'LESSONS_START\n- Тесты: pytest -q tests/\n- Тесты: pytest -q tests/\n* Миграции лежат в db/migrations\nLESSONS_END\n';;
  nomarker_empty)  echo "Готово (наверное)";;
  nomarker_work)   echo "print(2)" > work.py; echo "Готово";;
  nomarker_tmp)    echo "1" > tmp_probe.py; echo "Готово";;
  dirty_mixed)     echo "print(3)" > feature.py; echo "1" > tmp_probe.py; echo "CODE_GENERATION_SUCCESS";;
  commit_mixed)    echo "print(4)" > feature.py; echo "1" > tmp_probe.py; commit "work+tmp"; echo "CODE_GENERATION_SUCCESS";;
  commit_tmp)      echo "1" > tmp_probe.py; commit "tmp only"; echo "CODE_GENERATION_SUCCESS";;
  commit_develop)  git checkout -q develop; echo "print(5)" > feature.py; commit "into develop"; echo "CODE_GENERATION_SUCCESS";;
  fail)            echo "boom" >&2; exit 3;;
  hang)            echo "half" > half.py; commit "half"; sleep 60;;
  tokens_text)     echo "print(6)" > feature.py; commit "w"; echo "CODE_GENERATION_SUCCESS"; echo "Total tokens: 12 345";;
  *)               echo "unknown FAKE_MODE=$FAKE_MODE" >&2; exit 99;;
esac
