"""Local web app: a FastAPI backend serving the Vue frontend built into ``static/``.

Needs the ``app`` extra: ``pip install swirl-spectra[app]``.
"""

from __future__ import annotations

import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from swirl._version import __version__
from swirl.app.api import build_router
from swirl.app.workspace import Workspace

STATIC_DIR = Path(__file__).parent / "static"

_NOT_BUILT = """<!doctype html><meta charset="utf-8"><title>SWIRL</title>
<body style="font-family:sans-serif;max-width:40rem;margin:4rem auto">
<h1>SWIRL API is running</h1>
<p>The graphical interface has not been built. From the repository root:</p>
<pre>cd frontend && npm install && npm run build</pre>
<p>The API itself is documented at <a href="/docs">/docs</a>.</p></body>"""


def create_app(workspace: Workspace | None = None, static_dir: Path | None = STATIC_DIR) -> FastAPI:
    app = FastAPI(title="SWIRL", version=__version__)
    app.include_router(build_router(workspace or Workspace()))
    if static_dir is not None and (static_dir / "index.html").exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="frontend")
    else:

        @app.get("/", response_class=HTMLResponse)
        def not_built() -> str:
            return _NOT_BUILT

    return app


def launch(host: str = "127.0.0.1", port: int = 8765, open_browser: bool = True) -> None:
    import uvicorn

    url = f"http://{host}:{port}/"
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()
    print(f"SWIRL running at {url}  (Ctrl+C to stop)")
    uvicorn.run(create_app(), host=host, port=port, log_level="warning")
