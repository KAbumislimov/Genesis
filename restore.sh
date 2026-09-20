#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════════════════════
#  MEDIA Campus — ВОССТАНОВЛЕНИЕ ВСЕЙ СИСТЕМЫ ИЗ GITHUB (версия 2)
#
#  Одна команда на новой/пустой машине (CentOS 9 / Ubuntu, обычный пользователь с sudo):
#
#     export GH_TOKEN=ghp_xxxxxxxx          # токен GitHub с доступом к campus-infra и campus-secrets
#     git clone --depth 1 https://${GH_TOKEN}@github.com/KAbumislimov/campus-infra.git /tmp/ci \
#       && bash /tmp/ci/projects/campus-infra/restore.sh
#
#  Если репозиторий уже на машине:   bash ~/projects/campus-infra/restore.sh
#
#  Что делает: ставит Docker/Git/cron → синхронизирует репозиторий в ~ → берёт секреты из campus-secrets →
#  возвращает БД (пользователи, РОЛИ И ПРАВА, настройки, машины) и Helpdesk Ops из зашифрованных снимков в GitHub →
#  ставит crontab и systemd-службы (Telegram-бот и др.) → открывает порты → поднимает все контейнеры →
#  (по желанию) переустанавливает кампусные клиенты → проверяет, что панель отвечает.
#
#  Опции:
#     --verify      ничего не меняет: проверяет, что ВСЁ необходимое для восстановления есть и читается
#     --state-only  только данные (БД, права, настройки) из снимков, без контейнеров/cron/служб
#     --no-clients  не трогать кампусные машины (client1, client2…)
#     --force-data  заменить существующие БД снимками из GitHub (старые сохраняются рядом)
#     --yes         не задавать вопросов
#  Подробно: RESTORE.md и docs/BACKUP-AND-RESTORE.md
# ═══════════════════════════════════════════════════════════════════════════════
set -uo pipefail

VERIFY=0; STATE_ONLY=0; NO_CLIENTS=0; FORCE_DATA=0; YES=0
for a in "$@"; do case "$a" in
  --verify) VERIFY=1;; --state-only) STATE_ONLY=1;; --no-clients) NO_CLIENTS=1;; --force-data) FORCE_DATA=1;; --yes) YES=1;;
  -h|--help) sed -n 2,28p "$0"; exit 0;; esac; done

INFRA_REPO="KAbumislimov/campus-infra"; SECRETS_REPO="KAbumislimov/campus-secrets"
PROJECTS="$HOME/projects"; INFRA="$PROJECTS/campus-infra"; SECRETS="$PROJECTS/campus-secrets"; HOPS="$PROJECTS/helpdesk-ops"
GH_TOKEN="${GH_TOKEN:-}"
PROBLEMS=0; WARNINGS=0
G='\033[0;32m'; Y='\033[1;33m'; R='\033[0;31m'; B='\033[1m'; N='\033[0m'
ok()   { echo -e "${G}  ✓${N} $*"; }
warn() { echo -e "${Y}  ⚠${N} $*"; WARNINGS=$((WARNINGS+1)); }
bad()  { echo -e "${R}  ✗${N} $*"; PROBLEMS=$((PROBLEMS+1)); }
step() { echo -e "\n${B}━━ $* ━━${N}"; }
do_it() { if [[ $VERIFY -eq 1 ]]; then echo "    (проверка) пропущено: $*"; else "$@"; fi; }
ask()  { [[ $YES -eq 1 || $VERIFY -eq 1 ]] && return 0; read -rp "$1 [y/N] " ans; [[ "$ans" =~ ^[YyДд] ]]; }

echo -e "${B}MEDIA Campus — восстановление из GitHub $([[ $VERIFY -eq 1 ]] && echo '(ПРОВЕРКА, без изменений)')${N}  $(date '+%Y-%m-%d %H:%M')"

# ── 0. Программы ───────────────────────────────────────────────────────────────
step "0. Необходимые программы"
pm=""; command -v dnf >/dev/null && pm="dnf"; [[ -z "$pm" ]] && command -v apt-get >/dev/null && pm="apt"
need=()
for c in git openssl python3 curl crontab; do command -v "$c" >/dev/null || need+=("$c"); done
if [[ ${#need[@]} -gt 0 ]]; then
  warn "не хватает: ${need[*]}"
  if [[ $VERIFY -eq 0 ]]; then
    case "$pm" in
      dnf) sudo dnf -y install git openssl python3 curl cronie chrony && sudo systemctl enable --now crond chronyd ;;
      apt) sudo apt-get update -qq && sudo apt-get -y install git openssl python3 curl cron chrony && sudo systemctl enable --now cron chrony ;;
      *) bad "неизвестный менеджер пакетов — поставьте вручную: ${need[*]}" ;;
    esac
  fi
else ok "git, openssl, python3, curl, crontab есть"; fi
if ! command -v docker >/dev/null; then
  warn "Docker не установлен"
  if [[ $VERIFY -eq 0 ]]; then curl -fsSL https://get.docker.com | sudo sh && sudo systemctl enable --now docker && sudo usermod -aG docker "$USER"; fi
else ok "Docker: $(docker --version 2>/dev/null | cut -d, -f1)"; fi
DOCKER="docker"; docker ps >/dev/null 2>&1 || DOCKER="sudo docker"
$DOCKER compose version >/dev/null 2>&1 && ok "docker compose есть" || warn "плагин docker compose не найден"

# ── 1. Репозиторий ─────────────────────────────────────────────────────────────
step "1. Код и конфигурация из GitHub"
REMOTE="https://github.com/${INFRA_REPO}.git"
[[ -n "$GH_TOKEN" ]] && AUTH_REMOTE="https://${GH_TOKEN}@github.com/${INFRA_REPO}.git" || AUTH_REMOTE="$REMOTE"
[[ -n "${CAMPUS_REPO_URL:-}" ]] && AUTH_REMOTE="$CAMPUS_REPO_URL"      # для зеркал и тестов (например git@github.com:…)
mkdir -p "$HOME/log"
if [[ -f "$INFRA/webui/app.py" && -d "$HOME/.git" ]]; then
  ok "репозиторий уже на месте ($HOME)"
  if [[ $VERIFY -eq 1 ]]; then
    git -C "$HOME" ls-remote --exit-code origin main >/dev/null 2>&1 && ok "GitHub доступен, ветка main найдена" || warn "GitHub недоступен с этой машины (проверьте SSH-ключ/токен)"
  else git -C "$HOME" pull --ff-only origin main >/dev/null 2>&1 && ok "обновлено до последнего коммита" || warn "pull не выполнен (локальные правки?) — продолжаю с тем, что есть"; fi
else
  if [[ $VERIFY -eq 1 ]]; then bad "репозитория нет на этой машине (в режиме проверки не клонирую)"
  else
    echo "  Загружаю репозиторий в $HOME (частичный клон: только campus-infra, helpdesk-ops, ops-journal ≈ 100 МБ)…"
    ( cd "$HOME" && { [[ -d .git ]] || git init -q -b main; } && { git remote add origin "$AUTH_REMOTE" 2>/dev/null || git remote set-url origin "$AUTH_REMOTE"; } \
      && if [[ "${FULL_CHECKOUT:-0}" == "1" ]]; then git fetch --depth 1 origin main; \
         else git fetch --depth 1 --filter=blob:none origin main && git sparse-checkout init --cone && git sparse-checkout set projects/campus-infra projects/helpdesk-ops projects/ops-journal; fi \
      && git checkout -f -B main FETCH_HEAD ) >"$HOME/log/restore-git.log" 2>&1 \
      && ok "репозиторий получен" || { bad "не удалось получить репозиторий (нужен GH_TOKEN или SSH-ключ GitHub) — см. ~/log/restore-git.log"; exit 1; }
    # дальше работаем по SSH, если ключ есть, иначе оставляем HTTPS
    if ssh -o BatchMode=yes -o ConnectTimeout=5 git@github.com true 2>&1 | grep -qi "successfully authenticated"; then
      git -C "$HOME" remote set-url origin "git@github.com:${INFRA_REPO}.git"; ok "remote переключён на SSH"
    else warn "SSH-ключа GitHub нет: автосинхронизация будет пушить по HTTPS. Добавьте ключ:  ssh-keygen -t ed25519  →  GitHub → Settings → SSH keys, затем: git -C ~ remote set-url origin git@github.com:${INFRA_REPO}.git"; fi
  fi
fi
[[ -f "$INFRA/webui/app.py" ]] && ok "код веб-панели на месте" || bad "нет $INFRA/webui/app.py"
mkdir -p "$HOME/log" "$HOME/campus-backups"

# ── 2. Секреты ─────────────────────────────────────────────────────────────────
step "2. Секреты (campus-secrets: .env, токены ботов, SSH-ключ campus_bot)"
if [[ -f "$INFRA/.env" ]]; then ok ".env уже есть"
elif [[ $VERIFY -eq 1 ]]; then
  if [[ -n "$GH_TOKEN" ]] && git ls-remote "https://${GH_TOKEN}@github.com/${SECRETS_REPO}.git" HEAD >/dev/null 2>&1; then ok "campus-secrets доступен по токену"; else warn ".env нет и campus-secrets не проверить (задайте GH_TOKEN)"; fi
else
  GH_TOKEN="$GH_TOKEN" bash "$INFRA/bootstrap.sh" secrets || true
  [[ -f "$INFRA/.env" ]] && ok ".env установлен" || bad ".env не получен — без секретов система не запустится (проверьте GH_TOKEN)"
fi
if [[ -f "$INFRA/.env" ]]; then
  grep -q '^BACKUP_VAULT_PASS=.\+' "$INFRA/.env" && ok "ключ расшифровки снимков (BACKUP_VAULT_PASS) есть" || bad "в .env нет BACKUP_VAULT_PASS — зашифрованные снимки БД не открыть"
  if [[ -f "$SECRETS/server/helpdesk-ops.env" && -d "$HOPS" && $VERIFY -eq 0 ]]; then cp -n "$SECRETS/server/helpdesk-ops.env" "$HOPS/.env" 2>/dev/null && ok "helpdesk-ops/.env"; fi
fi

# ── 3. Данные из GitHub-снимков ────────────────────────────────────────────────
step "3. Данные: пользователи, роли и права, настройки, машины, Helpdesk Ops"
if [[ -d "$INFRA/state" ]]; then
  if [[ $VERIFY -eq 1 ]]; then python3 "$INFRA/scripts/import_state.py" verify && ok "снимки расшифровываются и целы" || bad "проверка снимков не пройдена"
  else
    F=""; [[ $FORCE_DATA -eq 1 ]] && F="--force"
    python3 "$INFRA/scripts/import_state.py" restore $F || warn "часть данных не восстановлена из снимка (см. выше)"
  fi
else warn "в репозитории нет state/ (снимки ещё не создавались)"; fi
if [[ ! -s "$INFRA/data/webui/webui.db" && $VERIFY -eq 0 ]]; then
  LATEST=$(find "$HOME/campus-backups" -name webui.db 2>/dev/null | sort | tail -1)
  if [[ -n "$LATEST" ]]; then mkdir -p "$INFRA/data/webui" && cp "$LATEST" "$INFRA/data/webui/webui.db" && ok "БД из локального бэкапа: $LATEST"; fi
fi
[[ -s "$INFRA/data/webui/webui.db" ]] && HAVE_DB=1 || HAVE_DB=0
[[ $STATE_ONLY -eq 1 ]] && { echo; ok "Готово (--state-only)."; exit 0; }

# ── 4. Службы и cron ───────────────────────────────────────────────────────────
step "4. Telegram-бот, systemd-службы, crontab"
if [[ -d "$INFRA/state/systemd" && -f "$INFRA/state/systemd/ENABLED.txt" ]]; then
  ok "unit-файлов в снимке: $(ls "$INFRA"/state/systemd/*.service 2>/dev/null | wc -l); включённые: $(tr '\n' ' ' < "$INFRA/state/systemd/ENABLED.txt")"
  if [[ $VERIFY -eq 0 ]]; then
    sudo mkdir -p /opt/tg-campus-bot
    [[ -f "$INFRA/bots/client1/bot_client1.py" ]] && sudo cp "$INFRA/bots/client1/bot_client1.py" /opt/tg-campus-bot/
    [[ -f "$SECRETS/server/client1.config.env" ]] && sudo cp "$SECRETS/server/client1.config.env" /opt/tg-campus-bot/client1.env
    for u in "$INFRA"/state/systemd/*.service; do sudo cp "$u" /etc/systemd/system/; done
    sudo systemctl daemon-reload
    while read -r unit; do [[ -n "$unit" ]] && sudo systemctl enable --now "$unit" >/dev/null 2>&1 && ok "служба $unit включена" || warn "служба $unit не запустилась"; done < "$INFRA/state/systemd/ENABLED.txt"
  fi
else warn "нет снимка systemd-служб (state/systemd)"; fi
if [[ -f "$INFRA/state/crontab.txt" ]]; then
  ok "crontab в снимке: $(grep -vc '^#\|^$' "$INFRA/state/crontab.txt") задач (бэкап в GitHub, синхронизация времени, дайджест, Zəfər…)"
  if [[ $VERIFY -eq 0 ]]; then
    crontab -l > "$HOME/crontab.before_restore" 2>/dev/null || true
    crontab "$INFRA/state/crontab.txt" && ok "crontab установлен (прежний — в ~/crontab.before_restore)"
  fi
else warn "нет state/crontab.txt"; fi
[[ -f "$INFRA/state/etc/chrony.conf" && $VERIFY -eq 0 ]] && sudo cp "$INFRA/state/etc/chrony.conf" /etc/chrony.conf && sudo systemctl restart chronyd 2>/dev/null && ok "NTP-конфиг (chrony) восстановлен"
# постоянный автосинхронизатор с GitHub (запускается cron'ом @reboot, но стартуем сразу)
[[ $VERIFY -eq 0 ]] && nohup bash "$INFRA/scripts/github-live-sync-watchdog.sh" >>"$HOME/log/github-live-sync-watchdog.log" 2>&1 &

# ── 5. Порты ───────────────────────────────────────────────────────────────────
step "5. Firewall"
if command -v firewall-cmd >/dev/null; then
  if [[ $VERIFY -eq 0 ]]; then for p in 8090 8091 8094 3000 3100 9090 9091 19912 1991; do sudo firewall-cmd --permanent --add-port=${p}/tcp >/dev/null 2>&1; done; sudo firewall-cmd --permanent --add-service=ntp >/dev/null 2>&1; sudo firewall-cmd --reload >/dev/null 2>&1 && ok "порты открыты"; else ok "firewalld есть"; fi
else ok "firewalld нет — порты не трогаю"; fi

# ── 6. Контейнеры ──────────────────────────────────────────────────────────────
step "6. Docker-контейнеры (веб-панель, мониторинг, бот, Helpdesk Ops)"
if [[ $VERIFY -eq 1 ]]; then
  ( cd "$INFRA" && $DOCKER compose --profile webui --profile logs --profile bot --profile cockpit --profile helpdesk config -q ) 2>/dev/null && ok "docker-compose.yaml корректен" || bad "docker-compose.yaml не разбирается (нет .env?)"
else
  ( cd "$INFRA" && $DOCKER compose --profile webui --profile logs --profile bot --profile cockpit --profile helpdesk up -d --build ) && ok "контейнеры campus-infra подняты" || bad "docker compose завершился с ошибкой"
  [[ -d "$HOPS" ]] && ( cd "$HOPS" && $DOCKER compose up -d --build ) && ok "Helpdesk Ops поднят"
fi

# ── 7. Запасной путь для прав: JSON, если снимка БД не было ────────────────────
if [[ $VERIFY -eq 0 && ${HAVE_DB:-0} -eq 0 ]]; then
  step "7. БД из снимка не восстановлена — применяю права, настройки и машины из JSON"
  sleep 12
  $DOCKER cp "$INFRA/scripts/import_state.py" campus-webui:/tmp/import_state.py 2>/dev/null && $DOCKER cp "$INFRA/state" campus-webui:/tmp/state 2>/dev/null \
    && $DOCKER exec campus-webui python3 /tmp/import_state.py json --db /data/webui.db --state /tmp/state && $DOCKER restart campus-webui >/dev/null \
    && ok "права, настройки и машины применены из JSON (пользователей создайте заново)" || warn "JSON-импорт не выполнен"
fi

# ── 8. Кампусные клиенты ───────────────────────────────────────────────────────
if [[ $NO_CLIENTS -eq 0 && $VERIFY -eq 0 ]]; then
  step "8. Кампусные клиенты (client1, client2)"
  if ask "Переустановить плеер/боты на client1 и client2 по SSH?"; then GH_TOKEN="$GH_TOKEN" bash "$INFRA/bootstrap.sh" clients || warn "часть клиентов недоступна — см. docs/DISASTER-RECOVERY.md, машины по одной: machines/<кампус>/install.sh"; fi
fi

# ── 9. Проверка ────────────────────────────────────────────────────────────────
step "9. Итоговая проверка"
if [[ $VERIFY -eq 0 ]]; then
  for i in $(seq 1 30); do curl -sk -o /dev/null -w '%{http_code}' https://localhost:8090/login 2>/dev/null | grep -q 200 && break; sleep 2; done
  code=$(curl -sk -o /dev/null -w '%{http_code}' https://localhost:8090/login 2>/dev/null)
  [[ "$code" == "200" ]] && ok "веб-панель отвечает: https://$(hostname -I 2>/dev/null | awk '{print $1}'):8090" || bad "веб-панель не отвечает (docker logs campus-webui --tail 50)"
  $DOCKER ps --format 'table {{.Names}}\t{{.Status}}' | sed 's/^/    /'
fi
echo
if [[ $PROBLEMS -eq 0 ]]; then echo -e "${G}${B}ГОТОВО${N}${G}: критичных проблем нет (предупреждений: $WARNINGS).${N}"; else echo -e "${R}${B}ЕСТЬ ПРОБЛЕМЫ: $PROBLEMS${N} (предупреждений: $WARNINGS) — см. отметки ✗ выше."; fi
cat <<'MANUAL'

Что НЕ хранится в GitHub и восстанавливается отдельно (см. docs/BACKUP-AND-RESTORE.md):
  • «Kamran Music» (~33 ГБ) — НИГДЕ не бэкапится: вернуть можно только со старого диска / отдельной копии
  • мастер-копия Media (~800 МБ) — бэкап еженедельно на Proxmox (см. README.md в корне репозитория, шаг 6):
        bash ~/projects/campus-infra/scripts/restore-music.sh client1
  • на новой сетевой карте изменится MAC (Wake-on-LAN): обновить CLIENT1_MAC в .env
  • настройки Samba на кампусах (если использовались) — вручную по образцу
MANUAL
exit $PROBLEMS
