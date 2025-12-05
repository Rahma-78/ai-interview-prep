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

# for testing

llm_groq = get_llm(
    "groq/llama-3.3-70b-versatile",
    temperature=0.2,
    api_key=settings.GROQ_API_KEY,
    
)

# Meta via huggingface - For skill extraction (Agent 1)
llm_meta =get_llm(
    "openrouter/meta-llama/Llama-3.1-8B-Instruct",
    temperature=0.2,
    api_key=settings.OPENROUTER_API_KEY
)
  
 # openai via huggingface - For question generation(Agent 3)   
llm_openai = get_llm(
    "openrouter/openai/gpt-oss-120b",
    temperature=0.2,
    api_key=settings.OPENROUTER_API_KEY,
    
                              
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
