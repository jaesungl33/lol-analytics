"""Central configuration.

Everything that might change between your laptop, a teammate's laptop, and
production lives here and is read from environment variables (or a .env file).
Hardcoding these values into the code is the #1 thing that makes a project
impossible to deploy, so we pull them out from day one.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # Data source
    use_fixtures: bool = True
    hardcoded_riot_id: str = "SamplePlayer#NA1"

    # Riot API (only used when use_fixtures is False)
    riot_api_key: str = ""
    riot_region: str = "americas"

    # Database
    database_url: str = "postgresql+psycopg2://lol:lol@localhost:5432/lol"

    # --- Milestone 2: rate limiting, retries, caching -----------------------
    # Riot dev-key defaults: 20 requests / 1s (burst) and 100 / 2 minutes.
    rate_limit_per_second: int = 20
    rate_limit_per_two_min: int = 100
    rate_limit_window_seconds: int = 120

    # 429 back-off: wait Retry-After if Riot sends it, else base * 2**attempt
    # capped at backoff_cap_seconds, for at most http_max_retries extra tries.
    http_max_retries: int = 3
    backoff_base_seconds: float = 0.5
    backoff_cap_seconds: float = 8.0

    # How long cached account look-ups and computed stats stay fresh.
    cache_ttl_seconds: int = 300

    # --- Milestone 3: LLM coaching ------------------------------------------
    # "stub" (default, offline, no key) or "openai" (real, needs a key).
    coach_provider: str = "stub"
    openai_api_key: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    coach_model: str = "gpt-4o-mini"


# A single shared instance the rest of the app imports.
settings = Settings()
