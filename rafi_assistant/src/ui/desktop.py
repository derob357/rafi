import sys
import math
import asyncio
import logging
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QTextEdit, QPushButton, QSizePolicy, QLineEdit,
)
from PySide6.QtCore import Qt, QTimer, QRectF
from PySide6.QtGui import (
    QPainter, QColor, QRadialGradient, QFont, QPen, QBrush,
)
from qasync import QEventLoop, asyncSlot

logger = logging.getLogger(__name__)

# ── Colour palette (ADA-inspired dark sci-fi) ──────────────────────────
BG_DARK = "#0a0a1a"
PANEL_BG = "#10182a"
PANEL_BORDER = "#00a1c1"
ACCENT_CYAN = "#00d1ff"
ACCENT_BRIGHT = "#00ffff"
TEXT_PRIMARY = "#e0e0ff"
TEXT_DIM = "#8080b0"
CONSOLE_BG = "#080812"

# Common stylesheet fragments
PANEL_STYLE = (
    f"background-color: {PANEL_BG}; border: 1px solid {PANEL_BORDER}; "
    f"color: {TEXT_PRIMARY};"
)
BUTTON_STYLE = f"""
    QPushButton {{
        background: transparent;
        border: 1px solid {ACCENT_CYAN};
        color: {ACCENT_CYAN};
        padding: 8px 18px;
        font-family: 'Segoe UI', 'Helvetica Neue', sans-serif;
        font-size: 12px;
        letter-spacing: 2px;
        text-transform: uppercase;
    }}
    QPushButton:hover {{
        background: {ACCENT_CYAN};
        color: {BG_DARK};
    }}
    QPushButton:pressed {{
        background: {ACCENT_BRIGHT};
        color: {BG_DARK};
    }}
"""


class RafiVisualizer(QWidget):
    """Glowing, breathing circle with 'RAFI' text — painted via QPainter."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._time = 0.0
        self._active = False
        self._intensity = 0.0  # 0‒1 audio / speaking intensity
        self.setMinimumSize(200, 200)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # ~33 fps animation timer
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(30)

    # ── public API ──────────────────────────────────────────────────────
    def set_active(self, active: bool):
        self._active = active

    def set_intensity(self, value: float):
        self._intensity = max(0.0, min(1.0, value))

    # ── internals ───────────────────────────────────────────────────────
    def _tick(self):
        self._time += 0.03
        self.update()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)

        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        dim = min(w, h)

        base_radius = dim * 0.25

        # Breathing oscillation (idle) or audio-driven expansion (active)
        if self._active:
            radius = base_radius + self._intensity * dim * 0.06
        else:
            radius = base_radius + math.sin(self._time * 2.0) * dim * 0.015

        # ── Outer ambient glow ──────────────────────────────────────────
        glow_radius = radius * 2.0
        grad = QRadialGradient(cx, cy, glow_radius)
        grad.setColorAt(0.0, QColor(6, 182, 212, 30))
        grad.setColorAt(0.5, QColor(6, 182, 212, 10))
        grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(grad))
        painter.setPen(Qt.NoPen)
        painter.drawEllipse(QRectF(cx - glow_radius, cy - glow_radius,
                                   glow_radius * 2, glow_radius * 2))

        # ── Inner glow halo ─────────────────────────────────────────────
        halo_radius = radius * 1.3
        halo_grad = QRadialGradient(cx, cy, halo_radius)
        alpha = 50 if not self._active else 80
        halo_grad.setColorAt(0.0, QColor(34, 211, 238, alpha))
        halo_grad.setColorAt(0.7, QColor(34, 211, 238, alpha // 3))
        halo_grad.setColorAt(1.0, QColor(0, 0, 0, 0))
        painter.setBrush(QBrush(halo_grad))
        painter.drawEllipse(QRectF(cx - halo_radius, cy - halo_radius,
                                   halo_radius * 2, halo_radius * 2))

        # ── Main circle stroke ──────────────────────────────────────────
        pen_alpha = 200 if self._active else 130
        pen_width = 2.5 if self._active else 1.8
        pen = QPen(QColor(34, 211, 238, pen_alpha), pen_width)
        painter.setPen(pen)
        painter.setBrush(Qt.NoBrush)
        painter.drawEllipse(QRectF(cx - radius, cy - radius,
                                   radius * 2, radius * 2))

        # ── Second subtle outer ring ────────────────────────────────────
        outer_r = radius * 1.12
        painter.setPen(QPen(QColor(6, 182, 212, 40), 1.0))
        painter.drawEllipse(QRectF(cx - outer_r, cy - outer_r,
                                   outer_r * 2, outer_r * 2))

        # ── "RAFI" text ─────────────────────────────────────────────────
        font_size = max(16, int(dim * 0.09))
        font = QFont("Segoe UI", font_size, QFont.Bold)
        font.setLetterSpacing(QFont.AbsoluteSpacing, font_size * 0.35)
        painter.setFont(font)

        # Pulsing scale when active
        if self._active:
            scale = 1.0 + 0.05 * math.sin(self._time * 3.14)
            painter.save()
            painter.translate(cx, cy)
            painter.scale(scale, scale)
            painter.translate(-cx, -cy)

        # Text glow (draw twice: blurred shadow then crisp)
        glow_color = QColor(34, 211, 238, 160)
        text_color = QColor(224, 243, 255, 240)

        painter.setPen(glow_color)
        text_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        painter.drawText(text_rect, Qt.AlignCenter, "RAFI")

        painter.setPen(text_color)
        painter.drawText(text_rect, Qt.AlignCenter, "RAFI")

        if self._active:
            painter.restore()

        # ── Tiny orbiting dot (visual flair) ────────────────────────────
        orbit_r = radius * 1.06
        angle = self._time * 1.5
        dx = cx + orbit_r * math.cos(angle)
        dy = cy + orbit_r * math.sin(angle)
        painter.setPen(Qt.NoPen)
        painter.setBrush(QColor(34, 211, 238, 180))
        painter.drawEllipse(QRectF(dx - 3, dy - 3, 6, 6))

        painter.end()


class MainWindow(QMainWindow):
    def __init__(self, registry):
        super().__init__()
        self.registry = registry
        self.setWindowTitle("R.A.F.I. — Personal AI Assistant")
        self.setMinimumSize(1000, 700)
        self.resize(1280, 800)
        self.setStyleSheet(f"background-color: {BG_DARK}; color: {TEXT_PRIMARY};")

        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(15, 15, 15, 15)
        root.setSpacing(12)

        # ── Title bar ───────────────────────────────────────────────────
        title_bar = QHBoxLayout()
        title_label = QLabel("R . A . F . I .")
        title_label.setStyleSheet(
            f"color: {ACCENT_CYAN}; font-size: 16px; font-weight: bold; "
            f"letter-spacing: 6px; padding: 4px 0;"
        )
        title_bar.addWidget(title_label)
        title_bar.addStretch()

        self.voice_badge = QLabel("IDLE")
        self._set_badge_idle()
        title_bar.addWidget(self.voice_badge)

        self.camera_badge = QLabel("CAM OFF")
        self.camera_badge.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 11px; padding: 4px 10px; "
            f"border: 1px solid {TEXT_DIM}; letter-spacing: 2px;"
        )
        title_bar.addWidget(self.camera_badge)
        root.addLayout(title_bar)

        # ── Middle: three-panel layout ──────────────────────────────────
        panels = QHBoxLayout()
        panels.setSpacing(12)
        root.addLayout(panels, stretch=1)

        # Left panel — tool activity / status
        left_panel = QWidget()
        left_panel.setStyleSheet(PANEL_STYLE)
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(10, 10, 10, 10)

        left_title = QLabel("SYSTEM ACTIVITY")
        left_title.setStyleSheet(
            f"color: {ACCENT_CYAN}; font-size: 11px; font-weight: bold; "
            f"letter-spacing: 3px; border: none; padding-bottom: 6px;"
        )
        left_layout.addWidget(left_title)

        self.activity_log = QTextEdit()
        self.activity_log.setReadOnly(True)
        self.activity_log.setStyleSheet(
            f"background-color: {CONSOLE_BG}; color: #a0a0ff; "
            f"font-family: 'Consolas', 'Monaco', monospace; font-size: 11px; "
            f"border: none; padding: 6px;"
        )
        left_layout.addWidget(self.activity_log)
        panels.addWidget(left_panel, stretch=2)

        # Center panel — visualizer + console
        center_panel = QWidget()
        center_panel.setStyleSheet(PANEL_STYLE)
        center_layout = QVBoxLayout(center_panel)
        center_layout.setContentsMargins(10, 10, 10, 10)

        self.visualizer = RafiVisualizer()
        center_layout.addWidget(self.visualizer, stretch=3)

        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet(
            f"background-color: {CONSOLE_BG}; color: {TEXT_PRIMARY}; "
            f"font-family: 'Consolas', 'Monaco', monospace; font-size: 12px; "
            f"border: 1px solid #1a2040; padding: 8px;"
        )
        center_layout.addWidget(self.console, stretch=2)

        # Text input
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("INITIALIZE COMMAND...")
        self.input_field.setStyleSheet(
            f"background-color: {BG_DARK}; color: {TEXT_PRIMARY}; "
            f"border: 1px solid {PANEL_BORDER}; padding: 8px; "
            f"font-family: 'Consolas', monospace; font-size: 12px; "
            f"selection-background-color: {ACCENT_CYAN};"
        )
        self.input_field.returnPressed.connect(self._on_input_submit)
        center_layout.addWidget(self.input_field)

        panels.addWidget(center_panel, stretch=5)

        # Right panel — video / info
        right_panel = QWidget()
        right_panel.setStyleSheet(PANEL_STYLE)
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(10, 10, 10, 10)

        right_title = QLabel("VIDEO FEED")
        right_title.setStyleSheet(
            f"color: {ACCENT_CYAN}; font-size: 11px; font-weight: bold; "
            f"letter-spacing: 3px; border: none; padding-bottom: 6px;"
        )
        right_layout.addWidget(right_title)

        self.video_label = QLabel("[ NO SIGNAL ]")
        self.video_label.setAlignment(Qt.AlignCenter)
        self.video_label.setStyleSheet(
            f"background-color: #050510; color: {TEXT_DIM}; "
            f"font-size: 14px; letter-spacing: 4px; border: none;"
        )
        self.video_label.setMinimumHeight(180)
        right_layout.addWidget(self.video_label, stretch=1)

        right_layout.addStretch()
        panels.addWidget(right_panel, stretch=3)

        # ── Bottom toolbar ──────────────────────────────────────────────
        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)
        root.addLayout(toolbar)

        self.mic_toggle = QPushButton("MIC")
        self.mic_toggle.setStyleSheet(BUTTON_STYLE)
        self.mic_toggle.setCheckable(True)
        self.mic_toggle.clicked.connect(self.on_mic_toggle)
        toolbar.addWidget(self.mic_toggle)

        self.camera_toggle = QPushButton("CAMERA")
        self.camera_toggle.setStyleSheet(BUTTON_STYLE)
        self.camera_toggle.setCheckable(True)
        self.camera_toggle.clicked.connect(self.on_camera_toggle)
        toolbar.addWidget(self.camera_toggle)

        self.screen_toggle = QPushButton("SCREEN")
        self.screen_toggle.setStyleSheet(BUTTON_STYLE)
        self.screen_toggle.setCheckable(True)
        self.screen_toggle.clicked.connect(self.on_screen_toggle)
        toolbar.addWidget(self.screen_toggle)

        toolbar.addStretch()

        # Start background listener for registry events
        asyncio.create_task(self.listen_to_registry())

    # ── badge helpers ───────────────────────────────────────────────────
    def _set_badge_idle(self):
        self.voice_badge.setText("IDLE")
        self.voice_badge.setStyleSheet(
            f"color: {TEXT_DIM}; font-size: 11px; padding: 4px 10px; "
            f"border: 1px solid {TEXT_DIM}; letter-spacing: 2px;"
        )

    def _set_badge_listening(self):
        self.voice_badge.setText("LISTENING")
        self.voice_badge.setStyleSheet(
            "color: #ff4444; font-size: 11px; padding: 4px 10px; "
            "border: 1px solid #ff4444; letter-spacing: 2px;"
        )

    # ── registry listener ───────────────────────────────────────────────
    async def listen_to_registry(self):
        logger.info("UI background listener started")
        while True:
            try:
                item = await self.registry.transcript_queue.get()
                text = item.get("text", "")
                role = item.get("role", "user")
                prefix = f'<span style="color:{ACCENT_BRIGHT};">&gt; USER:</span>'
                if role == "assistant":
                    prefix = f'<span style="color:{ACCENT_CYAN};">&gt; RAFI:</span>'
                self.console.append(f"{prefix} {text}")
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in UI listener: %s", e)
                await asyncio.sleep(1)

    def _log_activity(self, text: str):
        self.activity_log.append(
            f'<span style="color:#606090;">[{self._timestamp()}]</span> {text}'
        )

    @staticmethod
    def _timestamp():
        from datetime import datetime
        return datetime.now().strftime("%H:%M:%S")

    def append_to_console(self, text):
        self.console.append(text)

    @asyncSlot()
    async def _on_input_submit(self):
        text = self.input_field.text().strip()
        if not text:
            return

        self.console.append(
            f'<span style="color:{ACCENT_BRIGHT};">&gt; USER:</span> {text}'
        )
        self.input_field.clear()
        self._log_activity(f'Command: <span style="color:#a0a0ff;">{text}</span>')

        # Process through LLM via ConversationManager
        if self.registry.conversation:
            await self.registry.conversation.process_text_input(text)
        else:
            self.console.append(
                f'<span style="color:#ff4444;">ConversationManager not available</span>'
            )

    # ── button handlers ─────────────────────────────────────────────────
    @asyncSlot()
    async def on_mic_toggle(self):
        active = self.mic_toggle.isChecked()
        if active:
            self._set_badge_listening()
            self.visualizer.set_active(True)
            self._log_activity("Microphone <b>ON</b>")
            if self.registry.conversation:
                await self.registry.conversation.start_listening()
        else:
            self._set_badge_idle()
            self.visualizer.set_active(False)
            self._log_activity("Microphone <b>OFF</b>")
            if self.registry.conversation:
                await self.registry.conversation.stop_listening()

    @asyncSlot()
    async def on_camera_toggle(self):
        active = self.camera_toggle.isChecked()
        if active:
            self.camera_badge.setText("CAM ON")
            self.camera_badge.setStyleSheet(
                "color: #00dd00; font-size: 11px; padding: 4px 10px; "
                "border: 1px solid #00dd00; letter-spacing: 2px;"
            )
            self.video_label.setText("[ STREAMING ]")
            self._log_activity("Camera <b>ON</b>")
        else:
            self.camera_badge.setText("CAM OFF")
            self.camera_badge.setStyleSheet(
                f"color: {TEXT_DIM}; font-size: 11px; padding: 4px 10px; "
                f"border: 1px solid {TEXT_DIM}; letter-spacing: 2px;"
            )
            self.video_label.setText("[ NO SIGNAL ]")
            self._log_activity("Camera <b>OFF</b>")
        if self.registry.vision:
            await self.registry.vision.toggle_camera(active)

    @asyncSlot()
    async def on_screen_toggle(self):
        active = self.screen_toggle.isChecked()
        if active:
            self.camera_badge.setText("SCREEN")
            self.camera_badge.setStyleSheet(
                "color: #4488ff; font-size: 11px; padding: 4px 10px; "
                "border: 1px solid #4488ff; letter-spacing: 2px;"
            )
            self.video_label.setText("[ SCREEN SHARE ]")
            self._log_activity("Screen share <b>ON</b>")
        else:
            self.camera_badge.setText("CAM OFF")
            self.camera_badge.setStyleSheet(
                f"color: {TEXT_DIM}; font-size: 11px; padding: 4px 10px; "
                f"border: 1px solid {TEXT_DIM}; letter-spacing: 2px;"
            )
            self.video_label.setText("[ NO SIGNAL ]")
            self._log_activity("Screen share <b>OFF</b>")
        if self.registry.vision:
            await self.registry.vision.toggle_screen(active)


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
