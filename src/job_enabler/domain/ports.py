from typing import Protocol

from job_enabler.domain.models import JobInfo


class JenkinsGateway(Protocol):
    """Acceso a un único Jenkins. Lanza InstanceUnavailableError si no responde."""

    def list_jobs(self) -> list[JobInfo]: ...

    def get_job(self, full_name: str) -> JobInfo | None:
        """Devuelve None si el job no existe."""
        ...

    def set_enabled(self, full_name: str, enabled: bool) -> None: ...
