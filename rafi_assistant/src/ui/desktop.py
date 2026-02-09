import sys
import asyncio
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QLabel, QTextEdit, QPushButton, QGridLayout
)
from PySide6.QtCore import Qt, Signal, Slot
from qasync import QEventLoop, asyncSlot

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, registry):
        super().__init__()
        self.registry = registry
        self.setWindowTitle("Rafi Desktop Assistant")
        self.setMinimumSize(800, 600)

        # Main Layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        self.main_layout = QVBoxLayout(central_widget)

        # Status Tiles
        self.status_layout = QGridLayout()
        self.main_layout.addLayout(self.status_layout)

        self.voice_status = QLabel("Voice: Idle")
        self.voice_status.setStyleSheet("background-color: #333; color: white; padding: 10px; border-radius: 5px;")
        self.status_layout.addWidget(self.voice_status, 0, 0)

        self.camera_status = QLabel("Camera: Off")
        self.camera_status.setStyleSheet("background-color: #333; color: white; padding: 10px; border-radius: 5px;")
        self.status_layout.addWidget(self.camera_status, 0, 1)

        self.task_summary = QLabel("Tasks: 0 pending")
        self.task_summary.setStyleSheet("background-color: #333; color: white; padding: 10px; border-radius: 5px;")
        self.status_layout.addWidget(self.task_summary, 0, 2)

        # Transcript Console
        self.transcript_label = QLabel("Transcript Console:")
        self.main_layout.addWidget(self.transcript_label)
        
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("background-color: #000; color: #0f0; font-family: monospace;")
        self.main_layout.addWidget(self.console)

        # Action Buttons
        self.button_layout = QHBoxLayout()
        self.main_layout.addLayout(self.button_layout)

        self.mic_toggle = QPushButton("Start Listening")
        self.mic_toggle.clicked.connect(self.on_mic_toggle)
        self.button_layout.addWidget(self.mic_toggle)

        self.camera_toggle = QPushButton("Enable Camera")
        self.camera_toggle.clicked.connect(self.on_camera_toggle)
        self.button_layout.addWidget(self.camera_toggle)

        self.screen_toggle = QPushButton("Share Screen")
        self.screen_toggle.clicked.connect(self.on_screen_toggle)
        self.button_layout.addWidget(self.screen_toggle)

        # Start background listener for registry events
        asyncio.create_task(self.listen_to_registry())

    async def listen_to_registry(self):
        """Monitor ServiceRegistry queues for updates."""
        logger.info("UI background listener started")
        
        # Poll the transcript queue
        while True:
            try:
                item = await self.registry.transcript_queue.get()
                text = item.get("text", "")
                is_final = item.get("is_final", True)
                
                self.append_to_console(f"{'[Final] ' if is_final else '[Live] '} {text}")
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in UI listener: {e}")
                await asyncio.sleep(1)

    def append_to_console(self, text):
        self.console.append(text)

    @asyncSlot()
    async def on_mic_toggle(self):
        """Toggle the conversation manager's listening state."""
        current_text = self.mic_toggle.text()
        if "Start" in current_text:
            self.mic_toggle.setText("Stop Listening")
            self.voice_status.setText("Voice: Listening")
            self.voice_status.setStyleSheet("background-color: #d00; color: white; padding: 10px; border-radius: 5px;")
            if self.registry.conversation:
                await self.registry.conversation.start_listening()
        else:
            self.mic_toggle.setText("Start Listening")
            self.voice_status.setText("Voice: Idle")
            self.voice_status.setStyleSheet("background-color: #333; color: white; padding: 10px; border-radius: 5px;")
            if self.registry.conversation:
                await self.registry.conversation.stop_listening()

    @asyncSlot()
    async def on_camera_toggle(self):
        """Toggle webcam capture."""
        current_text = self.camera_toggle.text()
        enabled = "Enable" in current_text
        
        if enabled:
            self.camera_toggle.setText("Disable Camera")
            self.camera_status.setText("Camera: Active")
            self.camera_status.setStyleSheet("background-color: #0d0; color: black; padding: 10px; border-radius: 5px;")
        else:
            self.camera_toggle.setText("Enable Camera")
            self.camera_status.setText("Camera: Off")
            self.camera_status.setStyleSheet("background-color: #333; color: white; padding: 10px; border-radius: 5px;")
            
        if self.registry.vision:
            await self.registry.vision.toggle_camera(enabled)

    @asyncSlot()
    async def on_screen_toggle(self):
        """Toggle screen capture."""
        current_text = self.screen_toggle.text()
        enabled = "Share" in current_text
        
        if enabled:
            self.screen_toggle.setText("Stop Sharing")
            self.camera_status.setText("Screen: Active")
            self.camera_status.setStyleSheet("background-color: #00d; color: white; padding: 10px; border-radius: 5px;")
        else:
            self.screen_toggle.setText("Share Screen")
            self.camera_status.setText("Screen: Off")
            self.camera_status.setStyleSheet("background-color: #333; color: white; padding: 10px; border-radius: 5px;")

        if self.registry.vision:
            await self.registry.vision.toggle_screen(enabled)

def start_ui(registry):
    """Entry point to start the PySide6 UI with qasync loop."""
    from PySide6.QtWidgets import QApplication
    
    app = QApplication(sys.argv)
    loop = QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(registry)
    window.show()

    with loop:
        loop.run_forever()
