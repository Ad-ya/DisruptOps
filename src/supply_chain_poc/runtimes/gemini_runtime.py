from __future__ import annotations

import os
from functools import cached_property
from typing import Any

from supply_chain_poc.core.runtime.base_runtime import AgentRuntime
from supply_chain_poc.config import ModelSettings
from supply_chain_poc.models import AgentContext, AgentRequest, AgentResult, Tool


class GeminiRuntime(AgentRuntime):
    def __init__(self, settings: ModelSettings, *, model: Any = None) -> None:
        self.settings = settings
        self._provided_model = model

    @cached_property
    def model(self) -> Any:
        if self._provided_model is not None:
            return self._provided_model
        if not (os.getenv('GOOGLE_API_KEY') or os.getenv('GEMINI_API_KEY')):
            raise RuntimeError('Set GOOGLE_API_KEY before making a live Gemini call.')
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=self.settings.name, temperature=self.settings.temperature,
            max_output_tokens=self.settings.max_output_tokens, max_retries=1,
            timeout=self.settings.timeout_seconds, thinking_level=self.settings.thinking_level, vertexai=False,
        )

    def build(self, request: AgentRequest, tools: list[Tool]) -> Any:
        from langchain.agents import create_agent
        from langchain.agents.structured_output import ToolStrategy
        from supply_chain_poc.middleware import build_middleware
        from supply_chain_poc.schemas.findings import FINDING_SCHEMAS

        return create_agent(
            model=self.model, tools=tools, system_prompt=request.system_prompt,
            context_schema=AgentContext,
            response_format=ToolStrategy(FINDING_SCHEMAS[request.role], handle_errors=False),
            middleware=build_middleware(request.middleware_names, request.max_model_calls, request.role),
        )

    def invoke(self, request: AgentRequest, tools: list[Tool]) -> AgentResult:
        graph = self.build(request, tools)
        state = graph.invoke(
            {'messages': [{'role': 'user', 'content': request.user_message}]},
            context=request.context,
            config={'recursion_limit': request.max_graph_steps},
        )
        if 'structured_response' not in state:
            raise ValueError('Agent did not return the required structured finding')
        finding = state['structured_response'].model_dump(mode='json')
        return AgentResult(request.role, request.context.case_id, finding)
