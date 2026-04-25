"""Generic LLM service for structured output classification.

Reusable across multiple apps — pass your own prompt and output schema.
"""

import logging
from typing import Any, Type

from django.conf import settings
from pydantic import BaseModel

logger = logging.getLogger(__name__)


class LLMService:
    """Generic LangChain OpenAI service for structured output."""

    def __init__(
        self,
        model: str = None,
        api_key: str = None,
        temperature: float = 0.0,
        timeout: int = 30,
    ):
        self.model = model or settings.OPENAI_MODEL
        self.api_key = api_key or settings.OPENAI_API_KEY
        self.temperature = temperature
        self.timeout = timeout

    def classify(
        self,
        prompt: str,
        user_input: str,
        output_schema: Type[BaseModel],
    ) -> BaseModel:
        """Send a system prompt + user input to the LLM and return structured output.

        Args:
            prompt: System prompt for the LLM.
            user_input: User-facing content (e.g., webhook payload).
            output_schema: Pydantic model class for structured output.

        Returns:
            An instance of `output_schema` populated by the LLM.
        """
        from langchain_openai import ChatOpenAI

        llm = ChatOpenAI(
            model=self.model,
            api_key=self.api_key,
            temperature=self.temperature,
            request_timeout=self.timeout,
        )
        structured_llm = llm.with_structured_output(output_schema)
        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": user_input},
        ]
        return structured_llm.invoke(messages)
