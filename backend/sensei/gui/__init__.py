"""
Sensei Qt GUI Application — standalone desktop chat interface using PySide6.

Run with: python -m sensei.gui

Features:
- Full chat interface with streaming
- Model provider selection
- Token compression stats display
- Conversation history
- Dark theme

Requires: pip install sensei[gui]
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time

from sensei.config import settings

logger = logging.getLogger(__name__)


def _import_qt():
    """Import PySide6 with helpful error message."""
    try:
        from PySide6.QtCore import Qt, QThread, Signal
        from PySide6.QtGui import QFont, QIcon, QColor, QPalette
        from PySide6.QtWidgets import (
            QApplication,
            QMainWindow,
            QWidget,
            QVBoxLayout,
            QHBoxLayout,
            QTextEdit,
            QLineEdit,
            QPushButton,
            QLabel,
            QComboBox,
            QStatusBar,
            QScrollBar,
        )
        return (
            Qt, QThread, Signal,
            QFont, QIcon, QColor, QPalette,
            QApplication, QMainWindow, QWidget,
            QVBoxLayout, QHBoxLayout,
            QTextEdit, QLineEdit, QPushButton,
            QLabel, QComboBox, QStatusBar, QScrollBar,
        )
    except ImportError:
        print(
            "PySide6 is not installed.\n"
            "Install with: pip install sensei[gui]\n"
            "Or: pip install PySide6",
            file=sys.stderr,
        )
        sys.exit(1)


class ChatWorker:
    """Async chat worker that runs in a separate thread."""

    def __init__(self):
        from sensei.models.registry import get_provider
        from sensei.compression.router import ContentRouter
        from sensei.compression.ccr import CCRStore
        from sensei.models.base import ChatMessage, Role

        self._get_provider = get_provider
        self._ContentRouter = ContentRouter
        self._CCRStore = CCRStore
        self._ChatMessage = ChatMessage
        self._Role = Role
        self._content_router = ContentRouter(ccr_store=CCRStore())
        self._messages: list[ChatMessage] = []
        self._tokens_saved = 0

    async def send_message(self, content: str) -> tuple[str, int]:
        """Send a message and return (response, tokens_saved)."""
        self._messages.append(self._ChatMessage(role=self._Role.user, content=content))

        # Compress
        msg_dicts = [{"role": m.role.value, "content": m.content} for m in self._messages]
        if settings.compression_enabled:
            compressed, results = self._content_router.compress_messages(msg_dicts)
            self._tokens_saved += sum(r.tokens_saved for r in results)
            messages = [self._ChatMessage(role=self._Role(m["role"]), content=m["content"]) for m in compressed]
        else:
            messages = self._messages

        provider = await self._get_provider()
        completion = await provider.chat(messages=messages)
        self._messages.append(self._ChatMessage(role=self._Role.assistant, content=completion.content))

        return completion.content, self._tokens_saved

    def clear(self):
        self._messages.clear()
        self._tokens_saved = 0


def run_gui():
    """Launch the Qt GUI application."""
    (
        Qt, QThread, Signal,
        QFont, QIcon, QColor, QPalette,
        QApplication, QMainWindow, QWidget,
        QVBoxLayout, QHBoxLayout,
        QTextEdit, QLineEdit, QPushButton,
        QLabel, QComboBox, QStatusBar, QScrollBar,
    ) = _import_qt()

    class ChatThread(QThread):
        response_ready = Signal(str, int)
        error_occurred = Signal(str)

        def __init__(self, worker: ChatWorker, message: str):
            super().__init__()
            self.worker = worker
            self.message = message

        def run(self):
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                response, tokens = loop.run_until_complete(
                    self.worker.send_message(self.message)
                )
                self.response_ready.emit(response, tokens)
            except Exception as e:
                self.error_occurred.emit(str(e))

    class SenseiWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.worker = ChatWorker()
            self.chat_thread: ChatThread | None = None

            self.setWindowTitle("Sensei — Self-hosted AI")
            self.setMinimumSize(800, 600)
            self.resize(900, 700)

            # Dark theme
            palette = QPalette()
            palette.setColor(QPalette.Window, QColor("#0a0a0a"))
            palette.setColor(QPalette.WindowText, QColor("#e0e0e0"))
            palette.setColor(QPalette.Base, QColor("#1a1a1a"))
            palette.setColor(QPalette.AlternateBase, QColor("#1a1a1a"))
            palette.setColor(QPalette.Text, QColor("#e0e0e0"))
            palette.setColor(QPalette.Button, QColor("#2a2a2a"))
            palette.setColor(QPalette.ButtonText, QColor("#e0e0e0"))
            palette.setColor(QPalette.Highlight, QColor("#16a34a"))
            palette.setColor(QPalette.HighlightedText, QColor("#ffffff"))
            self.setPalette(palette)

            # Central widget
            central = QWidget()
            self.setCentralWidget(central)
            layout = QVBoxLayout(central)
            layout.setContentsMargins(12, 12, 12, 12)
            layout.setSpacing(8)

            # Header
            header = QHBoxLayout()
            title = QLabel("Sensei")
            title.setFont(QFont("Inter", 18, QFont.Bold))
            title.setStyleSheet("color: #22c55e;")
            header.addWidget(title)

            subtitle = QLabel("GLM-5.2 · Self-hosted AI")
            subtitle.setStyleSheet("color: #666;")
            header.addWidget(subtitle)
            header.addStretch()

            self.model_label = QLabel("No model configured")
            self.model_label.setStyleSheet("color: #888; font-size: 11px;")
            header.addWidget(self.model_label)
            layout.addLayout(header)

            # Chat display
            self.chat_display = QTextEdit()
            self.chat_display.setReadOnly(True)
            self.chat_display.setStyleSheet("""
                QTextEdit {
                    background-color: #111;
                    color: #e0e0e0;
                    border: 1px solid #333;
                    border-radius: 8px;
                    padding: 8px;
                    font-size: 14px;
                }
            """)
            layout.addWidget(self.chat_display)

            # Input area
            input_layout = QHBoxLayout()
            self.input_field = QLineEdit()
            self.input_field.setPlaceholderText("Send a message...")
            self.input_field.setStyleSheet("""
                QLineEdit {
                    background-color: #1a1a1a;
                    color: #e0e0e0;
                    border: 1px solid #333;
                    border-radius: 8px;
                    padding: 10px;
                    font-size: 14px;
                }
                QLineEdit:focus {
                    border-color: #16a34a;
                }
            """)
            self.input_field.returnPressed.connect(self.send_message)
            input_layout.addWidget(self.input_field)

            self.send_btn = QPushButton("Send")
            self.send_btn.setStyleSheet("""
                QPushButton {
                    background-color: #16a34a;
                    color: white;
                    border: none;
                    border-radius: 8px;
                    padding: 10px 20px;
                    font-weight: bold;
                    font-size: 14px;
                }
                QPushButton:hover {
                    background-color: #15803d;
                }
                QPushButton:disabled {
                    background-color: #333;
                    color: #666;
                }
            """)
            self.send_btn.clicked.connect(self.send_message)
            input_layout.addWidget(self.send_btn)
            layout.addLayout(input_layout)

            # Status bar
            self.status_bar = QStatusBar()
            self.status_bar.setStyleSheet("color: #666; font-size: 11px;")
            self.setStatusBar(self.status_bar)
            self.status_bar.showMessage("Ready · Compression: enabled")

            # Welcome message
            self.chat_display.setHtml(
                '<div style="color: #888; text-align: center; padding: 40px;">'
                '<h2 style="color: #22c55e;">Welcome to Sensei</h2>'
                '<p>Self-hosted AI workspace with token compression, powered by GLM-5.2</p>'
                '<p style="color: #555; font-size: 12px;">Start typing to begin a conversation.</p>'
                '</div>'
            )

            # Check model availability
            self._check_models()

        def _check_models(self):
            """Check available models on startup."""
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                from sensei.models.registry import list_available_models
                models = loop.run_until_complete(list_available_models())
                if models:
                    available = [m for m in models if m.status == "available"]
                    if available:
                        self.model_label.setText(f"Model: {available[0].name}")
                        self.model_label.setStyleSheet("color: #22c55e; font-size: 11px;")
                    else:
                        self.model_label.setText("No model available — check config")
                        self.model_label.setStyleSheet("color: #f59e0b; font-size: 11px;")
            except Exception:
                pass

        def send_message(self):
            text = self.input_field.text().strip()
            if not text or self.chat_thread is not None:
                return

            # Display user message
            self._append_message("You", text, "#3b82f6")
            self.input_field.clear()
            self.send_btn.setEnabled(False)
            self.status_bar.showMessage("Generating response...")

            # Start chat thread
            self.chat_thread = ChatThread(self.worker, text)
            self.chat_thread.response_ready.connect(self.on_response)
            self.chat_thread.error_occurred.connect(self.on_error)
            self.chat_thread.start()

        def on_response(self, response: str, tokens_saved: int):
            self._append_message("Sensei", response, "#22c55e")
            self.send_btn.setEnabled(True)
            self.status_bar.showMessage(
                f"Ready · Tokens saved: {tokens_saved:,} · Compression: enabled"
            )
            self.chat_thread = None

        def on_error(self, error: str):
            self._append_message("Error", error, "#ef4444")
            self.send_btn.setEnabled(True)
            self.status_bar.showMessage(f"Error: {error[:50]}")
            self.chat_thread = None

        def _append_message(self, sender: str, text: str, color: str):
            cursor = self.chat_display.textCursor()
            cursor.movePosition(cursor.MoveOperation.End)
            cursor.insertHtml(
                f'<div style="margin: 8px 0;">'
                f'<b style="color: {color};">{sender}:</b>'
                f'<span style="color: #e0e0e0; white-space: pre-wrap;"> {text}</span>'
                f'</div>'
            )
            self.chat_display.verticalScrollBar().setValue(
                self.chat_display.verticalScrollBar().maximum()
            )

    app = QApplication(sys.argv)
    app.setApplicationName("Sensei")

    # Set app icon if available
    try:
        icon_path = __file__.replace("__init__.py", "icon.svg")
        import os
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
    except Exception:
        pass

    window = SenseiWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    run_gui()
