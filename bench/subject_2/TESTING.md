# ADK Playground - Manual Testing Procedure

This document outlines manual testing procedures for the ADK Playground features.

## Prerequisites

- Backend running on `http://localhost:8080`
- Frontend running on `http://localhost:3000`
- A working LLM provider (Gemini API key or local Ollama)

---

## Test 1: Project Management

### 1.1 Create a New Project
1. Navigate to `http://localhost:3000`
2. Click "New Project" button
3. Enter project name: "Test Agent Project"
4. Click "Create"
5. **Expected**: Redirected to project editor with the new project loaded

### 1.2 Verify Project Appears in List
1. Click "Projects" in the top bar to return to project list
2. **Expected**: "Test Agent Project" appears in the projects grid

### 1.3 Delete a Project
1. Hover over a project card
2. Click the trash icon
3. Confirm deletion
4. **Expected**: Project removed from the list

---

## Test 2: App Configuration

### 2.1 Basic Info
1. Open a project
2. Go to "App Config" tab
3. Change the App Name to "My Test App"
4. Set Description to "A test application"
5. **Expected**: Fields update and show "Unsaved changes"

### 2.2 Configure Services
1. In the Services section, change Session Service to "SQLite"
2. **Expected**: Dropdown updates to show "SQLite"

### 2.3 Enable Compaction
1. Toggle "Event Compaction" on
2. Set max events to 50
3. **Expected**: Toggle turns green, max events field appears

### 2.4 Add State Keys
1. Click "Add Key" in Session State Keys section
2. Fill in:
   - Name: `story`
   - Type: String
   - Scope: Session
   - Description: "The story being written"
3. Add another key:
   - Name: `iteration_count`
   - Type: Number
   - Scope: Session
4. **Expected**: Both state keys appear in the list

### 2.5 Add Plugin
1. Click "Add Plugin" in Plugins section
2. Select "Reflect & Retry Tool"
3. Set max retries to 5
4. **Expected**: Plugin appears with configuration options

### 2.6 Save Configuration
1. Click "Save" button in top bar
2. **Expected**: "Unsaved changes" indicator disappears

---

## Test 3: Agent Creation

### 3.1 Create an LLM Agent
1. Go to "Agents" tab
2. Click "Add" button
3. Select "LLM Agent"
4. **Expected**: New agent appears in sidebar and editor opens

### 3.2 Configure the Agent
1. Name the agent "writer_agent"
2. Set Description: "Writes creative stories"
3. Set Instruction: "You are a creative writer. Write engaging short stories based on user prompts."
4. Expand "Model" section
5. Set Provider to "Gemini" (or "LiteLLM" if using Ollama)
6. Set Model Name to "gemini-2.0-flash" (or "ollama/llama3.2:3b")
7. If using LiteLLM, set API Base to your endpoint
8. Set Output Key to "story" (from state keys)
9. **Expected**: All fields save correctly

### 3.3 Add Tools to Agent
1. Expand "Tools" section
2. Click "Add Tool"
3. From Built-in Tools, select "google_search"
4. **Expected**: Tool appears in the tools list

### 3.4 Create a Workflow Agent
1. Click "Add" button again
2. Select "Sequential"
3. Name it "story_workflow"
4. In Sub-Agents section, add "writer_agent"
5. **Expected**: Sequential agent with sub-agent reference

### 3.5 Create a Loop Agent
1. Click "Add" button
2. Select "Loop"
3. Name it "refinement_loop"
4. Set Max Iterations to 3
5. **Expected**: Loop agent with iteration limit

### 3.6 Set Root Agent
1. Go back to "App Config" tab
2. In Root Agent dropdown, select the main agent
3. **Expected**: Dropdown shows all created agents

---

## Test 4: Custom Tools

### 4.1 Create a Custom Tool
1. Go to "Tools" tab
2. Click "New" button
3. **Expected**: New tool appears in sidebar

### 4.2 Configure the Tool
1. Set Name to "save_story"
2. Set Description to "Saves the story to state"
3. Set Module Path to "tools.story_utils"
4. Replace code with:
```python
def save_story(tool_context: ToolContext, story: str) -> dict:
    """Saves the story to the session state.
    
    Args:
        story: The story content to save
    
    Returns:
        A confirmation message
    """
    tool_context.state['story'] = story
    return {"status": "saved", "length": len(story)}
```
5. Check the "story" state key in "State Keys Used"
6. Click "Save"
7. **Expected**: Code saves, "Unsaved" badge disappears

### 4.3 Add Custom Tool to Agent
1. Go back to "Agents" tab
2. Select the writer_agent
3. In Tools section, click "Add Tool"
4. Under "Custom Tools", select "save_story"
5. **Expected**: Custom tool appears in agent's tool list

---

## Test 5: YAML Import/Export

### 5.1 View YAML
1. Go to "YAML" tab
2. **Expected**: Full project configuration displayed in YAML format

### 5.2 Edit YAML
1. Find the agent name in the YAML
2. Change it to "modified_agent"
3. Click "Apply Changes"
4. Go to "Agents" tab
5. **Expected**: Agent name updated

### 5.3 Download YAML
1. Go to "YAML" tab
2. Click "Download"
3. **Expected**: File downloads as `{project_name}.yaml`

### 5.4 Copy YAML
1. Click "Copy"
2. **Expected**: "Copied!" indicator appears

---

## Test 6: Runtime Execution (Full Agent Run)

### 6.1 Setup for Run
1. Ensure you have a working agent with:
   - Valid model configuration
   - Clear instruction
   - Optionally some tools
2. Set this agent as the root agent in App Config
3. Save all changes

### 6.2 Run the Agent
1. Go to "Run" tab
2. In the input textarea, enter: "Write a short story about a robot learning to paint"
3. Click "Run"
4. **Expected**: 
   - Events start streaming in real-time
   - Agent start event appears
   - Model call events show
   - Model response events with text
   - Agent end event when complete

### 6.3 Verify Timeline
1. After run completes, observe the timeline section
2. **Expected**: Timeline shows event count and duration

### 6.4 Inspect Events
1. Click on an agent group to expand/collapse
2. Click on individual events to see details
3. **Expected**: Event details show in JSON format

### 6.5 State Changes
1. If the agent used output_key, look for "state_change" events
2. **Expected**: State delta shows the saved value

### 6.6 Stop Running Agent
1. Start another run with a long prompt
2. Click "Stop" while it's running
3. **Expected**: Run stops, events cease

---

## Test 7: Evaluation Tests

### 7.1 Create Test Group
1. Go to "Evaluate" tab
2. Select "All Tests" in the sidebar
3. Click the folder icon to add a group
4. Name it "Story Tests"
5. **Expected**: New group appears under All Tests

### 7.2 Create a Test Case
1. With "Story Tests" selected, click "Test" button
2. Configure the test:
   - Name: "Basic story generation"
   - Description: "Tests that the agent can generate a story"
   - Input Message: "Write a one paragraph story about a cat"
   - Expected Output: "cat" (partial match)
3. **Expected**: Test appears with pending status

### 7.3 Run Single Test
1. Click the play button on the test
2. **Expected**: Test runs, result shows pass/fail

### 7.4 Run Test Group
1. Click the play button on "Story Tests" group
2. **Expected**: All tests in group run sequentially

### 7.5 View Results
1. After tests complete, observe the stats badges on groups
2. Click a test to see detailed results
3. **Expected**: Pass/fail with duration shown

---

## Test 8: Error Handling

### 8.1 Invalid YAML
1. Go to YAML tab
2. Add invalid YAML (e.g., remove a colon)
3. Click "Apply Changes"
4. **Expected**: Error message appears, changes not applied

### 8.2 Missing Root Agent
1. Go to App Config
2. Clear the Root Agent selection
3. Go to Run tab and try to run
4. **Expected**: Error message about missing root agent

### 8.3 Network Error Recovery
1. Stop the backend server
2. Try to save a project
3. **Expected**: Error message shown
4. Restart backend
5. Save again
6. **Expected**: Save succeeds

---

## Test 9: UI/UX

### 9.1 Responsive Sidebar
1. In Agents panel, create multiple agents
2. Scroll the sidebar if needed
3. **Expected**: Scrolling works, selected item visible

### 9.2 Dark Theme Consistency
1. Check all panels for consistent styling
2. **Expected**: All elements use the cyberpunk theme colors

### 9.3 Form Validation
1. Try to create an agent with empty name
2. **Expected**: Either prevented or handled gracefully

### 9.4 Keyboard Navigation
1. Tab through form elements
2. Press Enter to submit where appropriate
3. **Expected**: Reasonable keyboard navigation support

---

## Test Checklist Summary

- [ ] Project create/delete
- [ ] App configuration (all fields)
- [ ] State keys management
- [ ] Plugin configuration
- [ ] LLM Agent creation and config
- [ ] Workflow agents (Sequential, Loop, Parallel)
- [ ] Sub-agent relationships
- [ ] Tool configuration (builtin, custom, MCP)
- [ ] Custom tool Python editing
- [ ] YAML export/import
- [ ] Full agent run with event streaming
- [ ] Timeline and event inspection
- [ ] Evaluation test creation
- [ ] Test execution (single and group)
- [ ] Error handling
- [ ] UI consistency

---

## Known Limitations

1. **MCP Tools**: Require npx and appropriate packages installed
2. **Agent Execution**: Requires valid API keys for cloud models
3. **Evaluation**: Currently simulates test results (backend integration pending)
4. **WebSocket**: Requires stable connection for streaming

