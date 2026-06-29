from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # JWT
    jwt_secret: str = "dev-secret-change-in-production"
    jwt_expire_hours: int = 24
    jwt_algorithm: str = "HS256"

    # Database
    database_url: str = "postgresql://trademeter:password@localhost:5432/trademeter"

    # Redis
    redis_url: str = "redis://localhost:6379"

    # NinjaTrader TCP
    nt_tcp_host: str = "0.0.0.0"
    nt_tcp_port: int = 5000

    # ML
    mlflow_tracking_uri: str = "http://localhost:5001"
    model_snapshot_interval: int = 100
    drift_accuracy_threshold: float = 0.60

    # Frontend (for OAuth redirect after callback)
    frontend_url: str = "http://localhost:5173"

    # Environment
    env: str = "development"

    model_config = {
        "env_file": [".env", "../.env"],  # backend/.env first, then TradeMeter/.env
        "env_file_encoding": "utf-8",
        "extra": "ignore",
    }


settings = Settings()
