# Prompt Plan for Rafi → ADA Parity

## Blueprint Overview
1. **Baseline audit** – Document the existing services (`TelegramBot`, `ElevenLabsAgent`, `DeepgramSTT`, calendar/email/task/memory services) in `src/main.py` and identify the hooking points for a GUI + toolset overlay. 2. **Orchestration layer** – Introduce a centralized service registry that exposes status hooks, scheduled callbacks, and tool invokers for the upcoming UI/vision pipeline. 3. **Multimodal front-end** – Build a PySide6-based UI that renders a voice status indicator, transcript console, and camera/screen-output mode controls, while streaming events from the backend. 4. **Audio/vision pipeline** – Wrap existing voice services (Deepgram + ElevenLabs) into a conversation manager that can trigger microphone/listener states, stream transcripts, and expose vision capture hooks. 5. **Extended tooling** – Provide a tool registry (search, filesystem, code execution, and data services) that can be invoked from both the UI and chat interfaces, ensuring every new capability wires back to the service registry.

## Iterative Chunking

### Phase 1: Establish the integration foundation
- Chunk 1.a: Create a `ServiceRegistry` data structure that holds strong references to the key services already instantiated in `lifespan` and exposes status queries + async helpers. This registry will later be consumed by the GUI and scheduler callbacks.
- Chunk 1.b: Replace direct `app.state` assignments in `lifespan` with registry wiring and add helper APIs that allow new UI components to subscribe to updates (e.g., `register_listener`).
- Chunk 1.c: Add light-weight event channels (async queues/subjects) to broadcast voice/transcript updates, task/note alerts, and tool execution results.

### Phase 2: Build the PySide6 experience
- Chunk 2.a: Vendor a new `ui` package with a PySide6 `MainWindow` showing status tiles for voice, camera, and tasks, plus a log console and action buttons. Start with a skeleton window and incremental widgets that push events to/from the registry.
- Chunk 2.b: Implement voice status badges that listen to the event channels established earlier; show “listening/speaking/idle” states and append transcripts to the console as they arrive.
- Chunk 2.c: Add camera/screen toggles and wire them to placeholder methods in the registry so that the UI can request a live input feed (video capture logic to follow). Provide UI-driven commands (e.g., “Open Tasks Panel”) that route through the tool registry.

### Phase 3: Add conversation & vision tooling
- Chunk 3.a: Introduce a `ConversationManager` that binds `DeepgramSTT` (input) with `ElevenLabsAgent` (output), exposing start/stop methods and streaming transcript callbacks via the event channel.
- Chunk 3.b: Integrate a simple OpenCV-based capture dispatcher that can switch between webcam/screen streams and expose frames (or metadata) to the registry; the UI toggles from Phase 2 drive it.
- Chunk 3.c: Allow the conversation manager to ingest captured frames and emit contextual summaries (placeholder) so the UI console can show “Visual Input: ...”. This lays groundwork for LLM vision later.

### Phase 4: Tool registry + wiring
- Chunk 4.a: Define a `ToolRegistry` that lists callable actions (e.g., create task, list notes, search emails, run python snippet) with metadata and async adapters to existing services.
- Chunk 4.b: Surface tool invocation buttons in the PySide6 UI and allow the Telegram bot (and future scheduler) to reuse the same registry so actions behave identically.
- Chunk 4.c: Build a final wiring step that ties the registry, conversation manager, and UI through the event channels, ensuring every prompt/action flows through a single orchestrated path (no orphaned helpers). The final prompt should describe wiring: UI -> service registry -> tools/conversation manager -> service execution -> UI feedback.

## Prompt Series for an LLM Agent

### Prompt 1: establish the service registry scaffolding
```text
Context: The FastAPI lifespan in src/main.py currently instantiates Supabase, chat providers, calendar, email, task, note, weather, memory, Deepgram, Twilio, and ElevenLabs services, then stores them on app.state. Create a new src/orchestration/service_registry.py module that defines ServiceRegistry (dataclass or class) which takes those services, registers them, and exposes async listeners for voice, tools, and UI events. Modify lifespan to instantiate ServiceRegistry, register services, and expose helper methods like register_listener(name, coroutine). Include detailed docstrings explaining how future UI/LLM workflows consume it.
```

### Prompt 2: widen lifespan wiring + event channels
```text
Context: After Prompt 1 we have ServiceRegistry hooking existing services. Update src/main.py to replace raw app.state assignments with a ServiceRegistry instance and add async queues (e.g., asyncio.Queue) for transcript, task/event, and tool outputs. Expose helper methods on ServiceRegistry for broadcasting and awaiting events. Ensure the registry can be imported by UI/voice modules without circular imports.
```

### Prompt 3: add UI scaffolding
```text
Context: The UI will live in src/ui/desktop.py using PySide6 and must consume ServiceRegistry. Create a PySide6 MainWindow with voice status indicator, transcript console, task quick list, and buttons for camera/screen toggles. Use async bridges (asyncio event loop integration or qasync) to pull from ServiceRegistry event queues and append text to the console. Include initial placeholder callbacks that call registry methods when buttons are clicked.
```

### Prompt 4: voice event integration
```text
Context: Build src/voice/conversation_manager.py to wrap DeepgramSTT + ElevenLabsAgent, exposing start_listening, stop_listening, and speak(text) methods. The manager should push events to ServiceRegistry queues (default voice/transcript queue) whenever transcripts or socket updates arrive. Update ServiceRegistry to expose start/stop hooks for this manager and ensure the UI status indicator reflects the manager’s state.
```

### Prompt 5: vision input toggle wiring
```text
Context: Create src/vision/capture.py that can select between webcam and screen capture using OpenCV (cv2.VideoCapture and mss or similar). The capture dispatcher should send frame metadata / descriptors to ServiceRegistry’s visual queue and allow toggling modes via methods the GUI uses. Update the UI buttons from Prompt 3 to call these toggles and display simple status (e.g., “Streaming webcam”).
```

### Prompt 6: tool registry + actions
```text
Context: Build src/tools/tool_registry.py listing tool definitions (create task, list notes, search emails, run python snippet). Each tool should call into existing services (TaskService, NoteService, EmailService, WeatherService). Wire ToolRegistry into ServiceRegistry so UI buttons and future chat prompts can invoke tools via a single entry point and emit results on the tool output queue.
```

### Prompt 7: end-to-end wiring
```text
Context: With UI, ServiceRegistry, ConversationManager, Vision capture, and ToolRegistry in place, add integration code (either in src/main.py or src/ui/desktop.py) that subscribes to the event queues and routes user actions (buttons, transcript triggers) through ToolRegistry. Ensure the final wiring step reuses the same objects (no disconnected helpers) and adds log statements showing the full path (UI -> registry -> services -> UI result). Explain how this will support future LLM prompts/actions.
```

Each prompt builds on the previous modules, and the final prompt ensures everything is wired into a single orchestrated path before moving on to more advanced LLM-specific behavior.
