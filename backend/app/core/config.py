from pydantic import model_validator
from pydantic_settings import BaseSettings

# Sentinel default — anyone running in production with this value can forge JWTs,
# so startup must abort if it is left unchanged outside development.
_DEFAULT_JWT_SECRET = "dev-secret-change-in-production"


class Settings(BaseSettings):
    # Google OAuth
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8000/auth/google/callback"

    # JWT
    jwt_secret: str = _DEFAULT_JWT_SECRET
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
    model_state_save_interval: int = 100   # persist pickled model weights every N bars
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

    @model_validator(mode="after")
    def _enforce_production_secrets(self) -> "Settings":
        """
        Refuse to start in production with forgeable auth.
        A blank or default JWT secret means anyone can mint valid session
        cookies, so we fail fast instead of booting an insecure server.
        """
        if self.env == "production":
            if not self.jwt_secret or self.jwt_secret == _DEFAULT_JWT_SECRET:
                raise ValueError(
                    "JWT_SECRET must be set to a strong, unique value in production. "
                    "It is currently the built-in default, which allows anyone to "
                    "forge session tokens. Set the JWT_SECRET environment variable."
                )
        return self


settings = Settings()
