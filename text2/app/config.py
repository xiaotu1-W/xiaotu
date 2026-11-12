from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./oj.db"
    jwt_secret: str = "local-development-secret-change-me"
    jwt_expire_minutes: int = 1440
    runner_timeout_seconds: int = 3
    runner_memory_mb: int = 128
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
