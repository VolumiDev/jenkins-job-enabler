import jenkins

from job_enabler.application.job_service import JobService
from job_enabler.domain.ports import JenkinsGateway
from job_enabler.infrastructure.jenkins_gateway import PythonJenkinsGateway
from job_enabler.infrastructure.settings import (
    AppConfig,
    Credentials,
    load_config,
    load_credentials,
)


def build_gateways(
    config: AppConfig, credentials: dict[str, Credentials]
) -> dict[str, JenkinsGateway]:
    gateways: dict[str, JenkinsGateway] = {}
    for instance in config.instances:
        secret = credentials[instance.id]
        client = jenkins.Jenkins(
            instance.url,
            username=secret.user,
            password=secret.token.get_secret_value(),
            timeout=config.search.timeout_seconds,
        )
        # python-jenkins no expone verify_ssl; se fija sobre su sesión de requests.
        client._session.verify = instance.verify_ssl
        gateways[instance.id] = PythonJenkinsGateway(
            instance.id, client, config.search.folder_depth
        )
    return gateways


def build_service() -> tuple[JobService, AppConfig]:
    """Punto de composición: configuración + secretos → servicio listo para usar."""
    config = load_config()
    return JobService(build_gateways(config, load_credentials(config))), config
