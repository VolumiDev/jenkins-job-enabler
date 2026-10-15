"""Modelos de dominio: enums y dataclasses inmutables que intercambian las capas."""

from dataclasses import dataclass
from enum import StrEnum


class JobStatus(StrEnum):
    """Estado de un job en una ubicación; `NOT_FOUND` y `UNAVAILABLE` se usan al presentar."""

    ENABLED = "enabled"
    DISABLED = "disabled"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class JobKind(StrEnum):
    """Tipo de job de Jenkins que nos interesa distinguir."""

    FREESTYLE = "freestyle"
    PIPELINE = "pipeline"
    MULTIBRANCH = "multibranch"
    OTHER = "other"


class Outcome(StrEnum):
    """Resultado de intentar cambiar el estado de un job."""

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
    """Un Jenkins configurado: identificador corto, nombre visible y URL base."""

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
        """Nombre final del job, sin la ruta de carpetas."""
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
    """Cambio previsto para un job: estado actual y estado objetivo."""

    instance_id: str
    full_name: str
    current: JobStatus
    target: JobStatus

    @property
    def is_noop(self) -> bool:
        """Indica si el job ya está en el estado objetivo (no habrá modificación)."""
        return self.current == self.target


@dataclass(frozen=True, slots=True)
class ExclusivePlan:
    """Qué haría una activación exclusiva, y qué instancias no se pudieron consultar."""

    changes: list[PlannedChange]
    failures: dict[str, str]


@dataclass(frozen=True, slots=True)
class OperationResult:
    """Resultado de operar sobre un job; `message` recoge el motivo si falló."""

    instance_id: str
    full_name: str
    outcome: Outcome
    status_after: JobStatus
    message: str = ""
