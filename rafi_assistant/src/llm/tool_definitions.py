"""Tool/function schemas for LLM function calling.

Defines all tools available to the LLM during conversations, including
calendar, email, task, note, weather, settings, and memory tools.
All schemas follow the OpenAI tool format.
"""

from __future__ import annotations

from typing import Any

# =============================================================================
# Calendar Tools
# =============================================================================

READ_CALENDAR_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_calendar",
        "description": (
            "Read upcoming calendar events. Returns a list of events "
            "for the specified number of days ahead."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days ahead to look for events (default 7, max 30).",
                    "default": 7,
                },
            },
            "required": [],
        },
    },
}

CREATE_EVENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_event",
        "description": (
            "Create a new calendar event with a summary/title, start time, "
            "end time, and optional location."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "summary": {
                    "type": "string",
                    "description": "Title or summary of the event.",
                },
                "start": {
                    "type": "string",
                    "description": "Start time in ISO 8601 format (e.g., '2024-01-15T14:00:00-05:00').",
                },
                "end": {
                    "type": "string",
                    "description": "End time in ISO 8601 format (e.g., '2024-01-15T15:00:00-05:00').",
                },
                "location": {
                    "type": "string",
                    "description": "Location of the event (optional).",
                },
            },
            "required": ["summary", "start", "end"],
        },
    },
}

UPDATE_EVENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_event",
        "description": "Update an existing calendar event. Only provided fields are changed.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The Google Calendar event ID to update.",
                },
                "summary": {
                    "type": "string",
                    "description": "New title/summary for the event.",
                },
                "start": {
                    "type": "string",
                    "description": "New start time in ISO 8601 format.",
                },
                "end": {
                    "type": "string",
                    "description": "New end time in ISO 8601 format.",
                },
                "location": {
                    "type": "string",
                    "description": "New location for the event.",
                },
            },
            "required": ["event_id"],
        },
    },
}

DELETE_EVENT_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "delete_event",
        "description": "Delete/cancel a calendar event by its ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "event_id": {
                    "type": "string",
                    "description": "The Google Calendar event ID to delete.",
                },
            },
            "required": ["event_id"],
        },
    },
}

# =============================================================================
# Email Tools
# =============================================================================

READ_EMAILS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "read_emails",
        "description": "Read recent emails from the inbox. Can filter to unread only.",
        "parameters": {
            "type": "object",
            "properties": {
                "count": {
                    "type": "integer",
                    "description": "Number of emails to retrieve (default 20, max 50).",
                    "default": 20,
                },
                "unread_only": {
                    "type": "boolean",
                    "description": "If true, only return unread emails.",
                    "default": False,
                },
            },
            "required": [],
        },
    },
}

SEARCH_EMAILS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_emails",
        "description": (
            "Search emails using Gmail search syntax. Supports operators like "
            "from:, to:, subject:, after:, before:, has:attachment, etc."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Gmail search query string (e.g., 'from:john subject:meeting after:2024/01/01').",
                },
            },
            "required": ["query"],
        },
    },
}

SEND_EMAIL_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "send_email",
        "description": (
            "Send an email to a recipient. Always confirm with the user before sending."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "to": {
                    "type": "string",
                    "description": "Recipient email address.",
                },
                "subject": {
                    "type": "string",
                    "description": "Email subject line.",
                },
                "body": {
                    "type": "string",
                    "description": "Plain text email body.",
                },
            },
            "required": ["to", "subject", "body"],
        },
    },
}

# =============================================================================
# Task Tools
# =============================================================================

CREATE_TASK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_task",
        "description": "Create a new task with a title, optional description, and optional due date.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title of the task.",
                },
                "description": {
                    "type": "string",
                    "description": "Detailed description of the task (optional).",
                },
                "due_date": {
                    "type": "string",
                    "description": "Due date in ISO 8601 format (optional).",
                },
            },
            "required": ["title"],
        },
    },
}

LIST_TASKS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_tasks",
        "description": "List tasks, optionally filtered by status.",
        "parameters": {
            "type": "object",
            "properties": {
                "status": {
                    "type": "string",
                    "description": "Filter by status: 'pending', 'in_progress', or 'completed'. Omit for all tasks.",
                    "enum": ["pending", "in_progress", "completed"],
                },
            },
            "required": [],
        },
    },
}

UPDATE_TASK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_task",
        "description": "Update an existing task. Only provided fields are changed.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task UUID to update.",
                },
                "title": {
                    "type": "string",
                    "description": "New title for the task.",
                },
                "description": {
                    "type": "string",
                    "description": "New description for the task.",
                },
                "status": {
                    "type": "string",
                    "description": "New status for the task.",
                    "enum": ["pending", "in_progress", "completed"],
                },
                "due_date": {
                    "type": "string",
                    "description": "New due date in ISO 8601 format.",
                },
            },
            "required": ["task_id"],
        },
    },
}

DELETE_TASK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "delete_task",
        "description": "Delete a task by its ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task UUID to delete.",
                },
            },
            "required": ["task_id"],
        },
    },
}

COMPLETE_TASK_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "complete_task",
        "description": "Mark a task as completed.",
        "parameters": {
            "type": "object",
            "properties": {
                "task_id": {
                    "type": "string",
                    "description": "The task UUID to complete.",
                },
            },
            "required": ["task_id"],
        },
    },
}

# =============================================================================
# Note Tools
# =============================================================================

CREATE_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_note",
        "description": "Create a new note with a title and content.",
        "parameters": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Title of the note.",
                },
                "content": {
                    "type": "string",
                    "description": "Body content of the note.",
                },
            },
            "required": ["title", "content"],
        },
    },
}

LIST_NOTES_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "list_notes",
        "description": "List all notes, ordered by most recently created.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

GET_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_note",
        "description": "Get a specific note by its ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The note UUID to retrieve.",
                },
            },
            "required": ["note_id"],
        },
    },
}

UPDATE_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_note",
        "description": "Update an existing note. Only provided fields are changed.",
        "parameters": {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The note UUID to update.",
                },
                "title": {
                    "type": "string",
                    "description": "New title for the note.",
                },
                "content": {
                    "type": "string",
                    "description": "New content for the note.",
                },
            },
            "required": ["note_id"],
        },
    },
}

DELETE_NOTE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "delete_note",
        "description": "Delete a note by its ID.",
        "parameters": {
            "type": "object",
            "properties": {
                "note_id": {
                    "type": "string",
                    "description": "The note UUID to delete.",
                },
            },
            "required": ["note_id"],
        },
    },
}

# =============================================================================
# Weather Tools
# =============================================================================

GET_WEATHER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_weather",
        "description": (
            "Get current weather and forecast for a location. "
            "If no location is provided, uses the next calendar event's location."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "location": {
                    "type": "string",
                    "description": "City name or location (e.g., 'New York, NY'). Optional if a calendar event has a location.",
                },
            },
            "required": [],
        },
    },
}

# =============================================================================
# Settings Tools
# =============================================================================

UPDATE_SETTING_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "update_setting",
        "description": (
            "Update a user setting. Available settings: morning_briefing_time, "
            "quiet_hours_start, quiet_hours_end, reminder_lead_minutes, "
            "min_snooze_minutes."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Setting name to update.",
                    "enum": [
                        "morning_briefing_time",
                        "quiet_hours_start",
                        "quiet_hours_end",
                        "reminder_lead_minutes",
                        "min_snooze_minutes",
                    ],
                },
                "value": {
                    "type": "string",
                    "description": "New value for the setting. Times in HH:MM format, minutes as integer string.",
                },
            },
            "required": ["key", "value"],
        },
    },
}

GET_SETTINGS_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_settings",
        "description": "Get the current values of all user settings.",
        "parameters": {
            "type": "object",
            "properties": {},
            "required": [],
        },
    },
}

# =============================================================================
# Memory Tools
# =============================================================================

RECALL_MEMORY_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "recall_memory",
        "description": (
            "Search conversation history using semantic search. "
            "Useful for recalling past discussions, decisions, or information."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Natural language query describing what to recall (e.g., 'What did we discuss about the Johnson project?').",
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default 5).",
                    "default": 5,
                },
            },
            "required": ["query"],
        },
    },
}

# =============================================================================
# Aggregated Tool Lists
# =============================================================================

CALENDAR_TOOLS: list[dict[str, Any]] = [
    READ_CALENDAR_TOOL,
    CREATE_EVENT_TOOL,
    UPDATE_EVENT_TOOL,
    DELETE_EVENT_TOOL,
]

EMAIL_TOOLS: list[dict[str, Any]] = [
    READ_EMAILS_TOOL,
    SEARCH_EMAILS_TOOL,
    SEND_EMAIL_TOOL,
]

TASK_TOOLS: list[dict[str, Any]] = [
    CREATE_TASK_TOOL,
    LIST_TASKS_TOOL,
    UPDATE_TASK_TOOL,
    DELETE_TASK_TOOL,
    COMPLETE_TASK_TOOL,
]

NOTE_TOOLS: list[dict[str, Any]] = [
    CREATE_NOTE_TOOL,
    LIST_NOTES_TOOL,
    GET_NOTE_TOOL,
    UPDATE_NOTE_TOOL,
    DELETE_NOTE_TOOL,
]

WEATHER_TOOLS: list[dict[str, Any]] = [
    GET_WEATHER_TOOL,
]

SETTINGS_TOOLS: list[dict[str, Any]] = [
    UPDATE_SETTING_TOOL,
    GET_SETTINGS_TOOL,
]

MEMORY_TOOLS: list[dict[str, Any]] = [
    RECALL_MEMORY_TOOL,
]

ALL_TOOLS: list[dict[str, Any]] = (
    CALENDAR_TOOLS
    + EMAIL_TOOLS
    + TASK_TOOLS
    + NOTE_TOOLS
    + WEATHER_TOOLS
    + SETTINGS_TOOLS
    + MEMORY_TOOLS
)


def get_tool_names() -> list[str]:
    """Return the names of all defined tools."""
    return [tool["function"]["name"] for tool in ALL_TOOLS]
