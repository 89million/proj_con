from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    secret_key: str
    database_url: str = "postgresql+asyncpg://bookclub:bookclub@localhost:5432/bookclub"
    app_base_url: str = "http://localhost:8000"

    @property
    def async_database_url(self) -> str:
        """Ensure the URL uses the asyncpg driver (Railway provides postgresql://)."""
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    class Config:
        env_file = ".env"


settings = Settings()
