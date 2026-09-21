"""Исполнение python-кода модели в одноразовом docker-контейнере без сети и без доступа к хосту."""
import subprocess

IMAGE = "cestand-sandbox"
TIMEOUT = 10
HEAD, TAIL = 20, 20
MAX_BYTES = 64_000

DOCKER_ARGS = [
    "docker", "run", "--rm", "-i",
    "--network", "none",
    "--memory", "512m", "--memory-swap", "512m",
    "--cpus", "1",
    "--pids-limit", "64",
    "--read-only", "--tmpfs", "/tmp:size=64m,exec",
    "--security-opt", "no-new-privileges",
    "--cap-drop", "ALL",
    IMAGE, "timeout", str(TIMEOUT), "python", "-I", "-",
]


def trim(text, head=HEAD, tail=TAIL):
    text = text[:MAX_BYTES]
    lines = text.splitlines()
    if len(lines) <= head + tail:
        return text
    return "\n".join(lines[:head] + [f"... пропущено {len(lines) - head - tail} строк ..."] + lines[-tail:])


def run(code):
    """-> dict(stdout, stderr, rc, timeout). Код уходит через stdin, обратно только текст."""
    try:
        p = subprocess.run(DOCKER_ARGS, input=code.encode(), capture_output=True, timeout=TIMEOUT + 15)
    except subprocess.TimeoutExpired:
        return {"stdout": "", "stderr": "sandbox: контейнер не ответил", "rc": -1, "timeout": True}
    out, err = p.stdout.decode(errors="replace"), p.stderr.decode(errors="replace")
    timed_out = p.returncode == 124
    if timed_out:
        err += f"\nsandbox: превышен лимит {TIMEOUT} с"
    return {"stdout": trim(out), "stderr": trim(err), "rc": p.returncode, "timeout": timed_out}


def build():
    import os
    d = os.path.dirname(os.path.abspath(__file__))
    subprocess.run(["docker", "build", "-t", IMAGE, d], check=True)


if __name__ == "__main__":
    # проверка изоляции: каждая строка должна не навредить хосту и вернуть ошибку или таймаут
    import sys
    if "--build" in sys.argv:
        build()
    tests = {
        "ok": "print(2+2)",
        "rm": "import shutil,os; shutil.rmtree('/', ignore_errors=True); print(os.listdir('/'))",
        "loop": "while True: pass",
        "net": "import urllib.request; print(urllib.request.urlopen('http://example.com', timeout=3).status)",
        "flood": "print('x'*10_000_000)",
        "fork": "import os\nwhile True: os.fork()",
        "write": "open('/usr/bin/x','w').write('1')",
        "mem": "a=bytearray(2_000_000_000)",
    }
    for k, code in tests.items():
        r = run(code)
        print(f"{k:6} rc={r['rc']:4} timeout={r['timeout']} out={r['stdout'][:60]!r} err={r['stderr'][-80:]!r}")
