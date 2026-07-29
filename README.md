<div align="center">

<img src="docs/banner.svg" alt="Genesis" width="100%">

# Genesis

🇬🇧 English · 🇷🇺 [Русский](README.ru.md) · 🇦🇿 [Azərbaycan](README.az.md)

**A centralized platform for managing school audio broadcasting, monitoring, and IT infrastructure across multiple campuses.**

![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-web%20UI-000000?logo=flask&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-monitoring-F46800?logo=grafana&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-bots-26A5E4?logo=telegram&logoColor=white)

</div>

One server, several physical sites, a single web panel, Telegram bots, and a voice AI assistant — all built from scratch by one person, growing since 2026.

---

## 📖 Story

It all started with **a single thin client from an unknown manufacturer** — the school just needed the bell to ring on time. Today it has grown into a full infrastructure: a central server, fleet-wide monitoring through Grafana, independent audio control per campus (or all at once), automated backup and recovery, a full-control web panel, and a voice assistant built on Whisper + Claude.

Special thanks to the colleagues who helped along the way with advice and support — **our network admin** (the idea that got the whole thing rolling in the right direction) and **our sysadmin** (showed how to actually navigate all of this). Without you, this would still be one forgotten thin client on a desk.

---

## 🚀 Features

### Audio / Bells

- Automatic bell and anthem schedule per campus (cron-based, configurable through the web panel)
- Manual control: play / stop / pause / next / prev / seek — per campus or all at once
- Volume and a 10-band equalizer with **real FFT audio analysis** (not a mock — it actually listens to what's playing on the speakers and renders the spectrum live in the browser)
- PA announcements with campus selection
- Playlists, track uploads, PIN-protected folders

### Voice AI Assistant

- Offline speech recognition (faster-whisper)
- Context-aware replies via Claude AI
- Spoken responses via edge-tts
- Instant execution of campus commands by voice (stop, next track, volume)

### Monitoring

- Grafana + Prometheus + Loki — metrics (CPU/RAM/disk/temperature) and logs from every machine in one place
- Per-campus dashboards plus a fleet-wide overview
- `node_exporter` on every machine, `promtail` shipping logs centrally

### Web Panel (Flask)

- Role-based users (admin / staff / viewer), profiles, avatars
- Live chat between staff inside the panel
- Announcements with pinning and priority levels
- Thin client management (add / edit / delete / wake over the network — Wake-on-LAN)
- Web terminal with SSH access to campus machines (admins only)
- Activity log, cron job status, action history
- Backups — a separate PIN-protected page with reports and downloads

### Auto-Recovery & Backups

- `watchdog` checks every service's health every 5 minutes and restarts anything down
- `recovery` — a dedicated container that backs up the server and every campus, restoring from an image on total machine failure
- Full weekly backup to dedicated storage

### Telegram Bots (one per campus)

- `/play`, `/stop`, `/status`, `/volup`, `/voldown`, `/history`, `/server`, `/time`, and more — full remote control straight from Telegram
- Event notifications: bell start/stop, logins, failures, backup status

### Thin Clients

- A single install script (`install.sh`) — spins up a new campus from scratch on a clean Ubuntu box: player, cron schedule, monitoring, systemd services

---

## 🏗 Architecture

```text
                     ┌─────────────────────────┐
                     │      Central server      │
                     │     (Docker Compose)     │
                     │                          │
                     │  Web UI (Flask) ─────────┼──── Users (browser)
                     │  Grafana/Prometheus/Loki │
                     │  Telegram bots (xN)      │
                     │  Watchdog + Recovery     │
                     └───────────┬──────────────┘
                                 │ SSH / node_exporter / promtail
                 ┌───────────────┴───────────────┐
                 ▼                                ▼
         ┌───────────────┐               ┌───────────────┐
         │   Campus A     │               │   Campus B     │
         │  mpv + player  │               │  mpv + player  │
         │  node_exporter │               │  node_exporter │
         │  audio-analyzer│               │  audio-analyzer│
         └───────────────┘               └───────────────┘
```

Each campus is a physical machine (thin client / mini-PC) running a local `mpv` player controlled over an IPC socket. The central server never proxies audio — it only sends commands over SSH, while the sound itself plays physically on the campus speakers.

---

## 🛠 Tech Stack

| Component | Stack |
| --- | --- |
| Backend / web panel | Python 3, Flask, Flask-Login, SQLite, paramiko (SSH) |
| Audio engine | mpv (IPC), PulseAudio, real-time FFT (numpy) |
| Voice assistant | faster-whisper (STT), Claude AI, edge-tts (TTS) |
| Telegram bots | python-telegram-bot |
| Monitoring | Grafana, Prometheus, Loki, Promtail, node_exporter |
| Infrastructure | Docker Compose, systemd, bash |
| Frontend | Vanilla JS, Amplitude.js, Butterchurn (visualization) |

The whole project is **Python + Bash**, deployed via **Docker Compose** on the server and **systemd services** on every campus.

---

## ⚡ Quick Start

### Central server

```bash
git clone <repo>
cd genesis
cp .env.example .env      # fill in tokens, passwords, paths
docker compose --profile logs --profile bot --profile watchdog --profile recovery up -d
```

Done — Grafana on `:3000`, the web panel on `:8090`, bots running, watchdog automatically watching everything.

### New campus (thin client)

On a clean Ubuntu machine at the campus:

```bash
bash machines/<campus>/install.sh
```

The script installs the player, monitoring, cron schedule, and every systemd service — from a bare machine to a fully working campus in one command.

---

## 🔐 Security

All passwords, tokens, and SSH keys live in `.env` and a private `campus-secrets` store — no secret is ever hardcoded in the code. `.env.example` contains only the structure, no real values.

---

## 🙏 Credits

- **our network admin** — for the idea that really got this moving in the right direction
- **our sysadmin** — for showing how to actually find my way around all of this

And my team — for the moral support on the way from one forgotten thin client to a full-blown infrastructure.
