Add `tag` and `untag` commands, and add tag filtering to the `list` command.

Requirements:
- `taskboard tag <id> <tag>` — adds a tag to a task (no duplicates)
- `taskboard untag <id> <tag>` — removes a tag from a task
- `taskboard list --tag <tag>` — filters task list to only show tasks with that tag
- Tags are case-insensitive for matching but stored as-is
- Tagging a nonexistent task should print an error and exit with code 1
- Untagging a tag that doesn't exist on the task should be a no-op (not an error)
