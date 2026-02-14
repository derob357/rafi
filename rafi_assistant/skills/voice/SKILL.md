---
name: voice
description: Voice call stack readiness (Twilio + Deepgram + ElevenLabs).
tools: []
requires:
  env:
    - TWILIO_ACCOUNT_SID
    - TWILIO_AUTH_TOKEN
    - TWILIO_PHONE_NUMBER
    - DEEPGRAM_API_KEY
    - ELEVENLABS_API_KEY
    - ELEVENLABS_VOICE_ID
---

# Voice Skill

This skill gates voice-call integrations at startup so unavailable providers are surfaced early.

- Twilio: call routing and telephony transport.
- Deepgram: speech-to-text.
- ElevenLabs: conversational voice agent and TTS.
