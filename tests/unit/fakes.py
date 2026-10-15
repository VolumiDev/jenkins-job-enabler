"""Dobles de prueba en memoria para el puerto `JenkinsGateway`."""

from typing import ClassVar

from job_enabler.domain.errors import InstanceUnavailableError
from job_enabler.domain.models import JobInfo


class FakeGateway:
    """Gateway en memoria; con `down=True` toda operación lanza `InstanceUnavailableError`."""

    # Diario compartido entre gateways: (instance_id, full_name, enabled) en orden de escritura.
    journal: ClassVar[list[tuple[str, str, bool]]] = []

    def __init__(self, instance_id: str, jobs: dict[str, bool], *, down: bool = False) -> None:
        self.instance_id = instance_id
        self.jobs = dict(jobs)  # full_name -> enabled
        self.down = down
        self.writes: list[tuple[str, bool]] = []

    def _check(self) -> None:
        if self.down:
            raise InstanceUnavailableError(self.instance_id, "caído")

    def list_jobs(self) -> list[JobInfo]:
        self._check()
        return [JobInfo(n, f"http://{self.instance_id}/job/{n}", e) for n, e in self.jobs.items()]

    def get_job(self, full_name: str) -> JobInfo | None:
        self._check()
        if full_name not in self.jobs:
            return None
        url = f"http://{self.instance_id}/job/{full_name}"
        return JobInfo(full_name, url, self.jobs[full_name])

    def set_enabled(self, full_name: str, enabled: bool) -> None:
        self._check()
        self.jobs[full_name] = enabled
        self.writes.append((full_name, enabled))
        FakeGateway.journal.append((self.instance_id, full_name, enabled))
