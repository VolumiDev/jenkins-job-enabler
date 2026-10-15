"""Adaptador del puerto `JenkinsGateway` sobre la librería `python-jenkins`."""

import re
from collections.abc import Callable
from typing import Any, TypeVar
from xml.etree import ElementTree

import jenkins
import requests

from job_enabler.domain.errors import InstanceUnavailableError
from job_enabler.domain.models import JobInfo, JobKind, job_name

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
    """Indica si el elemento es un contenedor que se recorre, no un job."""
    return any(str(raw.get("_class", "")).endswith(c) for c in _FOLDER_CLASSES)


def _kind_of(raw: dict[str, Any]) -> JobKind:
    """Deduce el tipo de job por el sufijo de su `_class`."""
    job_class = str(raw.get("_class", ""))
    return next((kind for suffix, kind in _KINDS if job_class.endswith(suffix)), JobKind.OTHER)


def _is_enabled(raw: dict[str, Any]) -> bool | None:
    """`disabled` si Jenkins lo expone; si no, `buildable`; en último caso el color.

    Devuelve None si el JSON no basta para saberlo: un Multibranch es una carpeta y, según
    la versión de branch-api, no expone `disabled` ni `buildable` ni un color fiable.
    """
    if "disabled" in raw:
        return not raw["disabled"]
    if _kind_of(raw) is JobKind.MULTIBRANCH:
        return None
    if "buildable" in raw:
        return bool(raw["buildable"])
    return not str(raw.get("color", "")).startswith("disabled")


def _disabled_from_config(xml: str) -> bool:
    """Lee `<disabled>` del elemento raíz de un `config.xml`; si falta, está habilitado."""
    # Jenkins declara XML 1.1, que expat no admite.
    body = re.sub(r"^\s*<\?xml[^>]*\?>", "", xml)
    root = ElementTree.fromstring(body)  # noqa: S314 - XML de nuestro propio Jenkins
    return (root.findtext("disabled") or "").strip().lower() == "true"


def _item_path(full_name: str) -> str:
    """'a/b' -> 'job/a/job/b' (ruta de la API de Jenkins)."""
    return "/".join(f"job/{segment}" for segment in full_name.split("/"))


class PythonJenkinsGateway:
    """Adaptador de `python-jenkins` al puerto `JenkinsGateway`."""

    def __init__(self, instance_id: str, client: jenkins.Jenkins, folder_depth: int) -> None:
        self._instance_id = instance_id
        self._client = client
        self._folder_depth = folder_depth

    def list_jobs(self, query: str = "") -> list[JobInfo]:
        """Recorre las carpetas por niveles.

        No se usa `get_all_jobs`: entraría en los Multibranch y devolvería cada rama
        como si fuera un job. Aquí un Multibranch cuenta como un único job.

        Si `query` no está vacío solo se devuelven los jobs cuyo nombre final lo contiene;
        así el `config.xml` de un Multibranch solo se pide para los candidatos.
        """
        needle = query.casefold()
        found: list[JobInfo] = []
        pending: list[tuple[str, int]] = [("", 1)]  # (ruta de carpeta, nivel)
        while pending:
            folder, level = pending.pop()
            for raw in self._children(folder):
                full_name = raw.get("fullName") or "/".join(filter(None, (folder, raw["name"])))
                if _is_folder(raw):
                    if level < self._folder_depth:
                        pending.append((full_name, level + 1))
                elif needle in job_name(full_name).casefold():
                    found.append(self._to_job(raw, full_name))
        return found

    def get_job(self, full_name: str) -> JobInfo | None:
        """Devuelve el job, o None si no existe o la ruta apunta a una carpeta."""
        try:
            raw = self._call(self._client.get_job_info, full_name)
        except jenkins.NotFoundException:
            return None
        if _is_folder(raw):
            return None
        return self._to_job(raw, full_name)

    def _to_job(self, raw: dict[str, Any], full_name: str) -> JobInfo:
        """Convierte la respuesta JSON en un `JobInfo`; consulta `config.xml` si hace falta."""
        enabled = _is_enabled(raw)
        if enabled is None:
            enabled = not _disabled_from_config(self._call(self._client.get_job_config, full_name))
        return JobInfo(full_name, raw.get("url", ""), enabled, _kind_of(raw))

    def set_enabled(self, full_name: str, enabled: bool) -> None:
        """Activa o desactiva el job mediante la API de Jenkins."""
        action = self._client.enable_job if enabled else self._client.disable_job
        self._call(action, full_name)

    def _children(self, folder: str) -> list[dict[str, Any]]:
        """Hijos directos de una carpeta (la raíz si `folder` está vacío)."""
        info = self._call(
            self._client.get_info, _item_path(folder) if folder else "", _CHILDREN_QUERY
        )
        children: list[dict[str, Any]] = info.get("jobs", [])
        return children

    def _call(self, func: Callable[..., T], *args: Any) -> T:
        """Ejecuta una llamada al cliente traduciendo sus errores.

        `NotFoundException` se propaga tal cual; el resto de fallos de Jenkins o de red
        se convierten en `InstanceUnavailableError`.
        """
        try:
            return func(*args)
        except jenkins.NotFoundException:
            raise
        except (jenkins.JenkinsException, requests.RequestException) as exc:
            raise InstanceUnavailableError(self._instance_id, str(exc)) from exc
