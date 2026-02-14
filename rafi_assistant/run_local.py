import atexit
import os
import sys
import asyncio
import logging

# Steer Qt to PySide6's Qt6 before any Qt imports
os.environ.setdefault("QT_API", "pyside6")

import uvicorn
from qasync import QEventLoop
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QThreadPool

from src.main import app
from src.ui.desktop import MainWindow

logger = logging.getLogger("rafi.local")

# Module-level refs for cleanup
_server: uvicorn.Server | None = None
_window: MainWindow | None = None


class SignalingLogHandler(logging.Handler):
    """Custom logging handler that broadcasts logs to the ServiceRegistry."""

    def __init__(self, registry=None):
        super().__init__()
        self.registry = registry
        self._loop = asyncio.get_event_loop()
        self._is_broadcasting = False

    def set_registry(self, registry):
        self.registry = registry

    def emit(self, record):
        if self._is_broadcasting or not self.registry:
            return

        try:
            self._is_broadcasting = True
            msg = self.format(record)
            # Use thread-safe way to call the async broadcast
            if self._loop.is_running():
                asyncio.run_coroutine_threadsafe(
                    self.registry.broadcast_log(
                        record.levelname,
                        record.name,
                        msg
                    ),
                    self._loop
                )
        except Exception:
            self.handleError(record)
        finally:
            self._is_broadcasting = False


async def main():
    """Run FastAPI server and PySide6 UI in a shared qasync event loop."""
    global _server, _window

    config = uvicorn.Config(
        app,
        host="0.0.0.0",
        port=8000,
        log_level="info",
        reload=False,
        loop="asyncio",
    )
    _server = uvicorn.Server(config)
    _server.install_signal_handlers = lambda: None  # Qt handles signals

    # Attach signaling log handler to root logger BEFORE startup
    # so we can catch calibration/initialization logs.
    handler = SignalingLogHandler()
    handler.setFormatter(logging.Formatter("%(message)s"))
    logging.getLogger().addHandler(handler)

    server_task = asyncio.create_task(_server.serve())

    # Wait for FastAPI lifespan to init the ServiceRegistry
    print("Waiting for ServiceRegistry to initialize...", flush=True)
    for _ in range(200):  # up to ~20 seconds
        if hasattr(app.state, "registry"):
            break
        await asyncio.sleep(0.1)
    else:
        print("ERROR: ServiceRegistry did not initialize in time", flush=True)
        _server.should_exit = True
        await server_task
        return

    registry = app.state.registry
    handler.set_registry(registry)
    print("Registry ready. Launching UI.", flush=True)

    _window = MainWindow(registry)
    _window.show()
    print("UI shown. Server running on http://0.0.0.0:8000", flush=True)

    try:
        await server_task
    except asyncio.CancelledError:
        print("Local runner stopped")
    finally:
        # Stop the visualizer timer immediately so Qt won't call into
        # Python after the event loop is torn down (prevents the
        # "Error calling Python override of QObject::timerEvent()" crash).
        if _window is not None:
            _window.visualizer.stop()


def _shutdown():
    """Called by QApplication.aboutToQuit — clean up before Qt exits."""
    # Stop the visualizer timer and UI tasks
    if _window is not None:
        _window.visualizer.stop()

    # Tell uvicorn to exit gracefully
    if _server is not None:
        _server.should_exit = True

    # Cancel all pending asyncio tasks so qasync can close cleanly
    try:
        loop = asyncio.get_event_loop()
        for task in asyncio.all_tasks(loop):
            task.cancel()
    except RuntimeError:
        pass


def _force_exit():
    """atexit handler: bypass Py_FinalizeEx to avoid PySide6 thread crash.

    PySide6's module-level atexit handler destroys QCoreApplication, which
    calls QThread::~QThread() on still-running QThreadPool workers.  That
    triggers QMessageLogger::fatal() → abort().  Calling os._exit() here
    skips Py_FinalizeEx entirely, side-stepping the bug.  All real cleanup
    (FastAPI lifespan, channel shutdown, scheduler stop) has already run
    by this point via the aboutToQuit signal and the finally block below.
    """
    # Drain the Qt global thread pool first (best-effort)
    QThreadPool.globalInstance().waitForDone(2000)  # 2 s max
    os._exit(0)


if __name__ == "__main__":
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)

    # Register os._exit() FIRST so it runs LAST (atexit is LIFO).
    # PySide6 registers its own atexit handler at import time, so ours
    # will execute before PySide's, preventing the crash.
    atexit.register(_force_exit)

    qt_app = QApplication(sys.argv)
    qt_app.aboutToQuit.connect(_shutdown)

    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)

    try:
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        print("\nShutting down...")
    finally:
        # Stop the visualizer timer FIRST — before anything else touches
        # the event loop — so Qt never tries to call into a Python object
        # that's being torn down.
        if _window is not None:
            _window.visualizer.stop()

        # Give cancelled tasks a moment to finish
        try:
            loop.run_until_complete(asyncio.sleep(0.1))
        except Exception:
            pass
        loop.close()
        # Exit immediately — don't let Py_FinalizeEx reach PySide6's
        # atexit handler which crashes destroying running QThreads.
        # All real cleanup already ran (FastAPI lifespan, aboutToQuit).
        QThreadPool.globalInstance().waitForDone(2000)
        os._exit(0)
