import asyncio
import sys
import logging
import uvicorn
from qasync import QEventLoop
from PySide6.QtWidgets import QApplication

# Import the FastAPI app from main
from src.main import app
# Import the UI components
from src.ui.desktop import MainWindow

logger = logging.getLogger("rafi.local")

async def main():
    """
    Main entry point for local testing.
    Runs the FastAPI server and the PySide6 UI in a shared event loop.
    """
    # 1. Start the FastAPI server (Twilio/Webhooks) in the background
    # Note: We use the shared loop, so we don't call uvicorn.run() which blocks
    config = uvicorn.Config(
        app, 
        host="0.0.0.0", 
        port=8000, 
        log_level="info",
        reload=False  # Reloading doesn't work well inside a custom loop
    )
    server = uvicorn.Server(config)
    
    # We launch the server task. This will trigger the FastAPI 'lifespan' 
    # which initializes all services and the ServiceRegistry.
    server_task = asyncio.create_task(server.serve())
    
    # 2. Wait for the Registry to be initialized in the app state
    logger.info("Waiting for ServiceRegistry to initialize...")
    while not hasattr(app.state, 'registry'):
        await asyncio.sleep(0.1)
    
    registry = app.state.registry
    logger.info("ServiceRegistry ready. Launching UI.")

    # 3. Create and show the desktop window
    # MainWindow directly connects to the same registry used by the backend
    window = MainWindow(registry)
    window.show()

    # 4. Keep the loop alive while the server (and UI) is running
    try:
        await server_task
    except asyncio.CancelledError:
        logger.info("Local runner stopped")

if __name__ == "__main__":
    # Ensure structured logging doesn't double-print in the UI loop
    logging.getLogger("uvicorn.error").setLevel(logging.INFO)
    
    # Initialize the Qt Application
    qt_app = QApplication(sys.argv)
    
    # Create the qasync event loop that integrates with PySide6
    loop = QEventLoop(qt_app)
    asyncio.set_event_loop(loop)
    
    try:
        # Run the main async function
        loop.run_until_complete(main())
    except KeyboardInterrupt:
        logger.info("Keyboard interrupt received, shutting down...")
    finally:
        # Proper cleanup of the loop
        loop.close()
