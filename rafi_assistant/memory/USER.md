# USER.md — About My User

## Profile

- **Name**: (set via config.client.name)
- **Timezone**: (set via config.settings.timezone)

## Preference Keys

### response.style

- **value**: concise_direct
- **allowed_values**: concise_direct, balanced, detailed

### response.detail_mode

- **value**: on_request
- **allowed_values**: always_short, on_request, always_detailed

### notifications.style

- **value**: actionable_only
- **allowed_values**: actionable_only, digest_only, mixed

### notifications.digest_contents

- **value**: calendar,email,tasks,weather
- **notes**: default morning briefing bundle

### reminders.calendar_lead_minutes_default

- **value**: use_config
- **notes**: falls back to settings.reminder_lead_minutes

### reminders.task_lead_minutes_default

- **value**: adaptive
- **notes**: choose a practical lead based on due date proximity

### channel.primary

- **value**: telegram
- **allowed_values**: telegram, whatsapp

### channel.urgent_fallback

- **value**: twilio_voice
- **allowed_values**: none, telegram, whatsapp, twilio_voice

### quiet_hours.exceptions

- **value**: urgent_time_sensitive_only
- **allowed_values**: none, urgent_time_sensitive_only, whitelisted_topics

### quiet_hours.exception_topics

- **value**: []
- **notes**: populate only when user explicitly opts in

## Notes

- This file evolves as I learn more about my user's preferences
- The heartbeat process updates this when new preferences are detected
