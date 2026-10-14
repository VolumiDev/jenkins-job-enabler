"""Escenario sembrado en el laboratorio: instancia -> {ruta completa del job: activo}."""

PORTS = {"dev": 8081, "pre": 8082, "pro": 8083}

INITIAL_STATE: dict[str, dict[str, bool]] = {
    "dev": {
        "team-a/app-backend": True,  # Pipeline
        "legacy/app-backend": True,  # Freestyle, duplicado en el mismo Jenkins
        "team-a/app-frontend": True,  # Multibranch
    },
    "pre": {
        "backend/app-backend": True,  # Pipeline
        "batch-nightly": True,  # Freestyle
    },
    "pro": {
        "prod/team-a/app-backend": False,  # Pipeline, desactivado
        "frontend/app-frontend": True,  # Multibranch
    },
}
