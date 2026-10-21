from typing import Any

import jenkins
import pytest
import requests

from job_enabler.domain.errors import InstanceUnavailableError
from job_enabler.domain.models import JobKind
from job_enabler.infrastructure.jenkins_gateway import PythonJenkinsGateway

FOLDER = "com.cloudbees.hudson.plugins.folder.Folder"
ORG_FOLDER = "jenkins.branch.OrganizationFolder"
MULTIBRANCH = "org.jenkinsci.plugins.workflow.multibranch.WorkflowMultiBranchProject"
PIPELINE = "org.jenkinsci.plugins.workflow.job.WorkflowJob"
FREESTYLE = "hudson.model.FreeStyleProject"


def item(name: str, cls: str, full: str | None = None, **extra: Any) -> dict[str, Any]:
    """Construye el JSON de un elemento de Jenkins; `extra` añade campos como `disabled`."""
    return {"name": name, "fullName": full or name, "_class": cls, "url": f"u/{name}", **extra}


def config_xml(*, disabled: bool | None) -> str:
    """`config.xml` de un Multibranch; Jenkins lo declara como XML 1.1."""
    flag = "" if disabled is None else f"<disabled>{str(disabled).lower()}</disabled>"
    return f"<?xml version='1.1' encoding='UTF-8'?><org.x.Project>{flag}</org.x.Project>"


class FakeClient:
    """Árbol: raíz → [team-a/ (Folder) → [api (Pipeline), web (Multibranch)], batch (Freestyle)]."""

    def __init__(self) -> None:
        self.tree: dict[str, list[dict[str, Any]]] = {
            "": [item("team-a", FOLDER), item("batch", FREESTYLE, buildable=False)],
            "job/team-a": [
                item("api", PIPELINE, "team-a/api", buildable=True),
                # Como el Jenkins corporativo: el Multibranch no expone `disabled` en el JSON.
                item("web", MULTIBRANCH, "team-a/web"),
                item("gitlab", ORG_FOLDER, "team-a/gitlab"),
            ],
            "job/team-a/job/gitlab": [
                item("svc", MULTIBRANCH, "team-a/gitlab/svc", disabled=False)
            ],
        }
        self.configs: dict[str, str] = {"team-a/web": config_xml(disabled=True)}
        self.queries: list[str] = []
        self.config_calls: list[str] = []
        self.calls: list[tuple[str, str]] = []
        self.error: Exception | None = None

    def get_job_config(self, name: str) -> str:
        self.config_calls.append(name)
        if self.error:
            raise self.error
        return self.configs[name]

    def get_info(self, path: str, query: str) -> dict[str, Any]:
        self.queries.append(path)
        if self.error:
            raise self.error
        return {"jobs": self.tree[path]}

    def get_job_info(self, name: str) -> dict[str, Any]:
        if self.error:
            raise self.error
        for children in self.tree.values():
            for child in children:
                if child["fullName"] == name:
                    return child
        raise jenkins.NotFoundException(f"job[{name}] does not exist")

    def enable_job(self, name: str) -> None:
        self.calls.append(("enable", name))

    def disable_job(self, name: str) -> None:
        self.calls.append(("disable", name))


@pytest.fixture
def client() -> FakeClient:
    return FakeClient()


def gateway(client: FakeClient, depth: int = 5) -> PythonJenkinsGateway:
    """Gateway bajo prueba sobre el cliente falso."""
    return PythonJenkinsGateway("dev", client, depth)


def test_list_jobs_walks_folders_and_maps_kinds_and_states(client: FakeClient) -> None:
    jobs = {j.full_name: j for j in gateway(client).list_jobs()}

    assert set(jobs) == {"batch", "team-a/api", "team-a/web", "team-a/gitlab/svc"}
    assert jobs["batch"].kind is JobKind.FREESTYLE and not jobs["batch"].enabled
    assert jobs["team-a/api"].kind is JobKind.PIPELINE and jobs["team-a/api"].enabled
    assert jobs["team-a/web"].kind is JobKind.MULTIBRANCH and not jobs["team-a/web"].enabled
    assert jobs["team-a/gitlab/svc"].enabled
    assert jobs["team-a/api"].name == "api"


def test_multibranch_is_not_entered(client: FakeClient) -> None:
    gateway(client).list_jobs()

    assert not any(path.endswith("web") or path.endswith("svc") for path in client.queries)


def test_folder_depth_limits_the_walk(client: FakeClient) -> None:
    jobs = gateway(client, depth=1).list_jobs()

    assert {j.full_name for j in jobs} == {"batch"}


def test_state_falls_back_to_color_when_nothing_else_is_exposed(client: FakeClient) -> None:
    client.tree[""] = [item("old", "hudson.model.Other", color="disabled")]

    (job,) = gateway(client).list_jobs()

    assert job.enabled is False and job.kind is JobKind.OTHER


def test_get_job_returns_none_when_missing_or_folder(client: FakeClient) -> None:
    client.tree[""] = [item("team-a", FOLDER)]
    assert gateway(client).get_job("nope") is None
    assert gateway(client).get_job("team-a") is None


def test_get_job_returns_state(client: FakeClient) -> None:
    job = gateway(client).get_job("team-a/web")

    assert job is not None and job.kind is JobKind.MULTIBRANCH and not job.enabled


def test_multibranch_without_disabled_in_json_reads_config_xml(client: FakeClient) -> None:
    jobs = {j.full_name: j for j in gateway(client).list_jobs()}

    assert not jobs["team-a/web"].enabled
    # svc ya trae `disabled` y el resto no son Multibranch: solo web necesita config.xml
    assert client.config_calls == ["team-a/web"]


def test_multibranch_config_without_disabled_tag_is_enabled(client: FakeClient) -> None:
    client.configs["team-a/web"] = config_xml(disabled=None)

    job = gateway(client).get_job("team-a/web")

    assert job is not None and job.enabled


def test_get_job_multibranch_uses_config_xml(client: FakeClient) -> None:
    client.configs["team-a/web"] = config_xml(disabled=False)

    job = gateway(client).get_job("team-a/web")

    assert job is not None and job.enabled and client.config_calls == ["team-a/web"]


def test_query_avoids_fetching_config_of_unrelated_jobs(client: FakeClient) -> None:
    jobs = gateway(client).list_jobs("API")

    assert [j.full_name for j in jobs] == ["team-a/api"]
    assert client.config_calls == []


def test_config_error_becomes_instance_unavailable(client: FakeClient) -> None:
    def failing(name: str) -> str:
        raise jenkins.JenkinsException("403")

    client.get_job_config = failing  # type: ignore[method-assign]

    with pytest.raises(InstanceUnavailableError):
        gateway(client).get_job("team-a/web")


def test_set_enabled_calls_enable_or_disable(client: FakeClient) -> None:
    gateway(client).set_enabled("team-a/api", True)
    gateway(client).set_enabled("team-a/api", False)

    assert client.calls == [("enable", "team-a/api"), ("disable", "team-a/api")]


@pytest.mark.parametrize(
    "error", [jenkins.JenkinsException("403"), requests.ConnectionError("refused")]
)
def test_client_errors_become_instance_unavailable(client: FakeClient, error: Exception) -> None:
    client.error = error

    with pytest.raises(InstanceUnavailableError):
        gateway(client).list_jobs()
    with pytest.raises(InstanceUnavailableError):
        gateway(client).get_job("x")
