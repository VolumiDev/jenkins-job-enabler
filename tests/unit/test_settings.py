from pathlib import Path

import pytest

from job_enabler.domain.errors import ConfigurationError
from job_enabler.infrastructure.settings import load_config, load_credentials

YAML = """
instances:
  - {id: dev, name: DEV, url: "http://dev"}
  - {id: pro, name: PRO, url: "http://pro"}
"""


def _config(tmp_path: Path, text: str = YAML) -> Path:
    path = tmp_path / "jenkins.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_load_config_applies_defaults(tmp_path: Path) -> None:
    config = load_config(_config(tmp_path), environ={})

    assert [i.id for i in config.instances] == ["dev", "pro"]
    assert config.search.folder_depth == 5
    assert config.instances[0].verify_ssl is True


def test_frequent_apps_default_to_empty(tmp_path: Path) -> None:
    config = load_config(_config(tmp_path), environ={})

    assert config.frequent_apps == []


def test_frequent_apps_are_cleaned_keeping_order(tmp_path: Path) -> None:
    text = YAML + "frequent_apps: [' app-a ', '', app-b, app-a]\n"

    config = load_config(_config(tmp_path, text), environ={})

    assert config.frequent_apps == ["app-a", "app-b"]


def test_config_path_can_come_from_environment(tmp_path: Path) -> None:
    path = _config(tmp_path)

    config = load_config(environ={"JOB_ENABLER_CONFIG": str(path)})

    assert len(config.instances) == 2


def test_missing_file_is_a_configuration_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError):
        load_config(tmp_path / "nope.yaml", environ={})


def test_duplicate_ids_are_rejected(tmp_path: Path) -> None:
    text = "instances:\n  - {id: dev, name: A, url: x}\n  - {id: dev, name: B, url: y}\n"

    with pytest.raises(ConfigurationError, match="duplicados"):
        load_config(_config(tmp_path, text), environ={})


def test_credentials_come_from_dotenv_and_stay_secret(tmp_path: Path) -> None:
    config = load_config(_config(tmp_path), environ={})
    env = tmp_path / ".env"
    env.write_text(
        "JENKINS_DEV_USER=ana\nJENKINS_DEV_TOKEN=s3cret\n"
        "JENKINS_PRO_USER=bob\nJENKINS_PRO_TOKEN=t0ken\n",
        encoding="utf-8",
    )

    credentials = load_credentials(config, env_path=env, environ={})

    assert credentials["dev"].user == "ana"
    assert credentials["dev"].token.get_secret_value() == "s3cret"
    assert "s3cret" not in repr(credentials["dev"])


def test_environment_overrides_dotenv(tmp_path: Path) -> None:
    config = load_config(_config(tmp_path), environ={})
    env = tmp_path / ".env"
    env.write_text(
        "JENKINS_DEV_USER=a\nJENKINS_DEV_TOKEN=b\nJENKINS_PRO_USER=c\nJENKINS_PRO_TOKEN=d\n"
    )

    credentials = load_credentials(config, env_path=env, environ={"JENKINS_DEV_USER": "override"})

    assert credentials["dev"].user == "override"


def test_missing_secrets_are_listed(tmp_path: Path) -> None:
    config = load_config(_config(tmp_path), environ={})
    env = tmp_path / ".env"
    env.write_text("JENKINS_DEV_USER=a\n", encoding="utf-8")

    with pytest.raises(ConfigurationError) as excinfo:
        load_credentials(config, env_path=env, environ={})

    message = str(excinfo.value)
    assert "JENKINS_DEV_TOKEN" in message
    assert "JENKINS_PRO_USER" in message and "JENKINS_PRO_TOKEN" in message
