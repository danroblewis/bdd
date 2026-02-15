---
name: suggest
description: Use when a user describes a feature area or desire. Proposes goals, expectations, and facets, adding them to the catalog immediately. The human reviews and prunes.
argument-hint: "description of what you want"
user-invocable: true
allowed-tools: Bash, Read, Grep, Glob
---

Suggest and add catalog entries from a description.

## Steps

1. Read `$ARGUMENTS` — the user's description of what they want.

2. Run `bdd tree` to see the current catalog state. Understand what already exists.

3. Based on the description, propose a set of catalog entries:
   - If no relevant goal exists, create one with `bdd add goal "..."`.
   - Create expectations under the goal with `bdd add expectation "..." --parent <goal-id>`.
   - For concrete, testable details mentioned, create facets with `bdd add facet "..." --parent <expectation-id>`.

4. **Act immediately** — add the entries to the catalog. Do not ask for permission first. The human will review and remove what doesn't fit. This is the act-then-review style.

5. After adding, run `bdd tree` to show the user the updated catalog.

6. Summarize what was added and suggest any follow-up areas the user might want to consider.
