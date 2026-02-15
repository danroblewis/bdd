# Project Instructions

This project uses **Behavior Test Curation** (Emergent Alignment) as its development methodology.

## Methodology

Read @rules/methodology.md for the full approach. The short version:

- There is no spec document. The **catalog** (`catalog.json`) and the behavior test suite are the only sources of truth.
- The catalog contains **goals** (broad stakeholder intent), **expectations** (specific wants), and **facets** (testable pieces).
- When you write or modify code, check which expectations and facets are relevant.
- After modifying code, run behavior tests and update facet statuses with `bdd mark`.
- When you see untested facets related to your work, write behavior tests and link them with `bdd link`.
- When an expectation is removed by a human, suggest removing the corresponding tests.

## BDD Catalog Commands

```bash
bdd status                              # Summary: goals, expectations, facets, coverage %
bdd next                                # Next unsatisfied expectation to work on
bdd show <id>                           # Detail of a node + children + parent chain
bdd tree                                # Hierarchical view of entire catalog
bdd add <type> "text" [--parent <id>]   # Add goal/expectation/facet
bdd mark <facet-id> <status>            # Update facet: passing/failing/untested
bdd link <facet-id> <test-path>         # Associate facet with its test
bdd remove <id>                         # Remove a node
bdd edit <id> "new text"                # Edit node text
```

Add `--json` to any command for machine-readable output.

## Project Details

<!-- Fill these in during /bootstrap or manually -->

**Stack:** (describe your tech stack)

**Build:**
```bash
# build command here
```

**Test:**
```bash
# test command here
```

**Introspect:**
```bash
# introspection command here (if available)
```

**Key Paths:**
- (list important source directories and files)

## Working Style

- **Act then review**: When the human describes what they want, add expectations to the catalog immediately. The human will prune what doesn't fit.
- **Always motivate changes**: Every code change should trace back to a catalog entry.
- **Test from the user's perspective**: Behavior tests should validate what the user sees and experiences, not internal implementation details.
