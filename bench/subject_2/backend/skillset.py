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

"""SkillSet - A vector database toolset for ADK agents."""

from __future__ import annotations

import logging
from typing import Any, Optional

from google.adk.agents.readonly_context import ReadonlyContext
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.adk.tools.tool_context import ToolContext
from google.adk.models.llm_request import LlmRequest
from google.genai import types

from knowledge_service import KnowledgeServiceManager

logger = logging.getLogger(__name__)


class SearchSkillSetTool(BaseTool):
    """Tool for searching a SkillSet."""
    
    def __init__(
        self,
        skillset_id: str,
        project_id: str,
        manager: KnowledgeServiceManager,
        model_name: str,
        top_k: int = 10,
        min_score: float = 0.4,
    ):
        super().__init__(
            name=f"search_{skillset_id}",
            description=(
                f"Search the {skillset_id} knowledge base. "
                "Use this to find relevant information based on a query."
            ),
        )
        self.skillset_id = skillset_id
        self.project_id = project_id
        self.manager = manager
        self.model_name = model_name
        self.top_k = top_k
        self.min_score = min_score
    
    def _get_declaration(self) -> Optional[types.FunctionDeclaration]:
        """Get the function declaration for this tool."""
        return types.FunctionDeclaration(
            name=self.name,
            description=self.description,
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="The search query string",
                    ),
                },
                required=["query"],
            ),
        )
    
    async def run_async(
        self, *, args: dict[str, Any], tool_context: ToolContext
    ) -> str:
        """Execute the search."""
        query = args.get("query", "")
        if not query:
            return "Error: No query provided"
        
        try:
            store = self.manager.get_store(
                self.project_id,
                self.skillset_id,
                self.model_name,
            )
            results = store.search(
                query=query,
                top_k=self.top_k,
                min_score=self.min_score,
            )
            
            if not results:
                return f"No relevant information found for query: {query}"
            
            # Format results
            formatted = [
                f"[Score: {r.score:.2f}] {r.entry.text}"
                for r in results
            ]
            return "\n\n".join(formatted)
            
        except Exception as e:
            logger.error(f"Search failed: {e}")
            return f"Error searching knowledge base: {e}"


class SkillSet(BaseToolset):
    """A vector database toolset for ADK agents.
    
    Provides both explicit search tools and automatic knowledge preloading
    into agent instructions.
    """
    
    def __init__(
        self,
        *,
        skillset_id: str,
        project_id: str,
        manager: KnowledgeServiceManager,
        model_name: str = "text-embedding-004",
        search_enabled: bool = True,
        preload_enabled: bool = True,
        search_top_k: int = 10,
        search_min_score: float = 0.4,
        preload_top_k: int = 3,
        preload_min_score: float = 0.5,
        **kwargs,
    ):
        """Initialize the SkillSet toolset.
        
        Args:
            skillset_id: The ID of the SkillSet
            project_id: The project ID
            manager: The KnowledgeServiceManager
            model_name: The embedding model name
            search_enabled: Whether to include the search tool
            preload_enabled: Whether to preload knowledge into instructions
            search_top_k: Number of results for explicit search
            search_min_score: Minimum score for explicit search
            preload_top_k: Number of results for preloading
            preload_min_score: Minimum score for preloading
            **kwargs: Additional arguments for BaseToolset
        """
        super().__init__(**kwargs)
        self.skillset_id = skillset_id
        self.project_id = project_id
        self.manager = manager
        self.model_name = model_name
        self.search_enabled = search_enabled
        self.preload_enabled = preload_enabled
        self.search_top_k = search_top_k
        self.search_min_score = search_min_score
        self.preload_top_k = preload_top_k
        self.preload_min_score = preload_min_score
        
        # Create search tool if enabled
        self._search_tool: Optional[SearchSkillSetTool] = None
        if search_enabled:
            self._search_tool = SearchSkillSetTool(
                skillset_id=skillset_id,
                project_id=project_id,
                manager=manager,
                model_name=model_name,
                top_k=search_top_k,
                min_score=search_min_score,
            )
    
    async def get_tools(
        self,
        readonly_context: Optional[ReadonlyContext] = None,
    ) -> list[BaseTool]:
        """Return the search tool if enabled."""
        if self._search_tool:
            return [self._search_tool]
        return []
    
    async def process_llm_request(
        self, *, tool_context: ToolContext, llm_request: LlmRequest
    ) -> None:
        """Preload relevant knowledge into agent instructions.
        
        This method is called before the LLM request is sent.
        It searches the knowledge base and injects relevant information
        into the system instructions.
        """
        import traceback
        
        # Set state variable to track that we were called
        print(f"\n{'='*60}")
        print(f"[SkillSet] process_llm_request CALLED!")
        print(f"[SkillSet] skillset_id={self.skillset_id}")
        print(f"[SkillSet] project_id={self.project_id}")
        print(f"[SkillSet] preload_enabled={self.preload_enabled}")
        print(f"[SkillSet] model_name={self.model_name}")
        print(f"{'='*60}\n")
        
        # Track in state
        try:
            tool_context.state[f"_skillset_{self.skillset_id}_called"] = True
        except Exception as e:
            print(f"[SkillSet] Could not set state: {e}")
        
        if not self.preload_enabled:
            print(f"[SkillSet] Preloading DISABLED for {self.skillset_id}")
            tool_context.state[f"_skillset_{self.skillset_id}_status"] = "disabled"
            return
        
        # Get the last user message as the query
        query = None
        print(f"[SkillSet] Searching for user query in {len(llm_request.contents)} contents...")
        for i, content in enumerate(reversed(llm_request.contents)):
            print(f"[SkillSet]   Content {i}: role={content.role}, parts={len(content.parts)}")
            if content.role == "user":
                # Extract text from the content
                for part in content.parts:
                    if hasattr(part, "text") and part.text:
                        query = part.text
                        print(f"[SkillSet]   Found query: {query[:100]}...")
                        break
                if query:
                    break
        
        if not query:
            print(f"[SkillSet] NO USER QUERY FOUND!")
            tool_context.state[f"_skillset_{self.skillset_id}_status"] = "no_query"
            return
        
        tool_context.state[f"_skillset_{self.skillset_id}_query"] = query[:200]
        print(f"[SkillSet] Query: {query[:200]}")
        
        try:
            print(f"[SkillSet] Getting store...")
            store = self.manager.get_store(
                self.project_id,
                self.skillset_id,
                self.model_name,
            )
            
            print(f"[SkillSet] Store stats: {store.stats()}")
            
            print(f"[SkillSet] Searching with top_k={self.preload_top_k}, min_score={self.preload_min_score}...")
            results = store.search(
                query=query,
                top_k=self.preload_top_k,
                min_score=self.preload_min_score,
            )
            
            print(f"[SkillSet] Search returned {len(results)} results")
            tool_context.state[f"_skillset_{self.skillset_id}_results"] = len(results)
            
            if not results:
                print(f"[SkillSet] NO RESULTS FOUND (try lowering min_score)")
                tool_context.state[f"_skillset_{self.skillset_id}_status"] = "no_results"
                return
            
            # Log each result
            for i, r in enumerate(results):
                print(f"[SkillSet]   Result {i}: score={r.score:.3f}, text={r.entry.text[:100]}...")
            
            # Format knowledge for injection
            knowledge_text = "\n\n".join([
                f"--- Relevant Knowledge (Score: {r.score:.2f}) ---\n{r.entry.text}"
                for r in results
            ])
            
            preload_instruction = (
                f"\n\n# Knowledge Base Context\n\n"
                f"The following information from the {self.skillset_id} "
                f"knowledge base may be relevant to the user's query:\n\n"
                f"{knowledge_text}\n"
            )
            
            # Append to system instructions using ADK's append_instructions method
            print(f"[SkillSet] Appending to system instructions via llm_request.append_instructions()")
            llm_request.append_instructions([preload_instruction])
            print(f"[SkillSet] Instructions appended successfully!")
            tool_context.state[f"_skillset_{self.skillset_id}_status"] = f"injected_{len(results)}"
            tool_context.state[f"_skillset_{self.skillset_id}_preview"] = knowledge_text[:500]
            
            print(f"[SkillSet] SUCCESS! Preloaded {len(results)} entries")
            print(f"{'='*60}\n")
            
        except Exception as e:
            print(f"[SkillSet] ERROR: {e}")
            print(traceback.format_exc())
            tool_context.state[f"_skillset_{self.skillset_id}_error"] = str(e)
            tool_context.state[f"_skillset_{self.skillset_id}_status"] = "error"

