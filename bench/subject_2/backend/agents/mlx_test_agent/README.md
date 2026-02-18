# MLX Test Agent

This agent demonstrates how to use Google ADK with a local MLX server running on Apple Silicon, leveraging the Metal ANE processor.

## Prerequisites

1. **Start MLX Server**: Make sure you have an MLX server running:
   ```bash
   mlx_lm.server --model mlx-community/gemma-3-12b-it-8bit --port 8082
   ```

2. **Activate Environment**:
   ```bash
   cd /Users/danroblewis/adk-playground
   source .venv/bin/activate
   ```

## Usage

### Interactive CLI

Run the agent interactively:

```bash
adk run /Users/danroblewis/adk-playground/backend/agents/mlx_test_agent
```

Then type your query when prompted.

### Single Query

Use `echo` to pipe a single query:

```bash
echo "What are the benefits of running AI models locally on Apple Silicon?" | \
  adk run /Users/danroblewis/adk-playground/backend/agents/mlx_test_agent
```

### Example Output

```
[mlx_test_agent]: Here's a concise breakdown of the benefits:

*   Privacy: Data stays on your device.
*   Speed: Low latency due to no network transfer.
*   Offline Use: Works without an internet connection.
*   Efficiency: Optimized for Apple Silicon (Metal ANE) for power efficiency.
*   Cost: No reliance on cloud services.
```

## How It Works

The agent uses ADK's `LiteLlm` class to connect to the OpenAI-compatible MLX server:

```python
from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.lite_llm import LiteLlm

root_agent = LlmAgent(
  name="mlx_test_agent",
  model=LiteLlm(
    model="mlx-community/gemma-3-12b-it-8bit",
    api_base="http://localhost:8082/v1",
    api_key="dummy",  # MLX server doesn't need real auth
    custom_llm_provider="openai",  # Treat as OpenAI-compatible
  ),
  instruction="You are a helpful AI assistant running on Apple Silicon using the Metal ANE processor.",
  description="Test agent for MLX local inference on Apple Silicon",
)
```

## Key Points

- **Local Inference**: All processing happens on your Mac using the ANE/GPU
- **Privacy**: No data sent to external servers
- **Fast**: Low latency since there's no network round-trip
- **Cost**: No API costs for inference
- **OpenAI-Compatible**: MLX server implements the OpenAI API standard





