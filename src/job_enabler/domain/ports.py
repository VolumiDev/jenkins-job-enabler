"""Puertos que el dominio exige a la infraestructura."""

from typing import Protocol

from job_enabler.domain.models import JobInfo


class JenkinsGateway(Protocol):
    """Acceso a un único Jenkins. Lanza InstanceUnavailableError si no responde."""

    def list_jobs(self, query: str = "") -> list[JobInfo]:
        """Lista los jobs de la instancia; un Multibranch cuenta como un único job.

        `query` filtra por subcadena del nombre final, sin distinguir mayúsculas.
        """
        ...

    def get_job(self, full_name: str) -> JobInfo | None:
        """Devuelve None si el job no existe."""
        ...

    def set_enabled(self, full_name: str, enabled: bool) -> None:
        """Activa o desactiva el job indicado."""
        ...
