#!/usr/bin/env python3
"""Campus audio analyzer — PulseAudio monitor → FFT → /tmp/campus-audio-level.json
Runs as a persistent background process on client1/cgtk.
"""
import subprocess, struct, json, time, os, signal, sys, math
OUTPUT = '/tmp/campus-audio-level.json'
RATE   = 22050
CH     = 1
CHUNK  = 1024   # ~46 ms at 22050 Hz
BANDS  = 16     # output bands for visualizer

def find_monitor():
    try:
        out = subprocess.check_output(['pactl','list','sources','short'],
                                       stderr=subprocess.DEVNULL, text=True)
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
        ['pacat', '--record', f'--device={monitor}',
         f'--rate={RATE}', f'--channels={CH}', '--format=s16le', '--latency-msec=30', '--raw'],
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

    while True:
        try:
            data = proc.stdout.read(BYTES)
            if not data or len(data) < BYTES:
                time.sleep(0.02)
                continue

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
                samps = struct.unpack(f'{n}h', data)
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
    print(f"Analyzer started: {mon}", flush=True)
    run(mon)
