"""Application configuration using Pydantic Settings."""
from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings loaded from environment variables."""

    # Application
    app_name: str = "PLM System v2"
    app_version: str = "0.2.0"
    debug: bool = True

    # Database
    database_url: str = "sqlite+aiosqlite:///./plm.db"

    # Redis
    redis_url: str = "redis://:plm@localhost:6379/0"

    # File storage
    upload_dir: str = "/app/storage/uploads"
    gltf_dir: str = "/app/storage/gltf"
    max_upload_size: int = 100 * 1024 * 1024  # 100MB
    allowed_extensions: list[str] = [".step", ".stp", ".catia", ".catpart", ".catproduct", ".iges", ".igs"]

    # 3D Conversion
    conversion_timeout: int = 300  # 5 minutes max
    mesh_quality: float = 0.1  # Linear deflection for meshing (lower = better quality)

    # Security
    secret_key: str = "dev-secret-key-change-in-production"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 15
    refresh_token_expire_days: int = 7

    # Admin setup
    admin_registration_code: str = "CHANGE-THIS-ADMIN-CODE-IN-PRODUCTION"

    # Email/SMTP settings
    smtp_enabled: bool = False
    smtp_host: str = "smtp.example.com"
    smtp_port: int = 587
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_use_tls: bool = True
    smtp_from_email: str = "noreply@example.com"

    # Frontend URL for email links
    frontend_url: str = "http://localhost:5173"

    # Password reset settings
    password_reset_expire_hours: int = 24

    # Account lockout settings
    max_login_attempts: int = 5
    lockout_duration_minutes: int = 30

    # Notification settings
    notification_task_assigned: bool = True
    notification_task_completed: bool = True
    notification_escalation: bool = True
    notification_workflow_complete: bool = True

    class Config:
        env_file = ".env"
        env_file_encoding = "utf-8"


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
