from pydantic_settings import BaseSettings
from pydantic import Field
from pathlib import Path


class Settings(BaseSettings):
    # API Keys
    openai_api_key: str = Field(default="", alias="OPENAI_API_KEY")
    stability_api_key: str = Field(default="", alias="STABILITY_API_KEY")

    # Provider
    default_provider: str = Field(default="openai", alias="DEFAULT_PROVIDER")

    # Paths
    output_dir: Path = Field(default=Path("outputs"), alias="OUTPUT_DIR")
    presets_dir: Path = Field(default=Path("presets"), alias="PRESETS_DIR")

    # Image settings
    canvas_size: int = Field(default=1024, alias="CANVAS_SIZE")

    # Generation settings
    max_workers: int = Field(default=4, alias="MAX_WORKERS")
    max_retries: int = Field(default=3, alias="MAX_RETRIES")

    # Logging
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")

    model_config = {"env_file": ".env", "extra": "ignore", "populate_by_name": True}


settings = Settings()
