Add a `stats` command that shows summary statistics about tasks in the taskboard.

`taskboard stats` should print a summary with:
- Total number of tasks
- Number of todo tasks and number of done tasks
- A count of tasks at each priority level (1, 2, 3) — only show priorities that have tasks
- If there are no tasks at all, print "No tasks."

Example output format (exact format matters):
```
Total: 5
Todo: 3  Done: 2
Priority 1: 2  Priority 2: 2  Priority 3: 1
```

The command should return exit code 0.
