from app.core.config import settings
from google import genai
from google.genai import types

"""
Language Model (LLM) and AI client configuration.

This module provides:
- ChatGroq for skill extraction (llama-3.3-70b-versatile)
- ChatGroq for question generation (openai/gpt-oss-120b)
- GenAI SDK client for source discovery
- Consistent temperature and API key handling
"""


# --- LangChain LLM Instances (Direct, Fast) ---

from langchain_groq import ChatGroq

# ChatGroq - For skill extraction (fast, precise skill identification)
chat_groq_skill_extraction = ChatGroq(
    model="openai/gpt-oss-20b",
    temperature=0.2,
    api_key=settings.GROQ_API_KEY,
)

# ChatGroq - For question generation (larger context, better question quality)
chat_groq_question_generation = ChatGroq(
    model="openai/gpt-oss-120b",
    temperature=0.2,
    api_key=settings.GROQ_API_KEY,
    max_tokens=4096  # Increased for question generation (10 questions per skill)
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
