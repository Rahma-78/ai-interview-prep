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

# --- CrewAI LLM Instances ---

# Gemini Flash - For source discovery agent orchestration (Agent 2)
llm_gemini = get_llm(
    "gemini/gemini-2.5-flash",
    temperature=0.2,
    api_key=settings.GEMINI_API_KEY
)

# Groq Llama - For skill extraction (Agent 1)

llm_groq = get_llm(
    "groq/llama-3.3-70b-versatile",
    temperature=0.7,
    api_key=settings.GROQ_API_KEY,
    
)

# DeepSeek via OpenRouter - For question generation (Agent 3)
llm_openrouter = get_llm(
    "openrouter/x-ai/grok-4.1-fast:free",
    temperature=0.7,
    api_key=settings.OPENROUTER_API_KEY,
    extra_body={"include_reasoning": False}
)
llm_deepseek = get_llm(
    "groqllama-3.1-8b-instant",
    temperature=0.7,
    api_key=settings.GROQ_API_KEY,
    
)

# --- GenAI SDK Client ---

# Singleton client for source discovery tool (Agent 2's tool)
_genai_client = None

def get_genai_client() -> genai.Client:
    """Get or create the GenAI SDK client instance for source discovery."""
    global _genai_client
    if _genai_client is None:
        _genai_client = genai.Client(api_key=settings.GEMINI_API_KEY)
    return _genai_client

# Model constant for source discovery
GEMINI_MODEL = 'gemini-2.5-flash'
