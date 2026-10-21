import pytest

from job_enabler.application.job_service import JobService
from job_enabler.domain.errors import JobNotFoundError, UnknownInstanceError
from job_enabler.domain.models import JobStatus, Outcome
from tests.unit.fakes import FakeGateway


@pytest.fixture
def gateways() -> dict[str, FakeGateway]:
    # La ruta de carpetas cambia entre Jenkins; el nombre final identifica el job.
    return {
        "dev": FakeGateway(
            "dev",
            {
                "team-a/app-backend": True,
                "legacy/app-backend": True,  # duplicado en el mismo Jenkins
                "team-a/app-frontend": True,
            },
        ),
        "pre": FakeGateway("pre", {"backend/app-backend": True, "batch-nightly": True}),
        "pro": FakeGateway(
            "pro", {"prod/team-a/app-backend": False, "frontend/app-frontend": True}
        ),
    }


@pytest.fixture
def service(gateways: dict[str, FakeGateway]) -> JobService:
    return JobService(gateways)


def _state(gateways: dict[str, FakeGateway]) -> dict[tuple[str, str], bool]:
    return {(i, n): e for i, g in gateways.items() for n, e in g.jobs.items()}


def test_search_groups_by_final_name_even_if_paths_differ(service: JobService) -> None:
    report = service.search("APP-BACKEND")

    locations = report.jobs["app-backend"]
    assert {(loc.instance_id, loc.full_name): loc.status for loc in locations} == {
        ("dev", "team-a/app-backend"): JobStatus.ENABLED,
        ("dev", "legacy/app-backend"): JobStatus.ENABLED,
        ("pre", "backend/app-backend"): JobStatus.ENABLED,
        ("pro", "prod/team-a/app-backend"): JobStatus.DISABLED,
    }
    assert report.failures == {}


def test_search_matches_final_name_not_folders(service: JobService) -> None:
    assert service.search("team-a").jobs == {}


def test_search_can_be_limited_to_one_instance(service: JobService) -> None:
    report = service.search("app", instance_ids=["pro"])

    assert {loc.instance_id for locs in report.jobs.values() for loc in locs} == {"pro"}


def test_search_tolerates_unavailable_instance(gateways: dict[str, FakeGateway]) -> None:
    gateways["pre"].down = True

    report = JobService(gateways).search("app-backend")

    assert "pre" in report.failures
    assert {loc.instance_id for loc in report.jobs["app-backend"]} == {"dev", "pro"}


def test_search_unknown_instance_raises(service: JobService) -> None:
    with pytest.raises(UnknownInstanceError):
        service.search("x", instance_ids=["nope"])


def test_set_state_touches_only_the_chosen_location(
    service: JobService, gateways: dict[str, FakeGateway]
) -> None:
    before = _state(gateways)

    result = service.set_state("pro", "prod/team-a/app-backend", enabled=True)

    assert result.outcome is Outcome.CHANGED
    after = _state(gateways)
    assert {k for k in before if before[k] != after[k]} == {("pro", "prod/team-a/app-backend")}


def test_set_state_is_idempotent(service: JobService, gateways: dict[str, FakeGateway]) -> None:
    result = service.set_state("dev", "team-a/app-backend", enabled=True)

    assert result.outcome is Outcome.UNCHANGED
    assert gateways["dev"].writes == []


def test_set_state_missing_job_raises(service: JobService) -> None:
    with pytest.raises(JobNotFoundError):
        service.set_state("pre", "team-a/app-frontend", enabled=True)


@pytest.mark.parametrize(
    ("instance", "path"),
    [
        ("dev", "team-a/app-backend"),
        ("dev", "legacy/app-backend"),
        ("pre", "backend/app-backend"),
        ("pro", "prod/team-a/app-backend"),  # estaba desactivado
    ],
)
def test_activate_exclusively_leaves_only_target_enabled(
    service: JobService, gateways: dict[str, FakeGateway], instance: str, path: str
) -> None:
    service.activate_exclusively(instance, path)

    enabled = {k for k, v in _state(gateways).items() if v and k[1].endswith("app-backend")}
    assert enabled == {(instance, path)}


def test_activate_exclusively_does_not_touch_other_jobs(
    service: JobService, gateways: dict[str, FakeGateway]
) -> None:
    service.activate_exclusively("pro", "prod/team-a/app-backend")

    assert gateways["dev"].jobs["team-a/app-frontend"] is True
    assert gateways["pre"].jobs["batch-nightly"] is True
    assert gateways["pro"].jobs["frontend/app-frontend"] is True


def test_activate_exclusively_enables_target_before_disabling_others(
    service: JobService, gateways: dict[str, FakeGateway]
) -> None:
    FakeGateway.journal.clear()

    service.activate_exclusively("pro", "prod/team-a/app-backend")

    journal = FakeGateway.journal
    assert journal[0] == ("pro", "prod/team-a/app-backend", True)
    assert len(journal) == 4
    assert all(enabled is False for *_, enabled in journal[1:])


def test_preview_matches_execution_and_changes_nothing(
    service: JobService, gateways: dict[str, FakeGateway]
) -> None:
    before = _state(gateways)

    plan = service.preview_exclusive("pro", "prod/team-a/app-backend")

    assert _state(gateways) == before
    assert {(c.instance_id, c.full_name): c.target for c in plan.changes} == {
        ("pro", "prod/team-a/app-backend"): JobStatus.ENABLED,
        ("dev", "team-a/app-backend"): JobStatus.DISABLED,
        ("dev", "legacy/app-backend"): JobStatus.DISABLED,
        ("pre", "backend/app-backend"): JobStatus.DISABLED,
    }
    results = service.activate_exclusively("pro", "prod/team-a/app-backend")
    assert {(r.instance_id, r.full_name) for r in results} == {
        (c.instance_id, c.full_name) for c in plan.changes
    }


def test_activate_exclusively_missing_target_changes_nothing(
    service: JobService, gateways: dict[str, FakeGateway]
) -> None:
    with pytest.raises(JobNotFoundError):
        service.activate_exclusively("pre", "team-a/app-frontend")

    assert all(g.writes == [] for g in gateways.values())


def test_activate_exclusively_reports_unavailable_instance(
    gateways: dict[str, FakeGateway],
) -> None:
    gateways["pro"].down = True

    results = JobService(gateways).activate_exclusively("dev", "team-a/app-backend")

    by_instance = {r.instance_id: r for r in results if r.instance_id == "pro"}
    assert by_instance["pro"].outcome is Outcome.FAILED
    assert gateways["pre"].jobs["backend/app-backend"] is False
    assert gateways["dev"].jobs["legacy/app-backend"] is False
