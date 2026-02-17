# Context for: Add due dates

This touches all modules.

## Files to change
1. **models.py**: Add `due_date: str | None = None` field to Task dataclass
2. **cli.py**: Add `--due` argument to `add` and `edit` subparsers. Add `--due` flag to `list` (sort mode). Handle "none" to clear.
3. **store.py**: No changes needed (generic update handles new fields)
4. **display.py**: Show due date in `format_task()`. Add "[OVERDUE]" marker for past-due todo tasks.

## Date handling
- Dates are ISO format strings: "2026-03-15"
- Use `datetime.date.fromisoformat(date_str)` to parse
- Compare with `date.today()` for overdue check
- Store as string in JSON (no special serialization needed)

## Key patterns
- `format_task()` should append due date after title
- For `list --due`, sort tasks by due_date (None sorts last)
- Only "todo" tasks can be overdue (done tasks are never overdue)

## Run tests
`python -m pytest tests/ -v`
