"""Изоляция песочницы: код модели не вредит хосту и возвращает ошибку или таймаут. Нужен docker и образ
cestand-sandbox (docker build -t cestand-sandbox ace/env)."""
import pytest

from ace.env import Sandbox, sandbox

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
    assert Sandbox().run_python("print(2+2)") == "[stdout]\n4\n\n[stderr]"


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


@docker
def test_attempt_container():
    """Контейнер на попытку: файл из одного вызова виден в следующем, в другой попытке — нет; изоляция та же."""
    first, second = Sandbox(per="attempt").open(), Sandbox(per="attempt").open()
    try:
        [run1] = first.tools
        [run2] = second.tools
        assert run1("open('/tmp/x', 'w').write('kept')").startswith("[stdout]")
        assert "kept" in run1("print(open('/tmp/x').read())")
        assert "FileNotFoundError" in run2("print(open('/tmp/x').read())")
        assert "Read-only file system" in run1("open('/usr/bin/x','w').write('1')")
        assert "URLError" in run1("import urllib.request; urllib.request.urlopen('http://example.com', timeout=3)")
    finally:
        first.close()
        second.close()
    assert sandbox.run("print(1)", first.container)["rc"] != 0     # контейнер убран


def test_call_container_is_shared_env():
    """Контейнер на вызов: среда попытки — сама песочница, без состояния."""
    env = Sandbox()
    assert env.open() is env and [t.__name__ for t in env.tools] == ["run_python"]


@docker
def test_kernel_host_timeout():
    """Код, держащий GIL, ядро не прерывает — хост убивает контейнер после timeout и запаса; модели — текст о
    пределе времени; нехватка памяти — текст о смерти ядра; дальше — новое ядро с чистыми переменными."""
    from ace import render
    from ace.env import tfgrpo
    kernel = tfgrpo.Kernel()
    grace = tfgrpo.DOCKER_GRACE
    try:
        tfgrpo.DOCKER_GRACE = 3
        assert "'success': True" in kernel.call('{"code": "x = 1\\nprint(x)"}')
        assert kernel.call('{"code": "pow(3, 10**10)", "timeout": 1}') == render.kernel_timeout(1)
        assert kernel.call('{"code": "x = bytearray(900 * 1024 * 1024)"}') == render.KERNEL_DIED
        assert "NameError" in kernel.call('{"code": "print(x)"}')
    finally:
        tfgrpo.DOCKER_GRACE = grace
        kernel.close()


@docker
def test_timeout_ignoring_sigterm():
    """Код, который глушит SIGTERM, добивается SIGKILL-ом сразу после предела: вызов не держит лишние 15 с."""
    import time
    t0 = time.time()
    r = sandbox.run("import signal, time\nsignal.signal(signal.SIGTERM, signal.SIG_IGN)\nwhile True: time.sleep(0.1)", limit=2)
    assert r["timeout"] and time.time() - t0 < 2 + sandbox.DOCKER_GRACE
