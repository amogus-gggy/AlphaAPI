from __future__ import annotations

import pytest
from alphaapi import Application, JsonResponse, cli, path
from alphaapi.cli import main
from alphaapi.urls import clear_patterns


def test_routes_command_lists_resolved_patterns(monkeypatch, capsys):
    clear_patterns()

    async def index(request):
        return JsonResponse({"ok": True})

    app = Application(urlpatterns=[path("", index, name="index")])
    monkeypatch.setattr(cli, "load_app", lambda target: app)

    main(["routes", "demo.app:app"])

    captured = capsys.readouterr()
    assert "index" in captured.out
    assert "/" in captured.out
    assert "1 route(s)" in captured.out


def test_check_command_reports_success(monkeypatch, capsys, settings_override):
    settings_override(ALLOWED_HOSTS=["*"], SECRET_KEY="secret", DEBUG=False)
    app = Application(urlpatterns=[])
    monkeypatch.setattr(cli, "load_app", lambda target: app)

    main(["check", "demo.app:app"])

    captured = capsys.readouterr()
    assert "no issues" in captured.out


def test_check_command_warns_about_missing_secret(monkeypatch, capsys, settings_override):
    settings_override(ALLOWED_HOSTS=["*"], SECRET_KEY="", DEBUG=True)
    app = Application(urlpatterns=[])
    monkeypatch.setattr(cli, "load_app", lambda target: app)

    main(["check", "demo.app:app"])

    captured = capsys.readouterr()
    assert "warning" in captured.out.lower()
    assert "SECRET_KEY" in captured.out


def test_check_command_fails_on_empty_allowed_hosts(
    monkeypatch, capsys, settings_override
):
    settings_override(ALLOWED_HOSTS=[])
    app = Application(urlpatterns=[])
    monkeypatch.setattr(cli, "load_app", lambda target: app)

    with pytest.raises(SystemExit) as exc_info:
        main(["check", "demo.app:app"])

    assert exc_info.value.code == 1
    captured = capsys.readouterr()
    assert "ALLOWED_HOSTS is empty" in captured.out


def test_cli_parser_accepts_settings_option(monkeypatch, settings_override):
    import os

    settings_override(ALLOWED_HOSTS=["*"])
    app = Application(urlpatterns=[])
    monkeypatch.setattr(cli, "load_app", lambda target: app)
    monkeypatch.delenv("ALPHAAPI_SETTINGS_MODULE", raising=False)

    try:
        main(["check", "demo.app:app", "--settings", "demo.settings"])
        assert os.environ["ALPHAAPI_SETTINGS_MODULE"] == "demo.settings"
    finally:
        os.environ.pop("ALPHAAPI_SETTINGS_MODULE", None)
