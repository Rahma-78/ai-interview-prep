from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from dotenv import load_dotenv



# 2. Get the path to the .env file
CONFIG_DIR = Path(__file__).resolve().parent
# Assuming .env is in the project root (two levels up from app/core)
PROJECT_ROOT = CONFIG_DIR.parent.parent
ENV_FILE_PATH = PROJECT_ROOT / '.env'

# Load environment variables from .env file
load_dotenv(ENV_FILE_PATH)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH), 
        env_file_encoding='utf-8', 
        extra='ignore'
    )

   
    DEBUG_MODE: bool = False
   

    GEMINI_API_KEY: str = ""
    GROQ_API_KEY: str = ""
    OPENROUTER_API_KEY: str = ""
   
    
    # Service Specific Limits (Requests Per Minute)
    GEMINI_RPM: int = 15
    GROQ_RPM: int = 60
    OPENROUTER_RPM: int = 20  # Conservative limit for OpenRouter API
    
    # Service Specific Daily Limits
    GEMINI_DAILY_LIMIT: int = 20
    GROQ_DAILY_LIMIT: int = 1000  
    
    # Retry Configuration
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_BASE_DELAY: float = 1.0
    RETRY_MAX_DELAY: float = 60.0
   
    # Pipeline Configuration
    SKILL_COUNT: int = 9
    BATCH_SIZE: int = 3
    
    # Concurrency Configuration
    MAX_CONCURRENT_BATCHES: int = 3
    SOURCE_DISCOVERY_CONCURRENCY: int = 3
    MAX_SOURCES_PER_SKILL: int = 3  # Maximum sources per skill for quality
    MAX_CONCURRENT_QUESTION_GEN: int = 3  # Allow 3 concurrent question generation (matches batch count)
    
    # Performance Optimization
    GEMINI_BATCH_STAGGER_DELAY: float = 0.5  # Delay between concurrent Gemini batch starts (seconds)
    GEMINI_REQUEST_TIMEOUT: int = 30  # Gemini API request timeout (seconds)
    
    # Timeout Configuration (seconds)
    GLOBAL_TIMEOUT_SECONDS: int = 600  # 10 minutes
    
    # Streaming Configuration
    ENABLE_STREAMING: bool = True  # Use async streaming for LLM calls (eliminates timeouts)
    STREAM_CHUNK_TIMEOUT: int = 30  # Timeout per chunk (not total duration)
    
    # Token Management
    SAFE_TOKEN_LIMIT: int = 50000  # Safe input threshold for OpenRouter gpt-oss-120b
    
    # File Upload Limits
    MAX_FILE_SIZE_MB: int = 10  # Maximum resume file size in MB


# Initialize settings and validate API keys
settings = Settings()
