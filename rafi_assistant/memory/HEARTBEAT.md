# HEARTBEAT.md — Proactive Check Checklist

## Priority Checks (every 30 minutes)

### P1 — Time-Critical (notify when true)
- Calendar events starting soon that need prep/travel buffer
- Tasks with near deadlines that can still be acted on now
- Urgent inbound messages that imply immediate user action

### P2 — Important (notify only if actionable)
- New emails or task updates that change today's plan
- Schedule conflicts, overlaps, or newly blocked focus windows

### P3 — Context (digest-first)
- Weather or background changes that affect upcoming commitments
- Non-urgent updates best grouped into the next summary

## When To Notify
- Notify only when there is a clear next action for the user
- If everything is fine, respond with HEARTBEAT_OK
- Deduplicate equivalent alerts for 24 hours unless severity increases
- During quiet hours, suppress non-urgent alerts
- Prefer a single bundled alert over multiple pings in one cycle

## Escalation Criteria
- Escalate channel/urgency only when action is time-sensitive (generally <=60 minutes) or user-impact is high and unresolved.

## Anti-Spam Guardrails
- Avoid repeating unchanged facts; send updates only on meaningful state change
- Rate-limit proactive messages and merge related items into one concise notification
- If the user does not engage, reduce frequency rather than increase it

## Memory Maintenance (periodic)
- Review today's daily log for insights worth promoting to MEMORY.md
- Update USER.md if reliable new preferences detected
