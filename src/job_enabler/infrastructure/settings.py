import os
from collections.abc import Mapping
from pathlib import Path

import yaml
from dotenv import dotenv_values
from pydantic import BaseModel, Field, SecretStr, ValidationError, field_validator

from job_enabler.domain.errors import ConfigurationError

DEFAULT_CONFIG_PATH = Path("config/jenkins.yaml")
DEFAULT_ENV_PATH = Path(".env")
CONFIG_PATH_VAR = "JOB_ENABLER_CONFIG"


class SearchConfig(BaseModel):
    folder_depth: int = Field(default=5, ge=1, le=20)
    timeout_seconds: int = Field(default=10, ge=1)


class InstanceConfig(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9_]+$")
    name: str
    url: str
    verify_ssl: bool = True


class AppConfig(BaseModel):
    search: SearchConfig = SearchConfig()
    instances: list[InstanceConfig] = Field(min_length=1)

    @field_validator("instances")
    @classmethod
    def _unique_ids(cls, instances: list[InstanceConfig]) -> list[InstanceConfig]:
        ids = [i.id for i in instances]
        duplicated = sorted({i for i in ids if ids.count(i) > 1})
        if duplicated:
            raise ValueError(f"ids de instancia duplicados: {', '.join(duplicated)}")
        return instances


class Credentials(BaseModel):
    user: str
    token: SecretStr


def load_config(path: Path | None = None, environ: Mapping[str, str] | None = None) -> AppConfig:
    environ = os.environ if environ is None else environ
    config_path = path or Path(environ.get(CONFIG_PATH_VAR, DEFAULT_CONFIG_PATH))
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ConfigurationError(f"No se puede leer {config_path}: {exc}") from exc
    except yaml.YAMLError as exc:
        raise ConfigurationError(f"YAML inválido en {config_path}: {exc}") from exc
    try:
        return AppConfig.model_validate(raw)
    except ValidationError as exc:
        raise ConfigurationError(f"Configuración inválida en {config_path}:\n{exc}") from exc


def load_credentials(
    config: AppConfig,
    env_path: Path = DEFAULT_ENV_PATH,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Credentials]:
    """Lee `JENKINS_<ID>_USER` y `JENKINS_<ID>_TOKEN` del .env (el entorno tiene prioridad)."""
    values: dict[str, str | None] = {
        **dotenv_values(env_path),
        **(os.environ if environ is None else environ),
    }
    credentials: dict[str, Credentials] = {}
    missing: list[str] = []
    for instance in config.instances:
        prefix = f"JENKINS_{instance.id.upper()}"
        user, token = values.get(f"{prefix}_USER"), values.get(f"{prefix}_TOKEN")
        if user and token:
            credentials[instance.id] = Credentials(user=user, token=SecretStr(token))
        else:
            missing.extend(
                n for n, v in ((f"{prefix}_USER", user), (f"{prefix}_TOKEN", token)) if not v
            )
    if missing:
        raise ConfigurationError(f"Faltan secretos en el .env: {', '.join(missing)}")
    return credentials
