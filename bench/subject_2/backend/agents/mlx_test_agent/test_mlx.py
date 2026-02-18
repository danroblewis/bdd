#!/usr/bin/env python3
"""Simple test script for the MLX agent."""

import asyncio
from google.adk.runners import Runner
from google.adk.sessions.in_memory_session_service import InMemorySessionService
from .agent import root_agent


async def main():
  """Run a simple test query."""
  runner = Runner(
    app_name="mlx_test",
    agent=root_agent,
    session_service=InMemorySessionService()
  )
  
  query = "What are the benefits of running AI models locally on Apple Silicon?"
  
  print(f"\n🤖 Asking: {query}\n")
  
  from google.genai import types
  
  async for event in runner.run_async(
    user_id="test_user",
    session_id="test_session",
    new_message=types.Content(
      role="user",
      parts=[types.Part.from_text(text=query)]
    )
  ):
    if hasattr(event, 'content') and event.content:
      for part in event.content.parts:
        if hasattr(part, 'text') and part.text:
          print(part.text, end='', flush=True)
  
  print("\n\n✅ Test complete!")


if __name__ == "__main__":
  asyncio.run(main())

