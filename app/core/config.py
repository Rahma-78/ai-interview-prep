from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from dotenv import dotenv_values, load_dotenv

# --- Start Diagnostics ---

# 2. Get the path to the .env file
CONFIG_DIR = Path(__file__).resolve().parent
ENV_FILE_PATH = CONFIG_DIR / '.env'

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
    HF_API_KEY: str = ""
    CREWAI_TELEMETRY_OPT_OUT: bool = True
    REQUESTS_PER_MINUTE: int = 10
    
    # Service Specific Limits (Requests Per Minute)
    GEMINI_RPM: int = 15
    OPENROUTER_RPM: int = 20
    GROQ_RPM: int = 30
    
    # Agent Configuration
    AGENT_MAX_ITER: int = 3
    AGENT_MAX_RPM: int = 15
    
    # Retry Configuration
    RETRY_MAX_ATTEMPTS: int = 3
    RETRY_BASE_DELAY: float = 1.0
    RETRY_MAX_DELAY: float = 60.0
    RETRY_MIN_QUOTA_DELAY: float = 30.0
    
    # Fail-Fast Configuration (for user-facing or latency-sensitive operations)
    RETRY_FAIL_FAST_MAX_RETRIES: int = 1
    RETRY_FAIL_FAST_MAX_DELAY: float = 5.0
    RETRY_FAIL_FAST_MIN_QUOTA_DELAY: float = 3.0
    
    # Logging
    LOG_LEVEL_UTILS: str = "INFO"
    

# Initialize settings and validate API keys
settings = Settings()
