from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "mysql+pymysql://root:ak2006@localhost:3306/brandproof"
    jwt_secret: str = "dev-only-change-me"
    jwt_algorithm: str = "HS256"
    token_ttl_minutes: int = 480
    max_upload_mb: int = 20


settings = Settings()
