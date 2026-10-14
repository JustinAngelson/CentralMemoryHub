"""Explicit, fail-fast configuration without credential-bearing error output."""

import re
from urllib.parse import urlsplit

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CMH_", extra="ignore", env_file=None)

    database_url: SecretStr
    public_url: str
    env: str = "dev"
    bootstrap_token: SecretStr = Field(min_length=64)
    allowed_hosts: str = ""
    trusted_proxy_hops: int = Field(default=0, ge=0, le=32)
    embedding_api_key: SecretStr | None = None
    embedding_provider: str = "openai"
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int = Field(default=1536, ge=1)
    embedding_retry_seconds: int = Field(default=60, ge=0)

    @field_validator("embedding_provider")
    @classmethod
    def validate_provider(cls, value):
        if value not in ("openai", "fake"):
            raise ValueError("must be openai or fake")
        return value

    @field_validator("database_url")
    @classmethod
    def validate_database(cls, value: SecretStr) -> SecretStr:
        try:
            url = make_url(value.get_secret_value())
            if url.drivername not in ("postgres", "postgresql", "postgresql+psycopg"):
                raise ValueError
            if not url.database:
                raise ValueError
        except (ArgumentError, TypeError, ValueError):
            raise ValueError("must be a PostgreSQL database URL") from None
        return value

    @field_validator("public_url")
    @classmethod
    def validate_base_url(cls, value: str) -> str:
        try:
            url = urlsplit(value)
            if (
                url.scheme not in ("http", "https")
                or not url.hostname
                or url.username is not None
                or url.password is not None
                or url.path
                or url.query
                or url.fragment
                or url.port == 0
            ):
                raise ValueError
        except ValueError:
            raise ValueError("must be an HTTP(S) base URL with no path or trailing slash") from None
        return value

    @field_validator("env")
    @classmethod
    def validate_environment(cls, value: str) -> str:
        if value not in ("dev", "test", "prod"):
            raise ValueError("must be dev, test, or prod")
        return value

    @field_validator("allowed_hosts")
    @classmethod
    def validate_hosts(cls, value: str) -> str:
        for host in filter(None, (part.strip() for part in value.split(","))):
            if not re.fullmatch(r"[A-Za-z0-9.-]+", host):
                raise ValueError("must contain exact hostnames, without wildcards or URLs")
        return value

    @property
    def mcp_url(self) -> str:
        return self.public_url + "/mcp"


def load_settings() -> Settings:
    try:
        return Settings()
    except ValidationError as error:
        names = sorted({
            "CMH_" + str(item["loc"][0]).upper()
            for item in error.errors(include_input=False, include_context=False)
        })
        raise RuntimeError("Invalid CMH configuration: " + ", ".join(names)) from None
