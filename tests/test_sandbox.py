"""Изоляция песочницы: код модели не вредит хосту и возвращает ошибку или таймаут. Нужен docker и образ
cestand-sandbox (docker build -t cestand-sandbox ace/env)."""
import pytest

from ace.env import run_python, sandbox

docker = pytest.mark.skipif(not sandbox.available(), reason="нет docker или образа песочницы")


def test_trim():
    text = "\n".join(map(str, range(100)))
    lines = sandbox.trim(text).splitlines()
    assert lines[:2] == ["0", "1"] and lines[-1] == "99"
    assert lines[sandbox.HEAD_LINES] == "... 60 lines omitted ..."
    assert len(lines) == sandbox.HEAD_LINES + sandbox.TAIL_LINES + 1


@docker
def test_ok():
    r = sandbox.run("print(2+2)")
    assert (r["stdout"], r["rc"], r["timeout"]) == ("4\n", 0, False)
    assert run_python("print(2+2)") == "[stdout]\n4\n\n[stderr]"


@docker
def test_rm_root():
    r = sandbox.run("import shutil,os; shutil.rmtree('/', ignore_errors=True); print(os.listdir('/'))")
    assert "bin" in r["stdout"]


@docker
def test_endless_loop():
    r = sandbox.run("while True: pass")
    assert r["timeout"] and r["rc"] == sandbox.TIMEOUT_RC
    assert r["stderr"].strip() == f"sandbox: time limit of {sandbox.TIMEOUT} s exceeded"


@docker
def test_no_network():
    r = sandbox.run("import urllib.request; print(urllib.request.urlopen('http://example.com', timeout=3).status)")
    assert r["rc"] != 0 and "URLError" in r["stderr"]


@docker
def test_output_flood():
    r = sandbox.run("print('x'*10_000_000)")
    assert len(r["stdout"]) <= sandbox.MAX_BYTES


@docker
def test_fork_bomb():
    r = sandbox.run("import os\nwhile True: os.fork()")
    assert r["rc"] != 0 or r["timeout"]


@docker
def test_write_system():
    r = sandbox.run("open('/usr/bin/x','w').write('1')")
    assert r["rc"] != 0 and "Read-only file system" in r["stderr"]


@docker
def test_memory_limit():
    r = sandbox.run("a=bytearray(2_000_000_000)")
    assert r["rc"] != 0
