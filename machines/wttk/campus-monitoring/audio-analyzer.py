#!/usr/bin/env python3
"""Campus audio analyzer — PulseAudio monitor → FFT → /tmp/campus-audio-level.json
Runs as a persistent background process on client1/wttk.
"""
import subprocess, struct, json, time, os, signal, sys, math
OUTPUT = '/tmp/campus-audio-level.json'
RATE   = 22050
CH     = 1
CHUNK  = 1024   # ~46 ms at 22050 Hz
BANDS  = 16     # output bands for visualizer

def find_monitor():
    # mpv запускается с --ao=pulse (без --audio-device) — значит звук всегда
    # идёт через ТЕКУЩИЙ default sink PulseAudio, каким бы он ни был на этой
    # машине (USB-звук, встроенный analog, HDMI — неважно). Раньше здесь был
    # хардкод "ищем monitor с 'usb' в имени" — работало только на client1 (у
    # него реально USB-звуковая карта), а на любой другой машине без USB-звука
    # (например wttk — только встроенный аудиочип) find_monitor() всегда
    # возвращал None, и весь сервис падал в бесконечный restart-loop.
    # get-default-sink появился в поздних версиях pactl — на старом
    # PulseAudio (например Ubuntu 16.04) его нет, парсим `pactl info` вместо
    # этого (стабильная, давно существующая команда).
    try:
        info = subprocess.check_output(['pactl', 'info'],
                                        stderr=subprocess.DEVNULL, universal_newlines=True)
        default_sink = None
        for line in info.splitlines():
            if line.startswith('Default Sink:'):
                default_sink = line.split(':', 1)[1].strip()
                break
        if default_sink:
            monitor = default_sink + '.monitor'
            out = subprocess.check_output(['pactl', 'list', 'sources', 'short'],
                                           stderr=subprocess.DEVNULL, universal_newlines=True)
            if monitor in out:
                return monitor
    except Exception:
        pass
    # Фолбэк — старое поведение (USB-звук, как на client1)
    try:
        out = subprocess.check_output(['pactl','list','sources','short'],
                                       stderr=subprocess.DEVNULL, universal_newlines=True)
        for line in out.splitlines():
            if "monitor" in line and "usb" in line.lower():
                cols = line.split('\t')
                if len(cols) > 1:
                    return cols[1]
    except Exception:
        pass
    return None

def make_log_bands(fft_size, rate, n_bands):
    """Map FFT bin indices to n_bands log-spaced frequency bands."""
    freqs = [i * rate / fft_size for i in range(fft_size // 2)]
    f_min, f_max = 30.0, rate / 2.0
    edges = [f_min * (f_max / f_min) ** (k / n_bands) for k in range(n_bands + 1)]
    groups = []
    for k in range(n_bands):
        lo, hi = edges[k], edges[k + 1]
        indices = [i for i, f in enumerate(freqs) if lo <= f < hi]
        groups.append(indices if indices else [max(0, int((lo + hi) / 2 * fft_size / rate))])
    return groups

def smooth_decay(prev, cur, attack=0.85, decay=0.72):
    return [cur[i] if cur[i] > prev[i] * attack
            else prev[i] * decay + cur[i] * (1 - decay)
            for i in range(len(cur))]

def run(monitor):
    try:
        import numpy as np
        HAS_NP = True
    except ImportError:
        HAS_NP = False

    proc = subprocess.Popen(
        ['pacat', '--record', '--device={}'.format(monitor),
         '--rate={}'.format(RATE), '--channels={}'.format(CH), '--format=s16le', '--latency-msec=30', '--raw'],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL
    )

    def bye(s, f):
        proc.terminate()
        with open(OUTPUT, 'w') as fp:
            json.dump({'bands': [0.0]*BANDS, 'rms': 0.0, 'active': False, 'ts': time.time()}, fp)
        sys.exit(0)
    signal.signal(signal.SIGTERM, bye)
    signal.signal(signal.SIGINT, bye)

    BYTES = CHUNK * CH * 2   # 2 bytes per s16le sample
    smooth = [0.0] * BANDS

    if HAS_NP:
        import numpy as np
        window = np.hanning(CHUNK).astype(np.float32)
        band_groups = make_log_bands(CHUNK, RATE, BANDS)

    buf = b''
    while True:
        try:
            # pacat может отдавать данные меньшими кусками, чем latency-msec
            # предполагает (особенно на старых версиях) — накапливаем буфер,
            # а не отбрасываем частичное чтение, иначе полный BYTES-чанк
            # может вообще никогда не набраться.
            chunk = proc.stdout.read(BYTES - len(buf))
            if not chunk:
                time.sleep(0.02)
                continue
            buf += chunk
            if len(buf) < BYTES:
                continue
            data = buf[:BYTES]
            buf = buf[BYTES:]

            if HAS_NP:
                samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
                windowed = samples * window
                spectrum = np.abs(np.fft.rfft(windowed)[:CHUNK // 2])
                spectrum /= (CHUNK / 2)
                raw = []
                for idx_list in band_groups:
                    raw.append(float(np.mean(spectrum[idx_list])) * 200.0)
                rms = float(np.sqrt(np.mean(samples ** 2)))
            else:
                # Pure-Python fallback: time-domain RMS with rough frequency simulation
                n = len(data) // 2
                samps = struct.unpack('{}h'.format(n), data)
                rms = math.sqrt(sum(s*s for s in samps) / n) / 32768.0
                raw = [rms * math.exp(-i * 0.13) * (0.8 + 0.2 * abs(math.sin(i * 1.7 + time.time())))
                       for i in range(BANDS)]

            rms = min(1.0, rms)
            raw = [min(1.0, max(0.0, v)) for v in raw]
            smooth = smooth_decay(smooth, raw)

            with open(OUTPUT, 'w') as fp:
                json.dump({
                    'bands': [round(v, 4) for v in smooth],
                    'rms':   round(rms, 4),
                    'active': rms > 0.002,
                    'ts':    round(time.time(), 3)
                }, fp)

        except Exception as e:
            time.sleep(0.05)

if __name__ == '__main__':
    mon = os.environ.get('AUDIO_MONITOR') or find_monitor()
    if not mon:
        print("No PulseAudio monitor found", file=sys.stderr)
        sys.exit(1)
    print("Analyzer started: {}".format(mon), flush=True)
    run(mon)
