"""Interfaz Streamlit. Arranque: uv run streamlit run src/job_enabler/ui/app.py"""

import logging

import streamlit as st
import truststore

from job_enabler.application.job_service import JobService
from job_enabler.domain.errors import JobEnablerError
from job_enabler.domain.models import JobLocation, JobStatus, OperationResult, SearchReport
from job_enabler.infrastructure.gateway_factory import build_service
from job_enabler.infrastructure.settings import AppConfig
from job_enabler.ui.components import (
    build_matrix,
    plan_frame,
    repo_label,
    results_frame,
)

MIN_QUERY_LENGTH = 2
FLASH = "flash"

logging.basicConfig(level=logging.INFO)

# Usa el almacén de certificados del sistema (en Windows incluye las CA corporativas).
truststore.inject_into_ssl()


@st.cache_resource
def _bootstrap() -> tuple[JobService, AppConfig]:
    """Construye servicio y configuración una sola vez por proceso de Streamlit."""
    return build_service()


@st.cache_data(ttl=60, show_spinner="Consultando Jenkins…")
def _search(_service: JobService, query: str, instance_ids: tuple[str, ...]) -> SearchReport:
    """Búsqueda cacheada 60 s; `_service` lleva guion bajo para que Streamlit no lo hashee."""
    return _service.search(query, list(instance_ids))


def _names() -> dict[str, str]:
    """Mapa `id de instancia -> nombre visible`."""
    _, config = _bootstrap()
    return {i.id: i.name for i in config.instances}


def _flash_results(results: list[OperationResult]) -> None:
    """Guarda los resultados para mostrarlos tras el rerun, e invalida la caché de búsqueda."""
    st.session_state[FLASH] = ("results", results)
    _search.clear()
    st.rerun()


def _flash_error(message: str) -> None:
    """Guarda un error para mostrarlo tras el rerun."""
    st.session_state[FLASH] = ("error", message)
    st.rerun()


def _show_flash() -> None:
    """Muestra (y consume) el mensaje guardado por `_flash_results` o `_flash_error`."""
    kind, payload = st.session_state.pop(FLASH, (None, None))
    if kind == "error":
        st.error(payload)
    elif kind == "results":
        st.success("Operación terminada")
        st.dataframe(results_frame(payload, _names()), hide_index=True, width="stretch")


@st.dialog("Dejar activo solo aquí", width="large")
def _exclusive_dialog(instance_id: str, full_name: str) -> None:
    """Diálogo de confirmación: muestra el plan y, si se confirma, activa en exclusiva."""
    service, _ = _bootstrap()
    names = _names()
    try:
        plan = service.preview_exclusive(instance_id, full_name)
    except JobEnablerError as exc:
        st.error(str(exc))
        return

    st.write(
        f"Se activará **{full_name}** en **{names[instance_id]}** y se desactivará "
        "cualquier otro job con el mismo nombre."
    )
    st.dataframe(plan_frame(plan.changes, names), hide_index=True, width="stretch")
    for failed_id, reason in plan.failures.items():
        st.warning(f"{names.get(failed_id, failed_id)} no se ha podido consultar: {reason}")
    st.caption("No hay rollback: si algún Jenkins falla, los demás cambios se mantienen.")

    if st.button("Confirmar", type="primary"):
        try:
            _flash_results(service.activate_exclusively(instance_id, full_name))
        except JobEnablerError as exc:
            _flash_error(str(exc))


def _toggle(service: JobService, loc: JobLocation) -> None:
    """Invierte el estado del job en esa única ubicación."""
    enable = loc.status is not JobStatus.ENABLED
    try:
        _flash_results([service.set_state(loc.instance_id, loc.full_name, enabled=enable)])
    except JobEnablerError as exc:
        _flash_error(str(exc))


def _render_detail(service: JobService, locations: list[JobLocation]) -> None:
    """Pinta una fila por ubicación con sus acciones (abrir, activar/desactivar, exclusivo)."""
    names = _names()
    for loc in sorted(locations, key=lambda x: (x.instance_id, x.full_name)):
        key = f"{loc.instance_id}:{loc.full_name}"
        name, path, kind, state, link, toggle, only = st.columns([2, 4, 2, 2, 1, 2, 3])
        name.write(names[loc.instance_id])
        path.code(loc.full_name, language=None)
        kind.write(loc.kind.value)
        enabled = loc.status is JobStatus.ENABLED
        state.write("🟢 Activo" if enabled else "🔴 Inactivo")
        if loc.url:
            link.link_button("Abrir", loc.url)
        if toggle.button("Desactivar" if enabled else "Activar", key=f"toggle:{key}"):
            _toggle(service, loc)
        if only.button("Dejar activo solo aquí", key=f"only:{key}"):
            _exclusive_dialog(loc.instance_id, loc.full_name)


def main() -> None:
    """Dibuja la página: selector de instancias, búsqueda, resumen y detalle."""
    st.set_page_config(page_title="Job Enabler", page_icon="🛠️", layout="wide")
    st.title("Job Enabler")

    try:
        service, config = _bootstrap()
    except JobEnablerError as exc:
        st.error(f"Error de configuración: {exc}")
        st.stop()

    names = {i.id: i.name for i in config.instances}
    with st.sidebar:
        st.header("Jenkins")
        selected = st.multiselect(
            "Instancias a consultar",
            options=list(names),
            default=list(names),
            format_func=names.__getitem__,
        )
        if st.button("Recargar"):
            _search.clear()

    _show_flash()

    query = st.text_input("Buscar repositorio (nombre del job)", placeholder="p. ej. app-backend")
    if len(query.strip()) < MIN_QUERY_LENGTH:
        st.info(f"Escribe al menos {MIN_QUERY_LENGTH} caracteres para buscar.")
        return
    if not selected:
        st.warning("Selecciona al menos un Jenkins.")
        return

    report = _search(service, query.strip(), tuple(selected))
    for failed_id, reason in report.failures.items():
        st.warning(f"{names[failed_id]}: {reason}")
    if not report.jobs:
        st.info("Sin resultados.")
        return

    shown_names = {i: names[i] for i in selected}
    st.subheader("Resumen")
    st.dataframe(build_matrix(report, shown_names), hide_index=True, width="stretch")

    st.subheader("Detalle")
    key = st.selectbox(
        "Repositorio",
        options=list(report.jobs),
        format_func=lambda k: repo_label(report.jobs[k]),
    )
    _render_detail(service, report.jobs[key])


main()
