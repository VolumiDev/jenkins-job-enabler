# jenkins-job-enabler
Herramienta para la busqueda, activación y desactivación de jobs que se pueden encontrar en uno o varios de los jenkins informados

## Qué hace
- Busca un repositorio (nombre final del job) en todos los Jenkins configurados, o solo en algunos, y muestra su estado en cada uno. La ruta de carpetas puede ser distinta en cada Jenkins.
- Activa o desactiva un job concreto en un Jenkins concreto, sin tocar el resto.
- **Dejar activo solo aquí**: activa el job elegido y desactiva cualquier otro job con el mismo nombre, en el mismo Jenkins o en otros. Antes de aplicar nada muestra una previsualización y pide confirmación.
- Soporta jobs Pipeline, Multibranch Pipeline y Freestyle.

## Configuración
- **Jenkins a consultar**: `config/jenkins.yaml` (versionado, sin secretos). La ruta se puede cambiar con `JOB_ENABLER_CONFIG`.
- **Secretos**: `.env` (no versionado). Una pareja `JENKINS_<ID>_USER` / `JENKINS_<ID>_TOKEN` por cada `id` del YAML. Copia `.env.example` como punto de partida.

## Puesta en marcha
```powershell
python -m pip install --user uv          # si no tienes uv
python -m uv sync
python -m uv run streamlit run src/job_enabler/ui/app.py
```

## Laboratorio local (3 Jenkins en Docker)
Sirve para probar sin acceso a los Jenkins corporativos. Necesita Docker Desktop arrancado.
```powershell
python -m uv run python -m lab.bootstrap up      # genera lab/.env, levanta DEV/PRE/PRO, crea tokens en .env y deja el estado inicial
python -m uv run python -m lab.bootstrap reset   # restaura el estado inicial de los jobs
python -m uv run python -m lab.bootstrap down    # para los contenedores
```
Jenkins DEV, PRE y PRO quedan en `http://localhost:8081`, `8082` y `8083` (solo accesibles desde la propia máquina). El escenario sembrado está en `lab/scenario.py`.

## Desarrollo
```powershell
python -m uv run pytest                    # tests unitarios
python -m uv run pytest -m integration     # criterios de aceptación contra el laboratorio levantado
python -m uv run ruff check . ; python -m uv run ruff format --check . ; python -m uv run mypy src tests lab
```

## Arquitectura
```
src/job_enabler/
├── domain/          # modelos, errores y el puerto JenkinsGateway (sin I/O)
├── application/     # JobService: search, set_state, preview_exclusive, activate_exclusively
├── infrastructure/  # settings (YAML + .env), adaptador python-jenkins, factoría
└── ui/              # Streamlit (solo llama a JobService)
```

## Limitaciones conocidas
- La activación exclusiva **no tiene rollback**: si un Jenkins falla a mitad, el resto de cambios se mantienen y la UI informa del resultado de cada ubicación.
- La UI no autentica a quien la usa: todas las acciones se hacen con el token de servicio del `.env`.
