from app.core.config import settings
from google import genai
from google.genai import types
import httpx

"""
Language Model (LLM) and AI client configuration.

This module provides:
- LangChain LLM instances for direct calls (ChatGroq, ChatOpenAI)
- GenAI SDK client for source discovery
- Consistent temperature and API key handling
"""


# --- LangChain LLM Instances (Direct, Fast) ---

# ChatGroq - For skill extraction (fast inference, no CrewAI overhead)
from langchain_groq import ChatGroq
chat_groq = ChatGroq(
    model="llama-3.3-70b-versatile",
    temperature=0.2,
    api_key=settings.GROQ_API_KEY,
    max_tokens=1024
)

# ChatOpenAI via OpenRouter - For question generation (fast, no CrewAI overhead)
# Provider: OpenRouter (gpt-oss-120b)
# Context: 128k tokens max, Output: 4k tokens
from langchain_openai import ChatOpenAI

# Create custom httpx client with optimized settings for faster streaming
# Connection pool supports concurrent batches while serialization lock prevents rate limiting
http_async_client = httpx.AsyncClient(
    limits=httpx.Limits(
        max_connections=50,           # Total connection pool (supports 3+ concurrent streams)
        max_keepalive_connections=20, # Persistent connections for reuse
    ),
    timeout=httpx.Timeout(60.0),      # 1 minute timeout (reduced from 120s)
)

chat_openrouter = ChatOpenAI(
    model="openai/gpt-oss-120b",
    temperature=0.2,
    api_key=settings.OPENROUTER_API_KEY,
    base_url="https://openrouter.ai/api/v1",
    max_tokens=2048,                  # Optimized from 4096 (reduces generation time)
    http_async_client=http_async_client,  # Custom client with optimized settings
)

# --- GenAI SDK Client ---

# Pre-initialize client at module load time to avoid blocking during first API call
# This moves the initialization overhead to app startup rather than during batch processing
# Fail fast if API key is invalid
try:
    _genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
except Exception as e:
    import logging
    logger = logging.getLogger(__name__)
    logger.error(f"Failed to initialize GenAI client: {e}")
    raise  # Fail fast - don't continue if client can't be created

def get_genai_client() -> genai.Client:
    """Get the GenAI SDK client instance for source discovery."""
    return _genai_client

# Model constant for source discovery
GEMINI_MODEL = 'gemini-2.5-flash'
