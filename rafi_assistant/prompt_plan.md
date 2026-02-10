# Prompt Plan for Rafi → ADA Parity

## Current Status (Feb 9, 2026)
- **Phase 1-4:** COMPLETED. All core orchestration, UI, Voice (STT/TTS/Tools), and Tool Wiring are implemented.
- **Critical Blockers:** User must run the provided SQL migration in Supabase to create the updated `vector(1536)` tables.
- **Voice ID:** User needs a valid ElevenLabs Voice ID in `.env`.

## Blueprint Overview
1. **Baseline audit** – [DONE] Document the existing services...
2. **Orchestration layer** – [DONE] Introduce a centralized service registry...
3. **Multimodal front-end** – [DONE] Build a PySide6-based UI...
4. **Audio/vision pipeline** – [DONE] Wrap existing voice services...
5. **Extended tooling** – [IN PROGRESS] Provide a tool registry...

## Iterative Chunking

### Phase 1: Establish the integration foundation [COMPLETED]
- Chunk 1.a: Create a `ServiceRegistry`... [DONE]
- Chunk 1.b: Replace direct `app.state` assignments... [DONE]
- Chunk 1.c: Add light-weight event channels... [DONE]

### Phase 2: Build the PySide6 experience [COMPLETED]
- Chunk 2.a: Vendor a new `ui` package... [DONE]
- Chunk 2.b: Implement voice status badges... [DONE]
- Chunk 2.c: Add camera/screen toggles... [DONE]

### Phase 3: Add conversation & vision tooling [COMPLETED]
- Chunk 3.a: Introduce a `ConversationManager`... [DONE - Microphone -> Deepgram -> LLM -> Speech loop wired]
- Chunk 3.b: Integrate a simple OpenCV-based capture dispatcher... [DONE]
- Chunk 3.c: Allow the conversation manager to ingest captured frames... [STRETCH]

### Phase 4: Tool registry + wiring [COMPLETED]
- Chunk 4.a: Define a `ToolRegistry`... [DONE]
- Chunk 4.b: Surface tool invocation buttons... [DONE]
- Chunk 4.c: Build a final wiring step... [DONE - `ConversationManager` handles tool calls via `ToolRegistry`]

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
