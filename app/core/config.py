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
    CREWAI_TELEMETRY_OPT_OUT: bool = True
    REQUESTS_PER_MINUTE: int = 10
    

# Initialize settings and validate API keys
settings = Settings()
