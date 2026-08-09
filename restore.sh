#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════════
#  MEDIA Campus — полное восстановление инфраструктуры
#  Запускать на CentOS сервере (10.10.4.120) от имени kamran
#
#  Использование:
#    bash restore.sh              # полное восстановление
#    bash restore.sh --secrets    # только скачать секреты
#    bash restore.sh --up         # только поднять контейнеры
#    bash restore.sh --data       # только восстановить данные из бэкапа
# ═══════════════════════════════════════════════════════════════
set -euo pipefail

REPO_DIR="$HOME/projects/campus-infra"
HELPDESK_OPS_DIR="$HOME/projects/helpdesk-ops"
SECRETS_DIR="$HOME/projects/campus-secrets"
BACKUP_DIR="$HOME/campus-backups"
SECRETS_REPO="https://github.com/KAbumislimov/campus-secrets.git"
INFRA_REPO="https://github.com/KAbumislimov/campus-infra.git"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*"; exit 1; }

# ─── Параметры ────────────────────────────────────────────────
ONLY_SECRETS=0; ONLY_UP=0; ONLY_DATA=0
for arg in "$@"; do
  case "$arg" in
    --secrets) ONLY_SECRETS=1 ;;
    --up)      ONLY_UP=1 ;;
    --data)    ONLY_DATA=1 ;;
  esac
done

# ─── Шаг 1: Код ───────────────────────────────────────────────
if [[ $ONLY_UP -eq 0 && $ONLY_DATA -eq 0 ]]; then
  if [[ ! -d "$REPO_DIR/.git" ]]; then
    log "Клонирую campus-infra..."
    mkdir -p "$(dirname "$REPO_DIR")"
    git clone "$INFRA_REPO" "$REPO_DIR"
  else
    log "campus-infra уже есть — обновляю..."
    git -C "$REPO_DIR" pull --ff-only
  fi
fi

# ─── Шаг 2: Секреты ───────────────────────────────────────────
if [[ $ONLY_UP -eq 0 && $ONLY_DATA -eq 0 ]] || [[ $ONLY_SECRETS -eq 1 ]]; then
  if [[ ! -d "$SECRETS_DIR/.git" ]]; then
    echo ""
    warn "Нужен GitHub токен для campus-secrets (приватный репо)"
    warn "Токен хранится у Камрана или в записях"
    read -rp "GitHub Token (ghp_...): " GH_TOKEN
    git clone "https://${GH_TOKEN}@github.com/KAbumislimov/campus-secrets.git" "$SECRETS_DIR"
  else
    log "campus-secrets уже есть — обновляю..."
    git -C "$SECRETS_DIR" pull --ff-only 2>/dev/null || warn "Не удалось обновить campus-secrets"
  fi

  log "Копирую .env..."
  cp "$SECRETS_DIR/.env" "$REPO_DIR/.env"
  log ".env установлен"

  if [[ -f "$SECRETS_DIR/server/helpdesk-ops.env" && -d "$HELPDESK_OPS_DIR" ]]; then
    cp "$SECRETS_DIR/server/helpdesk-ops.env" "$HELPDESK_OPS_DIR/.env"
    log "helpdesk-ops/.env установлен"
  fi
fi

[[ $ONLY_SECRETS -eq 1 ]] && { log "Секреты готовы."; exit 0; }

# ─── Шаг 2.5: Личные утилиты (campus-mon, gitkamran) ───────────
if [[ -d "$REPO_DIR/personal-bin" ]]; then
  mkdir -p "$HOME/.local/bin"
  cp "$REPO_DIR"/personal-bin/* "$HOME/.local/bin/"
  chmod +x "$HOME"/.local/bin/campus-mon "$HOME"/.local/bin/gitkamran 2>/dev/null || true
  log "Личные утилиты (campus-mon, gitkamran) установлены в ~/.local/bin"
fi

# ─── Шаг 3: Данные из бэкапа ──────────────────────────────────
if [[ $ONLY_DATA -eq 1 ]] || [[ $ONLY_UP -eq 0 ]]; then
  mkdir -p "$REPO_DIR/data/webui" "$REPO_DIR/data/helpdesk/uploads"

  # Ищем последний бэкап webui.db
  LATEST_WEBUI=$(find "$BACKUP_DIR" -name "webui.db" 2>/dev/null | sort | tail -1)
  if [[ -n "$LATEST_WEBUI" ]]; then
    log "Восстанавливаю webui.db из бэкапа: $LATEST_WEBUI"
    cp "$LATEST_WEBUI" "$REPO_DIR/data/webui/webui.db"
  elif [[ -f "$REPO_DIR/data/webui/webui.db" ]]; then
    log "webui.db уже есть (не перезаписываю)"
  else
    warn "Бэкап webui.db не найден — будет создан новый (пустой)"
  fi

  # Ищем последний бэкап helpdesk.db
  LATEST_HELPDESK=$(find "$BACKUP_DIR" -name "helpdesk.db" 2>/dev/null | sort | tail -1)
  if [[ -n "$LATEST_HELPDESK" ]]; then
    log "Восстанавливаю helpdesk.db из бэкапа: $LATEST_HELPDESK"
    cp "$LATEST_HELPDESK" "$REPO_DIR/data/helpdesk/helpdesk.db"
  fi

  # helpdesk-ops (порт 8094) — своя БД и вложения
  if [[ -d "$HELPDESK_OPS_DIR" ]]; then
    mkdir -p "$HELPDESK_OPS_DIR/data"
    LATEST_HOPS_DB=$(find "$BACKUP_DIR" -name "helpdesk_ops.db" 2>/dev/null | sort | tail -1)
    if [[ -n "$LATEST_HOPS_DB" ]]; then
      log "Восстанавливаю helpdesk_ops.db из бэкапа: $LATEST_HOPS_DB"
      cp "$LATEST_HOPS_DB" "$HELPDESK_OPS_DIR/data/helpdesk_ops.db"
    elif [[ -f "$HELPDESK_OPS_DIR/data/helpdesk_ops.db" ]]; then
      log "helpdesk_ops.db уже есть (не перезаписываю)"
    else
      warn "Бэкап helpdesk_ops.db не найден — будет создан новый (пустой)"
    fi
    LATEST_HOPS_UP=$(find "$BACKUP_DIR" -name "helpdesk_ops_uploads.tar.gz" 2>/dev/null | sort | tail -1)
    if [[ -n "$LATEST_HOPS_UP" ]]; then
      log "Восстанавливаю вложения helpdesk-ops: $LATEST_HOPS_UP"
      tar xzf "$LATEST_HOPS_UP" -C "$HELPDESK_OPS_DIR/data/"
    fi
  fi
fi

[[ $ONLY_DATA -eq 1 ]] && { log "Данные восстановлены."; exit 0; }

# ─── Шаг 4: Firewall ──────────────────────────────────────────
if command -v firewall-cmd &>/dev/null; then
  log "Открываю порты..."
  for port in 8090 8091 3000 3100 19912; do
    sudo firewall-cmd --permanent --add-port=${port}/tcp --quiet 2>/dev/null || true
  done
  sudo firewall-cmd --reload --quiet 2>/dev/null || true
fi

# ─── Шаг 5: Docker Compose ────────────────────────────────────
cd "$REPO_DIR"
log "Поднимаю контейнеры campus-infra..."
docker compose \
  --profile webui \
  --profile logs \
  --profile bot \
  --profile cockpit \
  --profile helpdesk \
  up -d --build

if [[ -d "$HELPDESK_OPS_DIR" ]]; then
  log "Поднимаю helpdesk-ops (порт 8094)..."
  ( cd "$HELPDESK_OPS_DIR" && docker compose up -d --build )
fi

# ─── Шаг 6: Проверка ──────────────────────────────────────────
echo ""
log "═══ Статус контейнеров ═══"
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" | grep -v "^NAMES" | sort

echo ""
log "═══ Готово! ═══"
echo -e "  Web UI:       ${GREEN}http://10.10.4.120:8090${NC}"
echo -e "  HelpDesk (старый прототип): ${GREEN}http://10.10.4.120:8091${NC}"
echo -e "  Helpdesk Ops: ${GREEN}https://10.10.4.120:8094${NC}"
echo -e "  Grafana:      ${GREEN}http://10.10.4.120:3000${NC}"
echo -e "  Cockpit:      ${GREEN}http://10.10.4.120:1991${NC}"
echo ""
warn "Если что-то не стартовало: docker logs <имя_контейнера> --tail 50"
