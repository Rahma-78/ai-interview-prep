from app.core.config import settings
from crewai.llm import LLM

"""
Language Model (LLM) configuration and initialization.

This module provides:
- Centralized LLM instance management
- Pre-configured models for different tasks
- Consistent temperature and API key handling
"""


def get_llm(model: str, temperature: float = 0.1, api_key: str | None = None) -> LLM:
    """
    Retrieves an LLM instance from CrewAI.

    Args:
        model (str): The name of the LLM model to use.
        temperature (float): The temperature setting for the LLM.
        api_key (str | None): The API key for the LLM service.

    Returns:
        LLM: An instance of the CrewAI LLM.
    """
    return LLM(model=model, temperature=temperature, api_key=api_key)


# 1. Gemini Flash - For content extraction
llm_gemini_flash = get_llm("gemini/gemini-2.5-flash",
                           temperature=0.1,
                           api_key=settings.GEMINI_API_KEY)

# 2. Groq Llama - For skill extraction
llm_groq = get_llm(
    "groq/openai/gpt-oss-120b",
    temperature=0.2,
    api_key=settings.GROQ_API_KEY
)

# 3. DeepSeek via OpenRouter - For question generation
llm_openrouter = get_llm(
    "openrouter/deepseek/deepseek-chat",
    temperature=0.7,
    api_key=settings.OPENROUTER_API_KEY
)


