"""Upload player status fix to the live VDS. DB is not touched."""
import os
import sys
import time

import paramiko

HOST, PORT, USER = "2.27.248.113", 22, "root"
PASSWORD = os.environ.get("RA_VDS_PASS", "dens445566")
REMOTE_DIR = "/var/www/checkapp/site"
LOCAL = r"C:\Users\User\Desktop\rustapp.io"
FILES = [
    "server.py",
    "mock-local.js",
    "index.html",
    "plugin/RustApp.cs",
    "local/RustApp.cs",
]


def sh(client, cmd, timeout=180):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode(errors="replace")
    err = stderr.read().decode(errors="replace")
    code = stdout.channel.recv_exit_status()
    return code, out, err


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, port=PORT, username=USER, password=PASSWORD,
                   timeout=25, allow_agent=False, look_for_keys=False)
    print("connected")
    sftp = client.open_sftp()
    try:
        for rel in FILES:
            src = os.path.join(LOCAL, rel.replace("/", os.sep))
            dst = f"{REMOTE_DIR}/{rel}"
            sftp.put(src, dst)
            print(rel, os.path.getsize(src), "->", sftp.stat(dst).st_size)
    finally:
        sftp.close()
    code, out, err = sh(client, f"bash {REMOTE_DIR}/restart-site.sh", timeout=180)
    print("restart", code)
    print(out[-800:] if out else "")
    if err.strip():
        print("stderr", err[-400:])
    time.sleep(2)
    code, out, err = sh(
        client,
        "python3 -m py_compile /var/www/checkapp/site/server.py && "
        "grep -n 'player.status' /var/www/checkapp/site/server.py | head -5 && "
        "grep -n 'mock-local.js?v=' /var/www/checkapp/site/index.html && "
        "curl -s -m 8 http://127.0.0.1:8081/ | grep -o 'mock-local.js?v=[0-9]*'",
    )
    print("verify", out)
    if err.strip():
        print("stderr", err[-300:])
    client.close()
    return 0 if code == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
