"""Servicio de aplicación: búsqueda y cambio de estado de jobs en varios Jenkins."""

import getpass
import logging
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor

from job_enabler.domain.errors import (
    InstanceUnavailableError,
    JobEnablerError,
    JobNotFoundError,
    UnknownInstanceError,
)
from job_enabler.domain.models import (
    ExclusivePlan,
    JobInfo,
    JobLocation,
    JobStatus,
    OperationResult,
    Outcome,
    PlannedChange,
    SearchReport,
    job_key,
    job_name,
)
from job_enabler.domain.ports import JenkinsGateway

logger = logging.getLogger(__name__)


def _status(enabled: bool) -> JobStatus:
    """Traduce el booleano de Jenkins al estado de dominio."""
    return JobStatus.ENABLED if enabled else JobStatus.DISABLED


class JobService:
    """Orquesta varios `JenkinsGateway` (uno por instancia, indexados por id).

    Los cambios de estado se registran en el log con el usuario del sistema operativo.
    """

    def __init__(self, gateways: Mapping[str, JenkinsGateway], max_workers: int = 8) -> None:
        self._gateways = gateways
        self._max_workers = max_workers
        self._user = getpass.getuser()

    def search(self, query: str, instance_ids: list[str] | None = None) -> SearchReport:
        """Busca jobs cuyo nombre final contenga `query` (sin distinguir mayúsculas).

        Los resultados se agrupan por nombre de job aunque la ruta de carpetas difiera.
        """
        ids = self._resolve_ids(instance_ids)
        needle = query.casefold()
        listings, failures = self._list_all(ids, query)

        jobs: dict[str, list[JobLocation]] = {}
        for instance_id, found in listings.items():
            for job in found:
                if needle in job.name.casefold():
                    jobs.setdefault(job_key(job.name), []).append(
                        JobLocation(
                            instance_id, job.full_name, _status(job.enabled), job.url, job.kind
                        )
                    )
        return SearchReport(jobs=dict(sorted(jobs.items())), failures=failures)

    def set_state(self, instance_id: str, full_name: str, enabled: bool) -> OperationResult:
        """Activa o desactiva el job en una única ubicación; el resto no se toca."""
        job = self._gateway(instance_id).get_job(full_name)
        if job is None:
            raise JobNotFoundError(instance_id, full_name)
        return self._apply(instance_id, full_name, job.enabled, enabled)

    def preview_exclusive(self, instance_id: str, full_name: str) -> ExclusivePlan:
        """Calcula, sin modificar nada, qué cambiaría `activate_exclusively`.

        Incluye cualquier otro job con el mismo nombre, también dentro del Jenkins destino.
        """
        target = self._gateway(instance_id).get_job(full_name)
        if target is None:
            raise JobNotFoundError(instance_id, full_name)

        changes = [
            PlannedChange(instance_id, full_name, _status(target.enabled), JobStatus.ENABLED)
        ]
        listings, failures = self._list_all(list(self._gateways), job_name(full_name))
        key = job_key(full_name)
        for other_id, found in listings.items():
            for job in found:
                if job_key(job.name) != key or (other_id, job.full_name) == (
                    instance_id,
                    full_name,
                ):
                    continue
                changes.append(
                    PlannedChange(other_id, job.full_name, _status(job.enabled), JobStatus.DISABLED)
                )
        return ExclusivePlan(changes=changes, failures=failures)

    def activate_exclusively(self, instance_id: str, full_name: str) -> list[OperationResult]:
        """Activa el job en `instance_id` y desactiva cualquier otro con el mismo nombre.

        Activa primero el destino y después desactiva el resto. Si el destino no existe,
        aborta sin modificar nada. No hay rollback: cada ubicación informa de su resultado.
        """
        plan = self.preview_exclusive(instance_id, full_name)
        results = [
            self._apply(
                change.instance_id,
                change.full_name,
                current=change.current is JobStatus.ENABLED,
                enabled=change.target is JobStatus.ENABLED,
            )
            for change in plan.changes  # el destino va primero
        ]
        results.extend(
            OperationResult(other_id, full_name, Outcome.FAILED, JobStatus.UNAVAILABLE, reason)
            for other_id, reason in plan.failures.items()
        )
        return results

    def _list_all(
        self, instance_ids: list[str], query: str = ""
    ) -> tuple[dict[str, list[JobInfo]], dict[str, str]]:
        """Lista los jobs de cada instancia en paralelo, filtrados por `query`.

        Devuelve `(listados, fallos)`: una instancia caída aparece en `fallos` con su motivo
        en lugar de abortar la operación.
        """
        with ThreadPoolExecutor(max_workers=self._max_workers) as pool:
            futures = {i: pool.submit(self._gateways[i].list_jobs, query) for i in instance_ids}
        listings: dict[str, list[JobInfo]] = {}
        failures: dict[str, str] = {}
        for instance_id, future in futures.items():
            try:
                listings[instance_id] = future.result()
            except InstanceUnavailableError as exc:
                logger.warning("Listado fallido en %s: %s", instance_id, exc)
                failures[instance_id] = str(exc)
        return listings, failures

    def _apply(
        self, instance_id: str, full_name: str, current: bool, enabled: bool
    ) -> OperationResult:
        """Lleva un job de `current` a `enabled`; es idempotente y no lanza.

        Si ya está en el estado pedido devuelve `UNCHANGED`; si el gateway falla, `FAILED`.
        """
        target = _status(enabled)
        if current == enabled:
            return OperationResult(instance_id, full_name, Outcome.UNCHANGED, target)
        try:
            self._gateways[instance_id].set_enabled(full_name, enabled)
        except JobEnablerError as exc:
            logger.error("No se pudo cambiar %s en %s: %s", full_name, instance_id, exc)
            return OperationResult(
                instance_id, full_name, Outcome.FAILED, _status(current), str(exc)
            )
        logger.info(
            "AUDIT user=%s instance=%s job=%s %s -> %s",
            self._user,
            instance_id,
            full_name,
            _status(current).value,
            target.value,
        )
        return OperationResult(instance_id, full_name, Outcome.CHANGED, target)

    def _gateway(self, instance_id: str) -> JenkinsGateway:
        """Devuelve el gateway de la instancia o lanza `UnknownInstanceError`."""
        try:
            return self._gateways[instance_id]
        except KeyError:
            raise UnknownInstanceError(instance_id) from None

    def _resolve_ids(self, instance_ids: list[str] | None) -> list[str]:
        """`None` significa todas las instancias; valida que las indicadas existan."""
        if instance_ids is None:
            return list(self._gateways)
        for instance_id in instance_ids:
            self._gateway(instance_id)
        return instance_ids
