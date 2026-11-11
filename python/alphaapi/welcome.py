"""The default welcome page served by generated projects."""
from __future__ import annotations

from . import __version__


_WELCOME_PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>It worked! | AlphaAPI</title>
  <style>
    :root {
      color-scheme: light dark;
      --accent: #0c4b33;
      --accent-soft: #e7f3ed;
      --text: #1d2328;
      --muted: #5f6b73;
      --card: #ffffff;
      --page: #f4f7f5;
      --border: #dfe7e2;
    }
    @media (prefers-color-scheme: dark) {
      :root {
        --accent: #44b78b;
        --accent-soft: #14372a;
        --text: #edf3ef;
        --muted: #a8b5ae;
        --card: #1c2421;
        --page: #111815;
        --border: #2d3a34;
      }
    }
    * { box-sizing: border-box; }
    body {
      margin: 0;
      min-height: 100vh;
      display: grid;
      place-items: center;
      padding: 2rem;
      background: var(--page);
      color: var(--text);
      font: 16px/1.6 system-ui, -apple-system, Segoe UI, Roboto, sans-serif;
    }
    main {
      width: min(760px, 100%);
      padding: clamp(1.5rem, 5vw, 3rem);
      border: 1px solid var(--border);
      border-radius: 18px;
      background: var(--card);
      box-shadow: 0 20px 60px rgba(0, 0, 0, .08);
    }
    .badge {
      display: inline-block;
      padding: .25rem .65rem;
      border-radius: 999px;
      background: var(--accent-soft);
      color: var(--accent);
      font-size: .8rem;
      font-weight: 700;
      letter-spacing: .04em;
      text-transform: uppercase;
    }
    h1 { margin: .9rem 0 .4rem; font-size: clamp(1.8rem, 5vw, 2.6rem); line-height: 1.15; }
    h2 { margin-top: 2rem; font-size: 1.05rem; }
    p { color: var(--muted); }
    code {
      padding: .12rem .35rem;
      border-radius: 5px;
      background: var(--accent-soft);
      color: var(--accent);
      font: .9em ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
    }
    ul { padding-left: 1.2rem; }
    li { margin: .45rem 0; }
    a { color: var(--accent); }
    .footer { margin-top: 2rem; padding-top: 1rem; border-top: 1px solid var(--border); font-size: .9rem; }
  </style>
</head>
<body>
  <main>
    <span class="badge">AlphaAPI __VERSION__</span>
    <h1>The install worked successfully! Congratulations!</h1>
    <p>
      You just created the <strong>__PROJECT_NAME__</strong> project. You are seeing
      this page because it is served by <code>__PROJECT_NAME__/views.py</code>.
    </p>

    <h2>What can you do now?</h2>
    <ul>
      <li>Edit <code>__PROJECT_NAME__/urls.py</code> to add routes.</li>
      <li>Edit <code>__PROJECT_NAME__/views.py</code> to change this page.</li>
      <li>Add middleware in <code>__PROJECT_NAME__/settings.py</code>.</li>
      <li>Run <code>alphaapi startapp blog</code> to create a reusable app.</li>
      <li>Check the health endpoint at <a href="/health/">/health/</a>.</li>
    </ul>

    <p class="footer">
      This is an async-native, Django-shaped framework with no ORM. Bring your own
      data layer and start building.
    </p>
  </main>
</body>
</html>
"""


def welcome_page(project_name: str) -> str:
    """Return the default HTML welcome page."""
    return _WELCOME_PAGE.replace("__PROJECT_NAME__", project_name).replace(
        "__VERSION__", __version__
    )


__all__ = ["welcome_page"]
