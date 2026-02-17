Add an "in-progress" status to the task workflow.

Currently tasks can only be "todo" or "done". Add support for an intermediate "in-progress" state:

- Add a `start` command: `taskboard start <id>` marks a todo task as "in-progress"
  - If the task is already "in-progress", print "Task <id> is already in progress." and return 0
  - If the task is "done", print "Task <id> is already done." to stderr and return 1
  - If the task doesn't exist, print "Task <id> not found." to stderr and return 1
- The `done` command should work on both "todo" and "in-progress" tasks (mark either as "done")
- `taskboard list --status in-progress` should filter to in-progress tasks only
- In the display output, in-progress tasks should show a `[-]` icon (between `[ ]` for todo and `[x]` for done)
