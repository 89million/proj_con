from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    google_client_id: str
    google_client_secret: str
    google_redirect_uri: str = "http://localhost:8000/auth/callback"
    secret_key: str
    database_url: str = "postgresql+asyncpg://bookclub:bookclub@localhost:5432/bookclub"
    # Wherever this process happens to be listening. Never put this in anything
    # that leaves the building — it is localhost on any dev machine, and
    # notifications go out over Resend and Discord for real even when the app is
    # run locally, so links built from it reach members as dead localhost URLs.
    app_base_url: str = "http://localhost:8000"
    # Where the club actually lives. Every link in an outgoing email or Discord
    # message is built from this one.
    site_url: str = "https://stumblingbookclub.com"
    allowed_emails: str = ""  # comma-separated; empty = allow all (dev only)
    gemini_api_key: str = ""
    notifications_enabled: bool = True
    discord_webhook_url: str = ""
    resend_api_key: str = ""
    resend_from_email: str = "thehereandnow@stumblingbookclub.com"
    # Wall-clock timezone the club actually meets in. Everything is stored as
    # naive UTC and rendered through app.clock — this is the only place the
    # offset is declared.
    club_timezone: str = "America/Los_Angeles"
    # Weeks from "season complete" to the meetup itself — i.e. how long members
    # get to read the winning book. The poll deadline is derived from this
    # rather than the other way around, so the gap between the vote closing and
    # the meeting is deliberate instead of whatever the calendar leaves over.
    meetup_reading_weeks: int = 4
    # How long the scheduling poll stays open, starting when the season closes.
    meetup_poll_days: int = 7
    # Never let the poll close closer than this to the earliest proposed date;
    # a backstop for odd combinations of the two settings above.
    meetup_min_buffer_days: int = 3
    # How many candidate dates to seed, one week apart, from the first eligible
    # meetup_default_day. Each is seeded at each default location.
    meetup_date_options: int = 3
    meetup_default_locations: str = "Monk,Mixed session"
    meetup_default_day: str = "friday"
    meetup_default_time: str = "19:00"
    promotion_count: int = 2
    default_submit_days: int = 7
    default_ranking_days: int = 5
    default_bracket_round_hours: int = 48
    nudge_cooldown_minutes: int = 15
    dev_tools_enabled: bool = False  # gates simulation/seed tools; keep off in prod

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
