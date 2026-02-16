---
name: status
description: Quick summary of the BDD catalog — how many expectations are satisfied, what's next.
user-invocable: true
allowed-tools: Read
---

Show a quick summary of the BDD catalog.

## Steps

1. Call `bdd_status()` and display the results.

2. Call `bdd_tree()` and display the hierarchical view.

3. If there are unsatisfied expectations, call `bdd_next()` to show what would be worked on next.

4. Provide a brief assessment: Is the project on track? What areas need attention?
