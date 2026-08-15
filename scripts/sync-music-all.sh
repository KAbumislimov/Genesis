#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
#  SYNC MUSIC ALL — обновляет музыку/звонки (Media) сразу на всех
#  кампусах одной командой, вместо ручного restore-music.sh по одному.
#
#  Каждый кампус получает свою ЛОКАЛЬНУЮ копию (не сетевая шара/стрим) —
#  так плеер продолжает играть по расписанию, даже если в момент звонка
#  пропадёт сеть или ляжет центральный сервер. Это та же логика, что и
#  в scripts/restore-music.sh — тут просто прогон по всем кампусам сразу.
#
#  Запуск (с центрального сервера):
#      bash scripts/sync-music-all.sh
#
#  Список кампусов берётся из machines/*/ (кроме machines/server —
#  это не кампус-клиент). Один недоступный кампус не останавливает
#  остальные — в конце сводка, кто прошёл, кто нет.
# ═══════════════════════════════════════════════════════════════════════
set -uo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"

CAMPUSES=()
for d in "$REPO"/machines/*/; do
    c="$(basename "$d")"
    [[ "$c" == "server" ]] && continue
    CAMPUSES+=("$c")
done

if [[ ${#CAMPUSES[@]} -eq 0 ]]; then
    echo "Кампусов в machines/ не найдено." >&2
    exit 1
fi

echo "Кампусы: ${CAMPUSES[*]}"
echo ""

OK_LIST=()
FAIL_LIST=()

for campus in "${CAMPUSES[@]}"; do
    echo "══════════════ $campus ══════════════"
    if bash "$REPO/scripts/restore-music.sh" "$campus"; then
        OK_LIST+=("$campus")
    else
        FAIL_LIST+=("$campus")
    fi
    echo ""
done

echo "╔══════════════════════════════════════════╗"
echo "║   ИТОГ РАССЫЛКИ МУЗЫКИ                    ║"
echo "╚══════════════════════════════════════════╝"
echo "  ✅ Обновлено: ${OK_LIST[*]:-—}"
if [[ ${#FAIL_LIST[@]} -gt 0 ]]; then
    echo "  ❌ Не удалось: ${FAIL_LIST[*]}"
    exit 1
fi
