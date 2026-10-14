from dataclasses import dataclass
from enum import StrEnum


class JobStatus(StrEnum):
    ENABLED = "enabled"
    DISABLED = "disabled"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class JobKind(StrEnum):
    FREESTYLE = "freestyle"
    PIPELINE = "pipeline"
    MULTIBRANCH = "multibranch"
    OTHER = "other"


class Outcome(StrEnum):
    CHANGED = "changed"
    UNCHANGED = "unchanged"
    FAILED = "failed"


def job_name(full_name: str) -> str:
    """Último segmento de la ruta: coincide con el nombre del repositorio."""
    return full_name.rsplit("/", 1)[-1]


def job_key(name: str) -> str:
    """Clave de comparación de nombres entre Jenkins (sin distinguir mayúsculas)."""
    return job_name(name).casefold()


@dataclass(frozen=True, slots=True)
class JenkinsInstance:
    id: str
    name: str
    url: str


@dataclass(frozen=True, slots=True)
class JobInfo:
    """Job tal y como lo expone un Jenkins concreto."""

    full_name: str
    url: str
    enabled: bool
    kind: JobKind = JobKind.OTHER

    @property
    def name(self) -> str:
        return job_name(self.full_name)


@dataclass(frozen=True, slots=True)
class JobLocation:
    """Una ubicación concreta (instancia + ruta) de un job y su estado."""

    instance_id: str
    full_name: str
    status: JobStatus
    url: str = ""
    kind: JobKind = JobKind.OTHER


@dataclass(frozen=True, slots=True)
class SearchReport:
    """Resultado de una búsqueda.

    `jobs` se indexa por `job_key` y puede tener varias ubicaciones por instancia.
    """

    jobs: dict[str, list[JobLocation]]
    failures: dict[str, str]


@dataclass(frozen=True, slots=True)
class PlannedChange:
    instance_id: str
    full_name: str
    current: JobStatus
    target: JobStatus

    @property
    def is_noop(self) -> bool:
        return self.current == self.target


@dataclass(frozen=True, slots=True)
class ExclusivePlan:
    """Qué haría una activación exclusiva, y qué instancias no se pudieron consultar."""

    changes: list[PlannedChange]
    failures: dict[str, str]


@dataclass(frozen=True, slots=True)
class OperationResult:
    instance_id: str
    full_name: str
    outcome: Outcome
    status_after: JobStatus
    message: str = ""
