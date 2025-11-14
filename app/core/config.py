from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file='.env', extra='ignore')

    # Example setting
    APP_NAME: str = "InterviewPrepAPI"
    DEBUG_MODE: bool = False

    # API Keys (these would typically be loaded from .env)
    GEMINI_API_KEY: str | None = None
    SERPER_API_KEY: str | None = None
    GROQ_API_KEY: str | None = None
    OPENROUTER_API_KEY: str | None = None
    OPENAI_API_KEY: str | None = None
    CREWAI_TELEMETRY_OPT_OUT: bool = False

settings = Settings()
