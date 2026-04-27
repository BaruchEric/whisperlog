Extract action items from the transcript below. Format as a markdown checklist:

`- [ ] @owner: action (due: date if mentioned)`

Rules:
- Use the speaker's name if known; otherwise `@unassigned`.
- Only include items that are clearly actionable. Skip vague aspirations.
- If the transcript mentions a deadline relative to "today" or "next week",
  preserve the relative phrasing — don't invent a calendar date.
- If no action items exist, output exactly: `(none found)`

---

{{transcript}}
