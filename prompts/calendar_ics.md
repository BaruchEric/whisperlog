Read the meeting transcript below and identify any future events that were
mentioned (next meeting, deadline, follow-up call, demo date, etc.).

Output a single VCALENDAR with one VEVENT per mentioned event. Use:
- DTSTART/DTEND in `YYYYMMDDTHHMMSS` form (omit DTEND if duration is unclear)
- SUMMARY: short title
- DESCRIPTION: one-line context, escaping newlines as `\n`

If no future events are mentioned, output exactly: `(no events)`

Output only the VCALENDAR block — no commentary, no markdown fences.

---

{{transcript}}
