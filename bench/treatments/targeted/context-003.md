# Context for: Add tag/untag commands

You'll modify multiple files to support tag management.

## Files to change
1. **cli.py**: Add `cmd_tag`, `cmd_untag` functions and subparsers. Add `--tag` flag to `list` subparser.
2. **store.py**: You may need helper methods, but `update(id, **fields)` already can update `tags`.

## Data model
Tasks already have a `tags: list[str]` field (see `src/taskboard/models.py`).
Tags are stored as strings in a list. The `add` command already supports `--tags` for initial tag creation.

## Key patterns
- Tags are case-insensitive for matching but stored as-is
- Avoid duplicate tags: check before adding
- `store.get(id)` returns the current task; modify tags and `store.update(id, tags=new_tags)`

## Run tests
`python -m pytest tests/ -v`
