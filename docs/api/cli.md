# Command line

The `alphaapi` command scaffolds projects, runs the server, and inspects an
application.

## Scaffold

```bash
alphaapi startproject mysite
alphaapi startapp blog
```

Both accept an optional destination directory:

```bash
alphaapi startproject mysite /tmp/mysite
alphaapi startapp blog /tmp/mysite
```

`startproject` creates `manage.py` and a project package with `app.py`,
`settings.py`, `urls.py`, and `views.py`. `startapp` creates `apps.py`,
`urls.py`, `views.py`, and `__init__.py`.

## Run the server

```bash
alphaapi runserver project.app:app
alphaapi runserver project.app:app --host 0.0.0.0 --port 8000
alphaapi runserver project.app:app --workers 4
alphaapi runserver project.app:app --reload
alphaapi runserver project.app:app --settings project.settings
```

Options that are not supplied fall back to your settings module. This matters
for `--max-body-size` and `--access-log`, where the CLI default would otherwise
override project settings.

| Option | Meaning |
| --- | --- |
| `--host` | Bind address (default `127.0.0.1`) |
| `--port` | Port (default `8000`) |
| `--workers` | Tokio worker threads |
| `--max-body-size` | Maximum request body size in bytes |
| `--access-log` | Enable access logging |
| `--reload` | Restart when `.py` or `.toml` files change |
| `--settings` | Settings module, e.g. `project.settings` |

`run` is accepted as an alias for `runserver`.

## Inspect routes

```bash
alphaapi routes project.app:app
```

Prints every resolved route with its name and path, followed by a count. Routes
are resolved through the same URLconf machinery the server uses, so includes and
namespaces are reflected.

## Check configuration

```bash
alphaapi check project.app:app
```

`check` resolves and registers the application, then reports configuration
problems:

- An empty `ALLOWED_HOSTS` is an error, and the command exits with status `1`.
- An empty `SECRET_KEY` while `DEBUG=True` prints a warning.

When everything passes it prints `System check identified no issues.`

## Settings module

`--settings` sets `ALPHAAPI_SETTINGS_MODULE` before loading the app:

```bash
alphaapi check project.app:app --settings project.settings
```

Generated `manage.py` files are thin wrappers around the same CLI.

## Reference

::: alphaapi.cli.main

::: alphaapi.cli.load_app
