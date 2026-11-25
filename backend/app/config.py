"""Runtime configuration. All secrets come from the environment — nothing is hardcoded."""
import os


def _required(name: str) -> str:
    value = os.environ.get(name, "")
    if not value:
        raise RuntimeError(f"Missing required environment variable: {name}")
    return value


class Settings:
    def __init__(self) -> None:
        self.database_url = _required("EVAP_DATABASE_URL")
        self.jwt_secret = _required("EVAP_JWT_SECRET")
        if len(self.jwt_secret) < 32:
            raise RuntimeError("EVAP_JWT_SECRET must be at least 32 characters")
        self.runner_token = _required("EVAP_RUNNER_TOKEN")
        self.jwt_ttl_minutes = int(os.environ.get("EVAP_JWT_TTL_MINUTES", "720"))
        # Optional first-start bootstrap admin (only used when the users table is empty).
        self.bootstrap_admin_user = os.environ.get("EVAP_BOOTSTRAP_ADMIN_USER", "")
        self.bootstrap_admin_password = os.environ.get("EVAP_BOOTSTRAP_ADMIN_PASSWORD", "")
        self.max_script_bytes = int(os.environ.get("EVAP_MAX_SCRIPT_BYTES", "200000"))
        self.max_upload_bytes = int(os.environ.get("EVAP_MAX_UPLOAD_BYTES", "5000000"))


_settings: Settings | None = None


def get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
