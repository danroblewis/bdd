# Copyright 2025 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from __future__ import annotations

from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.lite_llm import LiteLlm

# MLX server provides OpenAI-compatible API
# We'll use LiteLLM to connect to it
# Use custom_llm_provider to bypass model validation
root_agent = LlmAgent(
  name="mlx_test_agent",
  model=LiteLlm(
    model="mlx-community/gemma-3-12b-it-8bit",
    api_base="http://localhost:8082/v1",
    api_key="dummy",  # MLX server doesn't need real auth
    custom_llm_provider="openai",  # Treat as OpenAI-compatible
  ),
  instruction="You are a helpful AI assistant running on Apple Silicon using the Metal ANE processor. Be concise and helpful.",
  description="Test agent for MLX local inference on Apple Silicon",
)

