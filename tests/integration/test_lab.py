"""Criterios de aceptación de la HU contra el laboratorio Docker (`pytest -m integration`).

Requiere: `uv run python -m lab.bootstrap up`.
"""

from collections.abc import Iterator

import pytest
import requests

from job_enabler.application.job_service import JobService
from job_enabler.domain.models import JobKind, JobStatus, Outcome
from job_enabler.infrastructure.gateway_factory import build_service
from lab.bootstrap import reset_state, url_of
from lab.scenario import PORTS

pytestmark = pytest.mark.integration

BACKEND_PRO = "prod/team-a/app-backend"


@pytest.fixture
def service() -> Iterator[JobService]:
    try:
        for instance_id in PORTS:
            requests.get(url_of(instance_id), timeout=3)
    except requests.RequestException:
        pytest.skip("Laboratorio no levantado: uv run python -m lab.bootstrap up")
    reset_state()
    yield build_service()[0]
    reset_state()


def _status(service: JobService, query: str) -> dict[tuple[str, str], JobStatus]:
    report = service.search(query)
    assert report.failures == {}
    return {
        (loc.instance_id, loc.full_name): loc.status
        for locations in report.jobs.values()
        for loc in locations
    }


def test_criterion_1_search_lists_every_jenkins_with_status(service: JobService) -> None:
    assert _status(service, "app-backend") == {
        ("dev", "team-a/app-backend"): JobStatus.ENABLED,
        ("dev", "legacy/app-backend"): JobStatus.ENABLED,
        ("pre", "backend/app-backend"): JobStatus.ENABLED,
        ("pro", BACKEND_PRO): JobStatus.DISABLED,
    }


def test_search_reports_job_kinds_including_multibranch(service: JobService) -> None:
    (locations,) = service.search("app-frontend").jobs.values()

    assert {loc.kind for loc in locations} == {JobKind.MULTIBRANCH}
    assert {loc.instance_id for loc in locations} == {"dev", "pro"}


def test_criterion_2_exclusive_activation_disables_everywhere_else(service: JobService) -> None:
    results = service.activate_exclusively("pro", BACKEND_PRO)

    assert all(r.outcome is not Outcome.FAILED for r in results)
    enabled = {k for k, v in _status(service, "app-backend").items() if v is JobStatus.ENABLED}
    assert enabled == {("pro", BACKEND_PRO)}
    # otros repositorios intactos
    assert _status(service, "batch-nightly") == {("pre", "batch-nightly"): JobStatus.ENABLED}


def test_criterion_3_individual_toggle_leaves_other_jenkins_alone(service: JobService) -> None:
    before = _status(service, "app-frontend")

    service.set_state("dev", "team-a/app-frontend", enabled=False)  # Multibranch

    after = _status(service, "app-frontend")
    assert after[("dev", "team-a/app-frontend")] is JobStatus.DISABLED
    assert after[("pro", "frontend/app-frontend")] == before[("pro", "frontend/app-frontend")]

    service.set_state("dev", "team-a/app-frontend", enabled=True)
    assert _status(service, "app-frontend") == before


@pytest.mark.parametrize("path", ["team-a/app-backend", "legacy/app-backend"])
def test_toggle_works_for_pipeline_and_freestyle(service: JobService, path: str) -> None:
    service.set_state("dev", path, enabled=False)

    assert _status(service, "app-backend")[("dev", path)] is JobStatus.DISABLED
