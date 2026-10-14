from collections.abc import Callable
from typing import Any, TypeVar

import jenkins
import requests

from job_enabler.domain.errors import InstanceUnavailableError
from job_enabler.domain.models import JobInfo, JobKind

T = TypeVar("T")

_JOB_FIELDS = "name,fullName,url,color,_class,buildable,disabled"
_CHILDREN_QUERY = f"?tree=jobs[{_JOB_FIELDS}]"

# Contenedores que se recorren por dentro (los grupos de GitLab son OrganizationFolder).
_FOLDER_CLASSES = ("cloudbees.hudson.plugins.folder.Folder", "jenkins.branch.OrganizationFolder")
_KINDS = (
    ("WorkflowMultiBranchProject", JobKind.MULTIBRANCH),
    ("WorkflowJob", JobKind.PIPELINE),
    ("FreeStyleProject", JobKind.FREESTYLE),
)


def _is_folder(raw: dict[str, Any]) -> bool:
    return any(str(raw.get("_class", "")).endswith(c) for c in _FOLDER_CLASSES)


def _kind_of(raw: dict[str, Any]) -> JobKind:
    job_class = str(raw.get("_class", ""))
    return next((kind for suffix, kind in _KINDS if job_class.endswith(suffix)), JobKind.OTHER)


def _is_enabled(raw: dict[str, Any]) -> bool:
    """`disabled` si Jenkins lo expone; si no, `buildable`; en último caso el color."""
    if "disabled" in raw:
        return not raw["disabled"]
    if "buildable" in raw:
        return bool(raw["buildable"])
    return not str(raw.get("color", "")).startswith("disabled")


def _to_job(raw: dict[str, Any], full_name: str) -> JobInfo:
    return JobInfo(full_name, raw.get("url", ""), _is_enabled(raw), _kind_of(raw))


def _item_path(full_name: str) -> str:
    """'a/b' -> 'job/a/job/b' (ruta de la API de Jenkins)."""
    return "/".join(f"job/{segment}" for segment in full_name.split("/"))


class PythonJenkinsGateway:
    """Adaptador de `python-jenkins` al puerto `JenkinsGateway`."""

    def __init__(self, instance_id: str, client: jenkins.Jenkins, folder_depth: int) -> None:
        self._instance_id = instance_id
        self._client = client
        self._folder_depth = folder_depth

    def list_jobs(self) -> list[JobInfo]:
        """Recorre las carpetas por niveles.

        No se usa `get_all_jobs`: entraría en los Multibranch y devolvería cada rama
        como si fuera un job. Aquí un Multibranch cuenta como un único job.
        """
        found: list[JobInfo] = []
        pending: list[tuple[str, int]] = [("", 1)]  # (ruta de carpeta, nivel)
        while pending:
            folder, level = pending.pop()
            for raw in self._children(folder):
                full_name = raw.get("fullName") or "/".join(filter(None, (folder, raw["name"])))
                if _is_folder(raw):
                    if level < self._folder_depth:
                        pending.append((full_name, level + 1))
                else:
                    found.append(_to_job(raw, full_name))
        return found

    def get_job(self, full_name: str) -> JobInfo | None:
        try:
            raw = self._call(self._client.get_job_info, full_name)
        except jenkins.NotFoundException:
            return None
        if _is_folder(raw):
            return None
        return _to_job(raw, full_name)

    def set_enabled(self, full_name: str, enabled: bool) -> None:
        action = self._client.enable_job if enabled else self._client.disable_job
        self._call(action, full_name)

    def _children(self, folder: str) -> list[dict[str, Any]]:
        info = self._call(
            self._client.get_info, _item_path(folder) if folder else "", _CHILDREN_QUERY
        )
        children: list[dict[str, Any]] = info.get("jobs", [])
        return children

    def _call(self, func: Callable[..., T], *args: Any) -> T:
        try:
            return func(*args)
        except jenkins.NotFoundException:
            raise
        except (jenkins.JenkinsException, requests.RequestException) as exc:
            raise InstanceUnavailableError(self._instance_id, str(exc)) from exc
