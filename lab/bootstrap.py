"""Gestiona el laboratorio de Jenkins.

uv run python -m lab.bootstrap up      # genera lab/.env, levanta Docker, crea tokens y resetea
uv run python -m lab.bootstrap reset   # vuelve a dejar el estado inicial de los jobs
uv run python -m lab.bootstrap down    # para los contenedores (los datos se conservan)
"""

import argparse
import secrets
import subprocess
import sys
import time
from pathlib import Path

import jenkins
import requests
from dotenv import dotenv_values

from job_enabler.infrastructure.jenkins_gateway import PythonJenkinsGateway
from lab.scenario import INITIAL_STATE, PORTS

ROOT = Path(__file__).resolve().parent.parent
LAB_DIR = ROOT / "lab"
LAB_ENV = LAB_DIR / ".env"
APP_ENV = ROOT / ".env"
ADMIN_USER = "admin"
TOKEN_NAME = "job-enabler"  # noqa: S105 (nombre del token, no un secreto)
READY_TIMEOUT_SECONDS = 300


def url_of(instance_id: str) -> str:
    return f"http://localhost:{PORTS[instance_id]}"


def upsert_env(path: Path, values: dict[str, str]) -> None:
    """Escribe/actualiza claves en un .env conservando el resto de líneas."""
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    pending = dict(values)
    for index, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in pending:
            lines[index] = f"{key}={pending.pop(key)}"
    lines.extend(f"{key}={value}" for key, value in pending.items())
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_lab_env() -> dict[str, str]:
    values = {k: v for k, v in dotenv_values(LAB_ENV).items() if v}
    missing = {
        f"{i.upper()}_ADMIN_PASSWORD": secrets.token_urlsafe(18)
        for i in PORTS
        if f"{i.upper()}_ADMIN_PASSWORD" not in values
    }
    if missing:
        upsert_env(LAB_ENV, missing)
        values.update(missing)
    return values


def compose(*args: str) -> None:
    subprocess.run(  # noqa: S603
        ["docker", "compose", "-f", str(LAB_DIR / "docker-compose.yml"), *args],  # noqa: S607
        check=True,
        cwd=LAB_DIR,
    )


def wait_ready(instance_id: str, password: str) -> None:
    deadline = time.monotonic() + READY_TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        try:
            response = requests.get(
                f"{url_of(instance_id)}/api/json", auth=(ADMIN_USER, password), timeout=5
            )
            if response.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(3)
    sys.exit(f"Jenkins {instance_id} no arrancó en {READY_TIMEOUT_SECONDS}s")


def token_works(instance_id: str, token: str) -> bool:
    try:
        response = requests.get(
            f"{url_of(instance_id)}/api/json", auth=(ADMIN_USER, token), timeout=5
        )
    except requests.RequestException:
        return False
    return response.status_code == 200


def create_token(instance_id: str, password: str) -> str:
    """Crea un API token por REST (la sesión debe conservar la cookie para el crumb)."""
    base = url_of(instance_id)
    with requests.Session() as session:
        session.auth = (ADMIN_USER, password)
        crumb = session.get(f"{base}/crumbIssuer/api/json", timeout=10).json()
        response = session.post(
            f"{base}/user/{ADMIN_USER}/descriptorByName/"
            "jenkins.security.ApiTokenProperty/generateNewToken",
            data={"newTokenName": TOKEN_NAME},
            headers={crumb["crumbRequestField"]: crumb["crumb"]},
            timeout=10,
        )
        response.raise_for_status()
        return str(response.json()["data"]["tokenValue"])


def ensure_tokens(lab_env: dict[str, str]) -> None:
    app_env = {k: v for k, v in dotenv_values(APP_ENV).items() if v}
    updates: dict[str, str] = {}
    for instance_id in PORTS:
        key = f"JENKINS_{instance_id.upper()}_TOKEN"
        wait_ready(instance_id, lab_env[f"{instance_id.upper()}_ADMIN_PASSWORD"])
        if key in app_env and token_works(instance_id, app_env[key]):
            continue
        password = lab_env[f"{instance_id.upper()}_ADMIN_PASSWORD"]
        updates[key] = create_token(instance_id, password)
        updates[f"JENKINS_{instance_id.upper()}_USER"] = ADMIN_USER
    if updates:
        upsert_env(APP_ENV, updates)
        print(f"Tokens escritos en {APP_ENV}")


def reset_state() -> None:
    app_env = dotenv_values(APP_ENV)
    for instance_id, jobs in INITIAL_STATE.items():
        client = jenkins.Jenkins(
            url_of(instance_id),
            username=app_env[f"JENKINS_{instance_id.upper()}_USER"],
            password=app_env[f"JENKINS_{instance_id.upper()}_TOKEN"],
            timeout=15,
        )
        gateway = PythonJenkinsGateway(instance_id, client, folder_depth=5)
        for full_name, enabled in jobs.items():
            gateway.set_enabled(full_name, enabled)
        print(f"{instance_id}: estado inicial restaurado ({len(jobs)} jobs)")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["up", "reset", "down"])
    command = parser.parse_args().command

    if command == "down":
        compose("down")
        return
    if command == "up":
        lab_env = ensure_lab_env()
        compose("up", "-d", "--build")
        ensure_tokens(lab_env)
    reset_state()


if __name__ == "__main__":
    main()
