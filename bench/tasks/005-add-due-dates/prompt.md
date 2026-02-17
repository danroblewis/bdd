Add due date support to the taskboard.

Requirements:
- Add a `due_date` field to the Task model (optional, ISO format date string like "2026-03-15", or null)
- `taskboard add "Task title" --due 2026-03-15` — sets a due date when adding
- `taskboard edit <id> --due 2026-03-15` — sets/changes a due date
- `taskboard edit <id> --due none` — removes a due date
- `taskboard list --due` — sorts tasks by due date (earliest first, tasks without due dates at the end)
- In the display output, show the due date after the title
- Overdue tasks (due date is in the past and status is "todo") should be displayed with "[OVERDUE]" marker
- Handle invalid date formats gracefully with a clear error message
