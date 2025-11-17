from pydantic_settings import BaseSettings, SettingsConfigDict
from pathlib import Path
from dotenv import dotenv_values # 1. Import dotenv_values

# --- Start Diagnostics ---

# 2. Get the path to the .env file
CONFIG_DIR = Path(__file__).resolve().parent
ENV_FILE_PATH = CONFIG_DIR / '.env'


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ENV_FILE_PATH), 
        env_file_encoding='utf-8', 
        extra='ignore'
    )

    APP_NAME: str = "InterviewPrepAPI"
    DEBUG_MODE: bool = False

    GEMINI_API_KEY: str| None = None
    SERPER_API_KEY: str| None = None
    GROQ_API_KEY: str| None = None
    OPENROUTER_API_KEY: str | None = None
    CREWAI_TELEMETRY_OPT_OUT: bool = False

# This is the line that is failing.
# The print statements above will tell us WHY.
settings = Settings()