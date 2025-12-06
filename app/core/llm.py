from crewai.llm import LLM
from app.core.config import settings
from google import genai
from google.genai import types

"""
Language Model (LLM) and AI client configuration.

This module provides:
- CrewAI LLM instances for agents
- GenAI SDK client for source discovery
- Consistent temperature and API key handling
"""

def get_llm(model: str, api_key: str, temperature: float = 0.1, **kwargs):
    """Initializes and returns a CrewAI LLM instance."""
    return LLM(model=model, temperature=temperature, api_key=api_key, **kwargs)

# --- LangChain LLM Instances (Direct, Fast) ---

# ChatGroq - For skill extraction (fast inference, no CrewAI overhead)
from langchain_groq import ChatGroq
chat_groq = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.2,
    api_key=settings.GROQ_API_KEY,
    max_tokens=1024
)

# --- CrewAI LLM Instances (for agents) ---

# openai via OpenRouter - For question generation (Agent 3)
# Provider: OpenRouter (gpt-oss-120b)
# Context: 128k tokens max, Output: Conservative 4k to avoid credit errors
llm_openai = get_llm(
    "openrouter/openai/gpt-oss-120b",
    temperature=0.2,
    api_key=settings.OPENROUTER_API_KEY,
    max_tokens=4096  # Safe limit - prevents "can only afford X tokens" errors
)

# --- GenAI SDK Client ---

# Pre-initialize client at module load time to avoid blocking during first API call
# This moves the initialization overhead to app startup rather than during batch processing
_genai_client = None

def get_genai_client() -> genai.Client:
    """Get or create the GenAI SDK client instance for source discovery."""
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _genai_client

# Pre-initialize on module load (moves blocking to startup, not first request)
try:
    _genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
except Exception as e:
    import logging
    logging.getLogger(__name__).warning(f"GenAI client pre-initialization failed: {e}")

# Model constant for source discovery
GEMINI_MODEL = 'gemini-2.5-flash'
