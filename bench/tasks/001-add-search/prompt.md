Add a `search` command to the taskboard CLI that filters tasks by keyword.

- `taskboard search <keyword>` should show all tasks whose title contains the keyword (case-insensitive)
- If no tasks match, print "No matching tasks."
- The search should work with `--status` flag to filter by status too
