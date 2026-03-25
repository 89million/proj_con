from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    secret_key: str
    database_url: str = "postgresql+asyncpg://bookclub:bookclub@localhost:5432/bookclub"
    app_base_url: str = "http://localhost:8000"
    allowed_emails: str = ""  # comma-separated; empty = allow all (dev only)
    gemini_api_key: str = ""
    notifications_enabled: bool = True
    discord_webhook_url: str = ""
    resend_api_key: str = ""
    resend_from_email: str = "thehereandnow@stumblingbookclub.com"

    def is_email_allowed(self, email: str) -> bool:
        if not self.allowed_emails.strip():
            return True
        allowed = {e.strip().lower() for e in self.allowed_emails.split(",")}
        return email.lower() in allowed

    @property
    def async_database_url(self) -> str:
        """Ensure the URL uses the asyncpg driver (Railway provides postgresql://)."""
        return self.database_url.replace("postgresql://", "postgresql+asyncpg://", 1)

    class Config:
        env_file = ".env"


settings = Settings()
