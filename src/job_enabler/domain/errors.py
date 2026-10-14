class JobEnablerError(Exception):
    """Base de los errores de la aplicación."""


class JobNotFoundError(JobEnablerError):
    def __init__(self, instance_id: str, full_name: str) -> None:
        super().__init__(f"El job '{full_name}' no existe en '{instance_id}'")
        self.instance_id = instance_id
        self.full_name = full_name


class InstanceUnavailableError(JobEnablerError):
    def __init__(self, instance_id: str, reason: str) -> None:
        super().__init__(f"Instancia '{instance_id}' no disponible: {reason}")
        self.instance_id = instance_id


class UnknownInstanceError(JobEnablerError):
    def __init__(self, instance_id: str) -> None:
        super().__init__(f"Instancia '{instance_id}' no configurada")
        self.instance_id = instance_id


class ConfigurationError(JobEnablerError):
    """Configuración o secretos ausentes o inválidos."""
