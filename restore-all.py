#!/usr/bin/env python3
"""Восстановление Docker на 3 машинах. Пароли из credentials.env."""
import os
import sys
import pexpect

CRED = "/home/client2/credentials.env"
if os.path.isfile(CRED):
    with open(CRED, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                os.environ[k.strip()] = v.strip().strip("'\"")

CENTOS = ("kamran", "10.10.4.120", os.environ["CLIENT1_PASSWORD"])
CLIENT1 = ("client1", "10.20.0.41", os.environ["CLIENT_PASSWORD"])
DIR = os.path.dirname(os.path.abspath(__file__))


def run(cmd, user, host, pw, timeout=120):
    full = f'ssh -o StrictHostKeyChecking=no {user}@{host} "{cmd}"'
    c = pexpect.spawn(full, encoding="utf-8", timeout=timeout)
    c.logfile = sys.stdout
    idx = c.expect(["password:", "Password:", pexpect.EOF, pexpect.TIMEOUT])
    if idx in (0, 1):
        c.sendline(pw)
    c.expect([pexpect.EOF, pexpect.TIMEOUT], timeout=timeout)
    c.close()
    return c.exitstatus == 0 if c.exitstatus is not None else True


def scp(local, remote, user, host, pw, timeout=60):
    full = f"scp -o StrictHostKeyChecking=no -r {local} {user}@{host}:{remote}"
    c = pexpect.spawn(full, encoding="utf-8", timeout=timeout)
    c.logfile = sys.stdout
    idx = c.expect(["password:", "Password:", pexpect.EOF, pexpect.TIMEOUT])
    if idx in (0, 1):
        c.sendline(pw)
    c.expect([pexpect.EOF, pexpect.TIMEOUT], timeout=timeout)
    c.close()
    return c.exitstatus == 0 if c.exitstatus is not None else True


def main():
    u, h, pw = CENTOS
    print("=" * 50)
    print("1. CentOS: копирую campus-infra, перезапускаю...")
    print("=" * 50)
    scp(DIR, "/home/kamran/", u, h, pw)
    run(
        "cd /home/kamran/campus-infra && docker compose --profile bot --profile logs down; docker compose --profile bot --profile logs up -d",
        u, h, pw,
    )

    u, h, pw = CLIENT1
    print("\n" + "=" * 50)
    print("2. client1: Promtail...")
    print("=" * 50)
    run("mkdir -p /home/client1/log-promtail", u, h, pw)
    scp(f"{DIR}/promtail-clients/promtail-client1.yaml", "/home/client1/log-promtail/promtail-config.yaml", u, h, pw)
    run(
        "docker rm -f promtail 2>/dev/null; cd /home/client1/log-promtail && docker run -d --name promtail --restart unless-stopped "
        "-v /home/client1/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro "
        "-v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml",
        u, h, pw,
    )

    print("\n" + "=" * 50)
    print("3. client2: Promtail...")
    print("=" * 50)
    os.makedirs("/home/client2/log-promtail", exist_ok=True)
    import shutil
    shutil.copy(
        f"{DIR}/promtail-clients/promtail-client2.yaml",
        "/home/client2/log-promtail/promtail-config.yaml",
    )
    r = os.system("docker rm -f promtail 2>/dev/null; docker run -d --name promtail --restart unless-stopped "
        "-v /home/client2/log-promtail/promtail-config.yaml:/etc/promtail/config.yaml:ro "
        "-v /var/log:/var/log:ro grafana/promtail:2.9.5 -config.file=/etc/promtail/config.yaml")
    if r != 0:
        print("client2: docker run promtail — ошибка (Docker может быть не установлен)")
        sys.exit(1)

    print("\n" + "=" * 50)
    print("Готово. Grafana: http://10.10.4.120:3000 (admin/admin)")
    print("=" * 50)


if __name__ == "__main__":
    main()
