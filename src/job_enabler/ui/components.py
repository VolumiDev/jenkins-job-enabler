"""Piezas de presentación de la UI. Sin lógica de negocio: solo dan formato a resultados."""

from collections.abc import Mapping, Sequence

import pandas as pd

from job_enabler.domain.models import (
    JobLocation,
    JobStatus,
    OperationResult,
    Outcome,
    PlannedChange,
    SearchReport,
    job_name,
)

STATUS_ICON = {
    JobStatus.ENABLED: "🟢",
    JobStatus.DISABLED: "🔴",
    JobStatus.NOT_FOUND: "—",
    JobStatus.UNAVAILABLE: "⚠️",
}
STATUS_LABEL = {
    JobStatus.ENABLED: "Activo",
    JobStatus.DISABLED: "Inactivo",
    JobStatus.NOT_FOUND: "No existe",
    JobStatus.UNAVAILABLE: "No disponible",
}
OUTCOME_LABEL = {
    Outcome.CHANGED: "✅ Modificado",
    Outcome.UNCHANGED: "⚪ Sin cambios",
    Outcome.FAILED: "❌ Error",
}


def repo_label(locations: Sequence[JobLocation]) -> str:
    """Nombre del repositorio al que pertenecen las ubicaciones (comparten nombre final)."""
    return job_name(locations[0].full_name)


def _cell(locations: Sequence[JobLocation]) -> str:
    """Iconos de estado de una instancia; añade el recuento si hay varios jobs."""
    if not locations:
        return STATUS_ICON[JobStatus.NOT_FOUND]
    icons = "".join(STATUS_ICON[loc.status] for loc in locations)
    return icons if len(locations) == 1 else f"{icons} ({len(locations)})"


def build_matrix(report: SearchReport, instance_names: Mapping[str, str]) -> pd.DataFrame:
    """Una fila por repositorio y una columna por Jenkins consultado."""
    rows = []
    for locations in report.jobs.values():
        row = {"Repositorio": repo_label(locations)}
        for instance_id, name in instance_names.items():
            row[name] = _cell([loc for loc in locations if loc.instance_id == instance_id])
        rows.append(row)
    columns = ["Repositorio", *instance_names.values()]
    return pd.DataFrame(rows, columns=columns)


def results_frame(
    results: Sequence[OperationResult], instance_names: Mapping[str, str]
) -> pd.DataFrame:
    """Tabla con el resultado de cada operación realizada."""
    return pd.DataFrame(
        [
            {
                "Jenkins": instance_names.get(r.instance_id, r.instance_id),
                "Job": r.full_name,
                "Resultado": OUTCOME_LABEL[r.outcome],
                "Estado final": STATUS_LABEL[r.status_after],
                "Detalle": r.message,
            }
            for r in results
        ]
    )


def plan_frame(changes: Sequence[PlannedChange], instance_names: Mapping[str, str]) -> pd.DataFrame:
    """Tabla con los cambios previstos (estado actual, objetivo y si cambia)."""
    return pd.DataFrame(
        [
            {
                "Jenkins": instance_names.get(c.instance_id, c.instance_id),
                "Job": c.full_name,
                "Ahora": STATUS_LABEL[c.current],
                "Después": STATUS_LABEL[c.target],
                "Cambia": "No" if c.is_noop else "Sí",
            }
            for c in changes
        ]
    )
