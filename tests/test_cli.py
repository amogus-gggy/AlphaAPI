from __future__ import annotations

import subprocess
import sys

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
                "import demo.app as demo, blog.apps as blog; "
                "demo.app._ensure_resolved(); "
                "print(demo.app.reverse('index')); "
                "print(blog.BlogConfig().name)"
            ),
        ],
        cwd=target,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["/", "blog"]


def test_startproject_rejects_non_empty_destination(tmp_path):
    target = tmp_path / "site"
    target.mkdir()
    (target / "existing.txt").write_text("keep me", encoding="utf-8")

    with pytest.raises(ScaffoldError):
        startproject("demo", target)


def test_startapp_rejects_invalid_name(tmp_path):
    with pytest.raises(ScaffoldError):
        startapp("not-a-package", tmp_path)
