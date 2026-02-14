"""Hand gesture to action mapping for the mobile companion UI.

Maps MediaPipe gesture recognizer output to Rafi actions.
Gestures are detected client-side (browser WASM) and sent
as lightweight JSON events over WebSocket.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

logger = logging.getLogger(__name__)

# MediaPipe built-in gesture names → Rafi actions
GESTURE_MAP: dict[str, dict[str, Any]] = {
    "Thumb_Up": {
        "action": "confirm",
        "label": "Confirmed",
        "text_command": "Yes, confirmed.",
        "min_confidence": 0.70,
    },
    "Thumb_Down": {
        "action": "negative",
        "label": "No",
        "text_command": "No, that's not right.",
        "min_confidence": 0.70,
    },
    "Open_Palm": {
        "action": "stop",
        "label": "Stop",
        "text_command": None,  # direct action, not conversational
        "min_confidence": 0.70,
    },
    "Victory": {
        "action": "skip",
        "label": "Next",
        "text_command": "Skip to the next item.",
        "min_confidence": 0.75,
    },
    "Pointing_Up": {
        "action": "repeat",
        "label": "Repeat",
        "text_command": "Please repeat that.",
        "min_confidence": 0.70,
    },
    "Closed_Fist": {
        "action": "dismiss",
        "label": "Dismissed",
        "text_command": None,
        "min_confidence": 0.80,
    },
    "ILoveYou": {
        "action": "acknowledge",
        "label": "Thanks!",
        "text_command": "Thank you!",
        "min_confidence": 0.70,
    },
}


class GestureActionMapper:
    """Maps MediaPipe gesture names to Rafi actions."""

    @staticmethod
    def map_gesture(
        gesture: str, confidence: float
    ) -> Optional[dict[str, Any]]:
        """Return the action mapping for a gesture, or None if below threshold.

        Args:
            gesture: MediaPipe gesture category name (e.g. ``"Thumb_Up"``).
            confidence: Detection confidence score (0–1).

        Returns:
            Dict with ``action``, ``label``, ``text_command`` keys, or None.
        """
        mapping = GESTURE_MAP.get(gesture)
        if mapping is None:
            return None
        if confidence < mapping["min_confidence"]:
            return None
        logger.info(
            "Gesture mapped: %s (%.0f%%) → %s",
            gesture,
            confidence * 100,
            mapping["action"],
        )
        return mapping
