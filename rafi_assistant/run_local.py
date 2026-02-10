import os
import sys
import asyncio
import logging

# Steer Qt to PySide6's Qt6 before any Qt imports
os.environ.setdefault("QT_API", "pyside6")

import uvicorn
from qasync import QEventLoop
from PySide6.QtWidgets import QApplication

from src.main import app
from src.ui.desktop import MainWindow

logger = logging.getLogger("rafi.local")


async def main():
    """Run FastAPI server and PySide6 UI in a shared qasync event loop."""
    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
        loop="asyncio",
    )
    server = uvicorn.Server(config)
    server.install_signal_handlers = lambda: None  # Qt handles signals

    server_task = asyncio.create_task(server.serve())

    # Wait for FastAPI lifespan to init the ServiceRegistry
    print("Waiting for ServiceRegistry to initialize...", flush=True)
    for _ in range(200):  # up to ~20 seconds
        if hasattr(app.state, "registry"):
            break
        await asyncio.sleep(0.1)
    else:
        print("ERROR: ServiceRegistry did not initialize in time", flush=True)
        server.should_exit = True
        await server_task
        return

    registry = app.state.registry
    print("Registry ready. Launching UI.", flush=True)

    window = MainWindow(registry)
    window.show()
    print("UI shown. Server running on http://0.0.0.0:8000", flush=True)

    try:
        await server_task
    except asyncio.CancelledError:
        print("Local runner stopped")


if __name__ == "__main__":
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    qt_app = QApplication(sys.argv)
    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        loop.close()
