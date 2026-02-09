# TODO

- [x] Blueprint service registry in `src/orchestration/service_registry.py` and replace direct `app.state` usage in `src/main.py` so every service can be subscribed to by UI, voice, and tool components.
- [x] Wire lifecycle event queues (transcripts, tasks/events, tool outputs) into the registry and expose broadcast/await helpers.
- [x] Implement the PySide6 desktop UI (`src/ui/desktop.py`) with a transcript console, voice status badges, and camera/screen toggle buttons that call into the registry.
- [x] Create `ConversationManager` to tie Deepgram STT + ElevenLabsAgent and publish transcripts/status into the registry’s voice queue.
- [x] Build the OpenCV-based vision/capture dispatcher (`src/vision/capture.py`) to switch between webcam and screen, reporting status back to the registry.
- [x] Develop `ToolRegistry` that exposes task/note/email/weather/code actions and integrates with the service registry for UI/Telegram reuse.
- [x] Final wiring: connect UI actions, event queues, conversation manager, vision capture, and tool invocations through ServiceRegistry so there are no orphaned pathways.
- [x] Implement `CadService` for 3D model generation using `build123d` and wire as a callable tool.
- [x] Implement `BrowserService` for autonomous web research using `playwright` and wire as a callable tool.
- [x] Integrate real-time VAD (Voice Activity Detection) for a smoother hands-free experience in `ConversationManager`.
- [x] Implement local screen control (mouse/keyboard) tool to complement the BrowserService for native app automation.
- [x] Create `run_local.py` to launch FastAPI backend and PySide6 UI simultaneously for local testing.
- [ ] Implement a `cli.py` command in `rafi_deploy` to generate local tunneling config automatically.

