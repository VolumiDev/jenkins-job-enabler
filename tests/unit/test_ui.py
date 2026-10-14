from collections.abc import Iterator
from pathlib import Path

import pytest
import streamlit as st
from streamlit.testing.v1 import AppTest

from job_enabler.application.job_service import JobService
from job_enabler.domain.models import JobLocation, JobStatus, SearchReport
from job_enabler.infrastructure.settings import AppConfig, InstanceConfig
from job_enabler.ui.components import build_matrix
from tests.unit.fakes import FakeGateway

NAMES = {"dev": "Jenkins DEV", "pre": "Jenkins PRE", "pro": "Jenkins PRO"}
APP = str(Path(__file__).resolve().parents[2] / "src/job_enabler/ui/app.py")


def test_matrix_has_one_row_per_repo_and_marks_missing_and_duplicates() -> None:
    report = SearchReport(
        jobs={
            "app-backend": [
                JobLocation("dev", "team-a/app-backend", JobStatus.ENABLED),
                JobLocation("dev", "legacy/app-backend", JobStatus.DISABLED),
                JobLocation("pro", "prod/app-backend", JobStatus.DISABLED),
            ]
        },
        failures={},
    )

    matrix = build_matrix(report, NAMES)

    assert list(matrix.columns) == ["Repositorio", *NAMES.values()]
    row = matrix.iloc[0]
    assert row["Repositorio"] == "app-backend"
    assert row["Jenkins DEV"] == "🟢🔴 (2)"
    assert row["Jenkins PRE"] == "—"
    assert row["Jenkins PRO"] == "🔴"


@pytest.fixture
def app(monkeypatch: pytest.MonkeyPatch) -> Iterator[AppTest]:
    gateways = {
        "dev": FakeGateway("dev", {"team-a/app-backend": True}),
        "pro": FakeGateway("pro", {"prod/app-backend": False}),
    }
    config = AppConfig(
        instances=[
            InstanceConfig(id="dev", name="Jenkins DEV", url="http://dev"),
            InstanceConfig(id="pro", name="Jenkins PRO", url="http://pro"),
        ]
    )
    monkeypatch.setattr(
        "job_enabler.infrastructure.gateway_factory.build_service",
        lambda: (JobService(gateways), config),
    )
    st.cache_resource.clear()
    st.cache_data.clear()
    yield AppTest.from_file(APP, default_timeout=30)
    st.cache_resource.clear()
    st.cache_data.clear()


def test_app_asks_for_a_query_first(app: AppTest) -> None:
    app.run()

    assert not app.exception
    assert "al menos" in app.info[0].value


def test_app_search_shows_summary_and_detail(app: AppTest) -> None:
    app.run()
    app.text_input[0].set_value("app-backend").run()

    assert not app.exception
    assert len(app.dataframe) == 1
    labels = [b.label for b in app.button]
    assert "Dejar activo solo aquí" in labels
    assert "Activar" in labels and "Desactivar" in labels


def test_app_toggle_changes_only_that_location(app: AppTest) -> None:
    app.run()
    app.text_input[0].set_value("app-backend").run()

    next(b for b in app.button if b.label == "Activar").click().run()

    assert not app.exception
    assert any("Operación terminada" in s.value for s in app.success)
