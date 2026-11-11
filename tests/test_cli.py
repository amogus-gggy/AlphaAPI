from __future__ import annotations

import signal
import socket
import subprocess
import sys
import time

import pytest

from alphaapi.cli import main
from alphaapi.scaffold import ScaffoldError, startapp, startproject


def test_cli_startproject_and_startapp(tmp_path):
    target = tmp_path / "site"
    main(["startproject", "demo", str(target)])
    main(["startapp", "blog", str(target)])

    assert (target / "manage.py").exists()
    assert (target / "demo" / "settings.py").exists()
    assert (target / "demo" / "urls.py").exists()
    assert (target / "demo" / "app.py").exists()
    assert (target / "blog" / "apps.py").exists()
    assert (target / "blog" / "urls.py").exists()

    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import asyncio; "
                "import demo.app as demo; "
                "import demo.views as views; "
                "import blog.apps as blog; "
                "demo.app._ensure_resolved(); "
                "print(demo.app.reverse('index')); "
                "print(blog.BlogConfig().name); "
                "page = asyncio.run(views.index(None)); "
                "print(page.status_code); "
                "print(page.body.decode())"
            ),
        ],
        cwd=target,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    lines = result.stdout.splitlines()
    assert lines[:3] == ["/", "blog", "200"]
    page = "\n".join(lines[3:])
    assert "The install worked successfully! Congratulations!" in page
    assert "AlphaAPI" in page
    assert "demo" in page


def test_startproject_rejects_non_empty_destination(tmp_path):
    target = tmp_path / "site"
    target.mkdir()
    (target / "existing.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(ScaffoldError):
        startproject("demo", target)


def test_startapp_rejects_invalid_name(tmp_path):
    with pytest.raises(ScaffoldError):
        startapp("not-a-package", tmp_path)


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def test_generated_manage_py_exits_on_sigint(tmp_path):
    target = tmp_path / "site"
    startproject("demo", target)
    port = _free_port()

    process = subprocess.Popen(
        [sys.executable, "manage.py", "--port", str(port)],
        cwd=target,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        for _ in range(200):
            if process.poll() is not None:
                break
            try:
                with socket.create_connection(("127.0.0.1", port), timeout=0.1):
                    break
            except OSError:
                time.sleep(0.02)
        else:
            pytest.fail("generated project did not start")

        assert process.poll() is None
        process.send_signal(signal.SIGINT)
        try:
            code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            pytest.fail("manage.py ignored SIGINT")
        assert code == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait()

