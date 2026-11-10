"""Configuration management using Pydantic Settings and YAML."""

from pathlib import Path
from typing import Any, Dict
import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings loaded from environment variables and .env file."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # LLM Provider Configuration (Default: DeepSeek)
    llm_provider: str = Field(default="deepseek", alias="LLM_PROVIDER")
    deepseek_api_key: str = Field(default="", alias="DEEPSEEK_API_KEY")
    deepseek_base_url: str = Field(
        default="https://api.deepseek.com", alias="DEEPSEEK_BASE_URL"
    )
    deepseek_model: str = Field(default="deepseek-chat", alias="DEEPSEEK_MODEL")

    # Optional OpenAI fallback
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4o-mini", alias="OPENAI_MODEL")

    # Web Search Discovery (Supports Tavily, Exa, Brave, and Keyless Free Search)
    search_provider: str = Field(default="auto", alias="SEARCH_PROVIDER")
    tavily_api_key: str = Field(default="", alias="TAVILY_API_KEY")
    exa_api_key: str = Field(default="", alias="EXA_API_KEY")
    brave_api_key: str = Field(default="", alias="BRAVE_API_KEY")
    brave_results_per_query: int = Field(
        default=20, ge=1, le=25, alias="BRAVE_RESULTS_PER_QUERY"
    )
    max_search_queries: int = Field(default=8, ge=1, le=25, alias="MAX_SEARCH_QUERIES")

    # Scraping & Rate Limiting
    http_timeout_seconds: int = Field(
        default=15, ge=3, le=60, alias="HTTP_TIMEOUT_SECONDS"
    )
    max_subpages_per_company: int = Field(
        default=5, ge=1, le=15, alias="MAX_SUBPAGES_PER_COMPANY"
    )
    request_delay_seconds: float = Field(
        default=1.0, ge=0.0, le=10.0, alias="REQUEST_DELAY_SECONDS"
    )
    user_agent: str = Field(
        default="HeidiLeadResearchBot/1.0 (+https://heidisystems.com; B2B Market Research)",
        alias="USER_AGENT",
    )

    # Storage & Persistence
    storage_backend: str = Field(default="json", alias="STORAGE_BACKEND")
    mongodb_uri: str = Field(
        default="mongodb://localhost:27017", alias="MONGODB_URI"
    )
    mongodb_database: str = Field(
        default="heidi_b2b_leads", alias="MONGODB_DATABASE"
    )

    # Paths
    data_dir: Path = Field(default=Path("data"), alias="DATA_DIR")
    cache_dir: Path = Field(default=Path("data/cache"), alias="CACHE_DIR")
    output_dir: Path = Field(default=Path("data/output"), alias="OUTPUT_DIR")
    kpi_config_path: Path = Field(
        default=Path("config/kpi_weights.yaml"), alias="KPI_CONFIG_PATH"
    )

    def ensure_directories(self) -> None:
        """Create required data, cache, and output directories if they don't exist."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.output_dir.mkdir(parents=True, exist_ok=True)

    def load_kpi_config(self) -> Dict[str, Any]:
        """Load KPI weights and discovery rules from the YAML config file."""
        if not self.kpi_config_path.exists():
            raise FileNotFoundError(
                f"KPI configuration file not found at {self.kpi_config_path}"
            )
        with open(self.kpi_config_path, "r", encoding="utf-8") as f:
            return yaml.safe_load(f)


def get_settings() -> Settings:
    """Return a configured Settings instance with directories initialized."""
    settings = Settings()
    settings.ensure_directories()
    return settings
