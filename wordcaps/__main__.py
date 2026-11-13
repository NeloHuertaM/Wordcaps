from __future__ import annotations

import argparse
import webbrowser

from . import VERSION
from .server import App, serve


def main() -> None:
    parser = argparse.ArgumentParser(prog="wordcaps", description="Subtítulos animados palabra a palabra para DaVinci Resolve.")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    options = parser.parse_args()

    app = App()
    server = serve(app, options.port)
    url = f"http://127.0.0.1:{options.port}/"
    print(f"WordCaps {VERSION} en {url}  (Ctrl+C para salir)")
    if not options.no_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
