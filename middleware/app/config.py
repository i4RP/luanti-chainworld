from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """ChainWorld middleware configuration."""

    # Database
    database_url: str = "sqlite+aiosqlite:///chainworld.db"

    # Blockchain
    chain_rpc_url: str = "http://127.0.0.1:8545"
    chain_id: int = 31337
    contract_address: str = ""
    private_key: str = ""

    # Middleware
    batch_commit_interval: int = 30
    max_batch_size: int = 500

    # CORS
    cors_origins: list[str] = ["*"]

    model_config = {"env_prefix": "CHAINWORLD_", "env_file": ".env"}


settings = Settings()
