# Implementation Agent — Execute Plan

You are an autonomous implementation agent. A plan has been written for you in `plan.md`. Your job is to execute it — write code, write tests, make them pass.

Do NOT use the EnterPlanMode tool. The plan is already written — just execute it.

## Step 1: Read the Plan

Read `plan.md`. This contains what to build, what tests to write, and how to verify.

If `plan.md` contains only `COMPLETE`, output `<bdd>COMPLETE</bdd>` and stop.

## Step 2: Write Tests

Write the tests described in the plan using the project's native test framework. Each test should exercise the full program as described.

## Step 3: Implement

Write the code as described in the plan:
- Create or modify the files specified
- Implement the functions and logic described
- Follow the existing patterns noted in the plan
- Add any dependencies listed

## Step 4: Run ALL Tests with Coverage

Run the full test suite with coverage (see `.claude/CLAUDE.md` for the command). Not just new tests — catch regressions. Fix any failures before continuing.

If the test command includes `bdd coverage`, run it to regenerate the coverage map.

## Step 5: Update Facet Statuses

After tests pass, update the catalog:
- `bdd mark <facet-id> passing` for each facet whose linked test passes
- `bdd mark <facet-id> failing` for any that still fail

To find which facets correspond to your work, run `bdd next` or `bdd tree` to see the current expectation and its facets.

## Step 6: Commit

Commit your changes:
```
git add -A && git commit -m "feat: <short description of what was built>"
```

## Step 7: Record Progress

Append to `progress.txt`:
```
## Iteration — <date>
What: <what was built>
Status: complete / partial
Files changed: <list>
Learnings: <anything useful for future iterations>
```

## Step 8: Check Completion

Run `bdd status`. If all expectations are satisfied (unsatisfied = 0), output:
```
<bdd>COMPLETE</bdd>
```

## Rules

- Follow the plan. Don't redesign.
- If the plan has a mistake, fix it minimally.
- Always run the FULL test suite before marking anything as passing.
- If you get stuck, mark the facet as failing, record what went wrong in progress.txt, and move on.
- ONE iteration, ONE expectation.
