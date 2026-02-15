# Introspection Services

An introspection service is a runtime adapter that lets the development agent perceive the application the way a user would — without looking at a screen.

## What It Is

Introspection is NOT a catalog browser or a test runner. It is a live query interface into the running application. It answers: "What does the user see right now?"

The ideal introspection service supports **arbitrary evaluation** in the running application — like a developer's REPL or debug console, but accessible to the agent via CLI or socket.

## Why It Matters

Without introspection, the agent is blind. It can write code and run tests, but it cannot:
- Verify visual correctness ("is the button actually visible?")
- Debug user-facing issues ("what's on screen when this fails?")
- Make judgment calls about quality ("does this look right?")

Behavior tests validate specific facets. Introspection gives the agent general awareness.

## The Principle

> If a user can perceive it, the agent can query it.
> If a developer can debug it, the agent can eval into it.

## Patterns by Project Type

### Game (SDL2, Unity, Godot, etc.)
- Unix socket or TCP server in the game loop
- Commands: `state` (current mode/scene), `manifest` (all visible objects), `screenshot`, `eval`
- The game exposes its scene graph, UI state, and frame data

### Web Application (React, Vue, etc.)
- Headless browser (Playwright/Puppeteer) controlled via CLI
- Commands: `page.evaluate(...)`, `screenshot`, `querySelector`, accessibility tree dump
- The agent can read DOM state and execute JavaScript in the page context

### CLI Application
- Run the CLI with test inputs, capture stdout/stderr
- If the CLI has a REPL mode, pipe commands and read output
- For TUI apps, use `script` or `tmux capture-pane` to get terminal state

### Backend Service (API, daemon)
- HTTP endpoints for health, state inspection, metrics
- Debug endpoints (only in dev mode) that expose internal state
- Database queries for verifying persisted state

## Building an Introspection Service

When you're early in a project and no introspection exists:

1. **Start minimal**: a single command that reports the application's current state
2. **Expose the UI layer**: what's visible, what's active, what text is on screen
3. **Add evaluation**: ability to run arbitrary queries against live state
4. **Document in CLAUDE.md**: add the commands to the Introspect section

The introspection service grows alongside the application. Each time you implement a new feature, extend introspection to cover it.

## Integration with BDD

- Behavior tests use introspection to assert against live state
- The agent uses introspection to verify work beyond what tests cover
- The inject-context hook can surface introspection results after test runs
- Facets like "button is visible" map directly to introspection queries

## When to Build vs. Skip

**Build introspection when:**
- The project has a visual/interactive component
- Tests need to verify user-visible state
- You're iterating on UX behavior

**Skip introspection when:**
- The project is a pure library with no UI
- All behavior can be verified through function calls and exit codes
- The project is a one-off script
