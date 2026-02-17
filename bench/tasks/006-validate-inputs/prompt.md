Add input validation to the taskboard to reject invalid data with clear error messages.

Currently the taskboard accepts any values without validation. Fix the following:

- **Priority range**: Priority must be 1, 2, or 3. If an invalid priority is given (e.g., 0 or 5), print "Error: priority must be 1, 2, or 3" to stderr and exit with code 2.
  - This applies to both `add --priority` and `edit --priority`.
- **Empty titles**: `add ""` (empty string title) should print "Error: title must not be empty" to stderr and exit with code 2.
  - Whitespace-only titles like `add "   "` should also be rejected.

Validation errors should print to stderr (not stdout) and return exit code 2 (usage error).
