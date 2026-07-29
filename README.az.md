<div align="center">

<img src="docs/banner.svg" alt="Genesis" width="100%">

# Genesis

🇬🇧 [English](README.md) · 🇷🇺 [Русский](README.ru.md) · 🇦🇿 Azərbaycan

**Bir neçə kampusda məktəb audio yayımı, monitorinq və İT infrastrukturunun idarə edilməsi üçün mərkəzləşdirilmiş platforma.**

![Python](https://img.shields.io/badge/Python-3-3776AB?logo=python&logoColor=white)
![Docker](https://img.shields.io/badge/Docker-Compose-2496ED?logo=docker&logoColor=white)
![Flask](https://img.shields.io/badge/Flask-web%20UI-000000?logo=flask&logoColor=white)
![Grafana](https://img.shields.io/badge/Grafana-monitoring-F46800?logo=grafana&logoColor=white)
![Telegram](https://img.shields.io/badge/Telegram-bots-26A5E4?logo=telegram&logoColor=white)

</div>

One server, several physical sites, a single web panel, Telegram bots, and a voice AI assistant — all built from scratch by one person, growing since 2026.

---

## 📖 Tarixçə

Hər şey **naməlum istehsalçının bir nazik klientindən** başladı — sadəcə məktəbdə zəngin vaxtında çalması lazım idi. Bu gün bu, tam hüquqlu infrastruktura çevrilib: mərkəzi server, Grafana vasitəsilə bütün maşın parkının monitorinqi, hər kampus üçün ayrıca audio idarəetmə (və ya hamısı birdən), avtomatik ehtiyat nüsxələmə və bərpa, tam idarəetmə ilə veb-panel və Whisper + Claude əsasında səsli assistent.

Bu yolda məsləhət və dəstəklə kömək edən həmkarlara xüsusi təşəkkür — **şəbəkə adminimizə** (hər şeyi düzgün istiqamətə yönəldən fikir) və **sysadminimizə** (bütün bunlarda necə üzməyi göstərdi). Sizsiz bu, masada unudulmuş bir nazik klient olaraq qalardı.

---

## 🚀 Nə edə bilir

### Audio / Zənglər

- Hər kampus üçün avtomatik zəng və himn cədvəli (cron əsaslı, veb-panel vasitəsilə tənzimlənir)
- Əl ilə idarəetmə: play / stop / pause / next / prev / seek — ayrıca hər kampus üçün və ya hamısı birdən
- Səs səviyyəsi və **real FFT audio analizi** ilə 10-zolaqlı ekvalayzer (imitasiya deyil — həqiqətən kolonkalarda nə çalındığını dinləyir və spektri brauzerdə real vaxtda çəkir)
- Kampus seçimi ilə səsli elanlar
- Pleylistlər, trek yükləmə, PIN qorumalı qovluqlar

### Səsli AI-assistent

- Oflayn nitq tanıma (faster-whisper)
- Claude AI vasitəsilə mənalı cavablar
- edge-tts vasitəsilə səsli cavab
- Kampus əmrlərinin səslə ani icrası (dayan, növbəti trek, səs səviyyəsi)

### Monitorinq

- Grafana + Prometheus + Loki — bütün maşınlardan metrikalar (CPU/RAM/disk/temperatur) və loglar bir yerdə
- Hər kampus üçün ayrıca və bütün infrastruktur üzrə ümumi dashboard-lar
- Hər maşında `node_exporter`, `promtail` logları mərkəzləşdirilmiş şəkildə göndərir

### Veb-panel (Flask)

- Rol əsaslı istifadəçi sistemi (admin / staff / viewer), profillər, avatarlar
- Panel daxilində əməkdaşlar arasında canlı çat
- Bərkidilmə və prioritetlərlə elanlar
- Nazik klient idarəetməsi (əlavə et / redaktə et / sil / şəbəkə üzərindən oyat — Wake-on-LAN)
- Admin üçün kampus maşınlarına SSH girişi olan veb-terminal
- Fəaliyyət jurnalı, cron tapşırıqlarının statusu, əməliyyat tarixçəsi
- Ehtiyat nüsxələr — hesabatlar və yükləmə ilə ayrıca PIN qorumalı səhifə

### Avtomatik bərpa və ehtiyat nüsxələmə

- `watchdog` hər 5 dəqiqədən bir bütün servislərin sağlamlığını yoxlayır və dayananları yenidən başladır
- `recovery` — ayrıca konteyner: server və bütün kampusları ehtiyat nüsxələyir, maşının tam sıradan çıxması zamanı imicdən bərpa edir
- Xüsusi anbara həftəlik tam ehtiyat nüsxə

### Telegram-botlar (hər kampus üçün bir)

- `/play`, `/stop`, `/status`, `/volup`, `/voldown`, `/history`, `/server`, `/time` və digərləri — Telegram-dan birbaşa tam məsafədən idarəetmə
- Hadisə bildirişləri: zəngin başlaması/dayanması, giriş, nasazlıqlar, ehtiyat nüsxə statusu

### Nazik klientlər

- Tək əmrlə quraşdırma skripti (`install.sh`) — yeni kampusu təmiz Ubuntu üzərində sıfırdan qaldırır: pleyer, cron cədvəli, monitorinq, systemd servisləri

---

## 🏗 Arxitektura

```text
                     ┌─────────────────────────┐
                     │      Mərkəzi server      │
                     │     (Docker Compose)     │
                     │                          │
                     │  Web UI (Flask) ─────────┼──── İstifadəçilər (brauzer)
                     │  Grafana/Prometheus/Loki │
                     │  Telegram-botlar (xN)    │
                     │  Watchdog + Recovery     │
                     └───────────┬──────────────┘
                                 │ SSH / node_exporter / promtail
                 ┌───────────────┴───────────────┐
                 ▼                                ▼
         ┌───────────────┐               ┌───────────────┐
         │   Kampus A     │               │   Kampus B     │
         │  mpv + player  │               │  mpv + player  │
         │  node_exporter │               │  node_exporter │
         │  audio-analyzer│               │  audio-analyzer│
         └───────────────┘               └───────────────┘
```

Hər kampus — `mpv` lokal pleyerini IPC-soket üzərindən idarə edən fiziki maşındır (nazik klient / mini-PC). Mərkəzi server səsi heç vaxt proksiləmir — o, yalnız SSH üzərindən əmrlər göndərir, səs isə fiziki olaraq kampusun kolonkalarında çalır.

---

## 🛠 Texnologiyalar

| Komponent | Stek |
| --- | --- |
| Backend / veb-panel | Python 3, Flask, Flask-Login, SQLite, paramiko (SSH) |
| Audio mühərriki | mpv (IPC), PulseAudio, real-vaxt FFT (numpy) |
| Səsli assistent | faster-whisper (STT), Claude AI, edge-tts (TTS) |
| Telegram-botlar | python-telegram-bot |
| Monitorinq | Grafana, Prometheus, Loki, Promtail, node_exporter |
| İnfrastruktur | Docker Compose, systemd, bash |
| Frontend | Vanilla JS, Amplitude.js, Butterchurn (vizuallaşdırma) |

Layihə tamamilə **Python + Bash** üzərindədir, serverdə **Docker Compose**, hər kampusda isə **systemd servisləri** ilə yerləşdirilib.

---

## ⚡ Sürətli başlanğıc

### Mərkəzi server

```bash
git clone <repo>
cd genesis
cp .env.example .env      # token, parol, yolları doldurun
docker compose --profile logs --profile bot --profile watchdog --profile recovery up -d
```

Hazırdır — Grafana `:3000`-də, veb-panel `:8090`-da, botlar işə düşüb, watchdog hər şeyi avtomatik izləyir.

### Yeni kampus (nazik klient)

Kampusun təmiz Ubuntu maşınında:

```bash
bash machines/<campus>/install.sh
```

Skript özü pleyeri, monitorinqi, cron cədvəlini və bütün systemd servislərini quraşdırır — "çılpaq" maşından tam işlək kampusa qədər bir əmrlə.

---

## 🔐 Təhlükəsizlik haqqında

Bütün parollar, tokenlər və SSH açarları `.env` və şəxsi `campus-secrets`-də saxlanılır — kodda heç bir sirr yoxdur. `.env.example` faylı yalnız strukturu ehtiva edir, real dəyərlər olmadan.

---

## 🙏 Təşəkkürlər

- **şəbəkə adminimizə** — hər şeyi düzgün istiqamətə yönəldən fikrə görə
- **sysadminimizə** — bütün bunlarda necə istiqamətlənməyi göstərdiyinə görə

Və komandama — bir unudulmuş nazik klientdən tam hüquqlu infrastruktura gedən yolda mənəvi dəstəyə görə.
