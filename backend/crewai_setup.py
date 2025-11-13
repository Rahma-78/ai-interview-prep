"""
Workaround for CrewAI's OpenAI API key requirement
This script initializes OpenAI with a placeholder to satisfy CrewAI's checks
while still using Groq, Gemini, and OpenRouter as the actual LLMs
"""

import os
from dotenv import load_dotenv

load_dotenv()

# CrewAI's telemetry/event tracing is now enabled
# os.environ["CREWAI_TELEMETRY_OPT_OUT"] = "true"

# CrewAI requires OPENAI_API_KEY to be set, even if not used
# This is a known limitation of the crewai library
# Solution: Set a dummy but valid-looking key if not already set

def ensure_openai_key():
    """Ensure OPENAI_API_KEY is set for CrewAI compatibility"""
    if not os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_API_KEY") == "DUMMY_KEY_FOR_CREWAI_CHECK":
        # Use a placeholder key that satisfies the format check
        # This won't actually be used since we're using other LLMs
        os.environ["OPENAI_API_KEY"] = "sk-placeholder-for-crewai-check-not-used"
    
    # Verify other required keys
    required_keys = {
        "GROQ_API_KEY": "Groq LLM for skill extraction",
        "GOOGLE_API_KEY": "Google Generative AI (Gemini)",
        "SERPER_API_KEY": "Serper for Google Search",
        "OPENROUTER_API_KEY": "OpenRouter (DeepSeek) for question generation"
    }
    
    missing_keys = []
    for key, description in required_keys.items():
        if not os.environ.get(key):
            missing_keys.append(f"  - {key}: {description}")
    
    if missing_keys:
        print("⚠️  WARNING: Missing required API keys:")
        print("\n".join(missing_keys))
        print("\nPlease add these keys to your .env file")
        return False
    
    return True

if __name__ == "__main__":
    if ensure_openai_key():
        print("✅ All required API keys are configured")
    else:
        print("❌ Some required API keys are missing")
