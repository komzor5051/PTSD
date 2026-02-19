from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BOT_TOKEN: str
    SUPABASE_URL: str
    SUPABASE_KEY: str
    OPENAI_API_KEY: str
    MANAGER_GROUP_CHAT_ID: int

    class Config:
        env_file = ".env"


settings = Settings()
