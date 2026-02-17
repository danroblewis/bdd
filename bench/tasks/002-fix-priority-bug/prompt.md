The `done` command crashes with an unhandled exception when given a task ID that doesn't exist.

For example, `taskboard done 999` (where task 999 doesn't exist) produces an `AttributeError` instead of a helpful error message.

Fix this bug so that:
- `taskboard done <invalid_id>` prints "Task <id> not found." to stderr and exits with code 1
- The fix should not break any existing functionality
