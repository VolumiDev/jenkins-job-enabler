# Job Enabler

> Busca, activa y desactiva jobs de Jenkins repartidos en varias instancias desde una única interfaz web.

![Python](https://img.shields.io/badge/python-3.13%2B-3776AB?logo=python&logoColor=white)
![Streamlit](https://img.shields.io/badge/UI-Streamlit-FF4B4B?logo=streamlit&logoColor=white)
![uv](https://img.shields.io/badge/gestor-uv-DE5FE9)
![Licencia](https://img.shields.io/badge/licencia-Apache%202.0-blue)

Cuando un mismo repositorio tiene job en varios Jenkins (DEV, PRE, PRO…) —e incluso duplicado dentro del mismo Jenkins— saber dónde está activo y dejarlo activo en un único sitio es tedioso y propenso a errores. **Job Enabler** muestra el estado del job en todos los Jenkins a la vez y permite cambiarlo con seguridad.

## Índice

- [Funcionalidades](#funcionalidades)
- [Requisitos](#requisitos)
- [Inicio rápido](#inicio-rápido)
- [Laboratorio de pruebas con Docker](#laboratorio-de-pruebas-con-docker)
- [Configuración para un entorno privado](#configuración-para-un-entorno-privado)
- [Desarrollo](#desarrollo)
- [Arquitectura](#arquitectura)
- [Limitaciones conocidas](#limitaciones-conocidas)
- [Licencia](#licencia)

## Funcionalidades

| Funcionalidad | Descripción |
|---|---|
| **Búsqueda multi-Jenkins** | Busca un repositorio (el nombre final del job) en todos los Jenkins configurados o solo en los que elijas. Las consultas se hacen en paralelo y la ruta de carpetas puede ser distinta en cada Jenkins. |
| **Resumen en matriz** | Una fila por repositorio y una columna por Jenkins, con semáforo de estado: 🟢 activo · 🔴 inactivo · — no existe · ⚠️ no disponible. Si hay varios jobs en el mismo Jenkins se muestra el recuento. |
| **Detalle por ubicación** | Para cada job: Jenkins, ruta completa, tipo, estado y enlace directo para abrirlo. |
| **Activar / desactivar** | Cambia el estado de un job concreto en un Jenkins concreto, sin tocar el resto. |
| **Dejar activo solo aquí** | Activa el job elegido y desactiva cualquier otro con el mismo nombre, en el mismo Jenkins o en otros. Antes de aplicar nada muestra una previsualización (columnas *Ahora* / *Después*) y pide confirmación. |
| **Aplicaciones frecuentes** | Botones en el panel lateral que cargan un patrón en la barra de búsqueda con un clic. |
| **Tipos de job** | Pipeline, Multibranch Pipeline (detecta también los deshabilitados) y Freestyle. |
| **Tolerancia a fallos** | Si un Jenkins no responde, se avisa de ello y se siguen mostrando los demás. |
| **Caché de búsqueda** | Los resultados se cachean 60 s; el botón *Recargar* los refresca. Tras cada cambio la caché se invalida. |
| **TLS corporativo** | Valida los certificados con el almacén del sistema operativo (`truststore`). |

## Requisitos

- **Python ≥ 3.13** (uv lo localiza o lo descarga según `requires-python` y `.python-version`).
- [**uv**](https://docs.astral.sh/uv/) como gestor de dependencias y entornos.
- **Docker Desktop** (o Docker Engine con Compose v2), *solo* si quieres usar el laboratorio local.

```powershell
python -m pip install --user uv     # si no tienes uv
```

## Inicio rápido

La forma más rápida de probar la aplicación es con el laboratorio local, que no requiere acceso a ningún Jenkins real:

```powershell
# 1. Instalar dependencias
python -m uv sync

# 2. Levantar los 3 Jenkins de prueba (genera tokens y rellena .env automáticamente)
python -m uv run python -m lab.bootstrap up

# 3. Arrancar la aplicación
python -m uv run streamlit run src/job_enabler/ui/app.py
```

La interfaz queda disponible en <http://localhost:8501>. Prueba a buscar `app-backend`: aparece en DEV (dos veces), PRE y PRO.

Para usarla contra tus propios Jenkins, consulta [Configuración para un entorno privado](#configuración-para-un-entorno-privado).

## Laboratorio de pruebas con Docker

El directorio `lab/` monta tres Jenkins reales, aislados entre sí y con datos sembrados, para ejecutar la aplicación y los tests de integración sin tocar ningún entorno real.

### Topología

```
                    127.0.0.1 (solo accesible desde la propia máquina)
                                      │
        ┌─────────────────────────────┼─────────────────────────────┐
        │ :8081                       │ :8082                       │ :8083
┌───────▼────────┐           ┌────────▼───────┐            ┌────────▼───────┐
│  jenkins-dev   │           │  jenkins-pre   │            │  jenkins-pro   │
│ casc/common +  │           │ casc/common +  │            │ casc/common +  │
│ casc/dev.yaml  │           │ casc/pre.yaml  │            │ casc/pro.yaml  │
└───────┬────────┘           └────────┬───────┘            └────────┬───────┘
        │                             │                             │
   vol. dev_home                 vol. pre_home                 vol. pro_home
```

| Pieza | Detalle |
|---|---|
| **Imagen** (`lab/Dockerfile`) | `jenkins/jenkins:lts-jdk21` con los plugins de `lab/plugins.txt` preinstalados: `cloudbees-folder`, `branch-api`, `workflow-aggregator`, `workflow-multibranch`, `git`, `configuration-as-code` y `job-dsl`. |
| **Servicios** (`lab/docker-compose.yml`) | `jenkins-dev`, `jenkins-pre` y `jenkins-pro`, mismo build, `restart: unless-stopped`. |
| **Puertos** | 8081 (DEV), 8082 (PRE) y 8083 (PRO), publicados solo en `127.0.0.1`. |
| **Persistencia** | Un volumen Docker por instancia (`dev_home`, `pre_home`, `pro_home`): los datos sobreviven a `down`. |
| **Contraseñas** | Una por instancia en `lab/.env` (no versionado), generadas aleatoriamente. El compose se niega a arrancar si faltan. |

### Configuración como código

Los Jenkins no usan asistente de instalación: arrancan ya configurados mediante **JCasC** y **Job DSL**.

- `lab/casc/common.yaml` — común a las tres instancias: usuario `admin` con la contraseña inyectada por variable de entorno, sin registro de usuarios, sin acceso anónimo y 0 ejecutores en el controlador.
- `lab/casc/{dev,pre,pro}.yaml` — definen los jobs de cada entorno con Job DSL.

### Escenario sembrado

El estado inicial está definido en `lab/scenario.py` y cubre los casos límite de la aplicación:

| Jenkins | Job | Tipo | Estado inicial | Caso que cubre |
|---|---|---|---|---|
| DEV | `team-a/app-backend` | Pipeline | 🟢 activo | Mismo repo en varios Jenkins |
| DEV | `legacy/app-backend` | Freestyle | 🟢 activo | Duplicado dentro del mismo Jenkins |
| DEV | `team-a/app-frontend` | Multibranch | 🟢 activo | Job Multibranch |
| PRE | `backend/app-backend` | Pipeline | 🟢 activo | Carpeta distinta por Jenkins |
| PRE | `batch-nightly` | Freestyle | 🟢 activo | Job en la raíz, sin carpeta |
| PRO | `prod/team-a/app-backend` | Pipeline | 🔴 inactivo | Carpetas anidadas y job desactivado |
| PRO | `frontend/app-frontend` | Multibranch | 🟢 activo | Multibranch en otro Jenkins |

### Qué hace `bootstrap up`

1. Genera una contraseña aleatoria por instancia en `lab/.env` (si no existe).
2. Ejecuta `docker compose up -d --build`.
3. Espera a que la API de cada Jenkins responda (máximo 300 s).
4. Crea un API token por REST (con su *crumb*) para cada instancia y lo escribe, junto con el usuario, en el `.env` de la raíz. Si el token ya existe y sigue siendo válido, lo reutiliza.
5. Restaura el estado inicial de los jobs.

### Comandos

```powershell
python -m uv run python -m lab.bootstrap up      # levanta el laboratorio y deja el estado inicial
python -m uv run python -m lab.bootstrap reset   # restaura el estado inicial de los jobs
python -m uv run python -m lab.bootstrap down    # para los contenedores (conserva los datos)
```

Para borrar también los datos, ejecuta `docker compose -f lab/docker-compose.yml down -v`.

> Los tests de integración (`pytest -m integration`) usan este laboratorio: restauran el estado inicial antes y después de cada test y se omiten si no está levantado.

## Configuración para un entorno privado

Para usar la aplicación contra tus Jenkins reales solo hay que editar dos ficheros: `config/jenkins.yaml` (qué Jenkins consultar, sin secretos) y `.env` (credenciales, no versionado).

### 1. `config/jenkins.yaml`

```yaml
search:
  folder_depth: 5        # profundidad máxima de carpetas a recorrer
  timeout_seconds: 10    # timeout HTTP por petición

# Opcional: botones del panel lateral
frequent_apps:
  - app-backend
  - app-frontend

instances:
  - id: dev              # [a-z0-9_]; define JENKINS_DEV_USER / JENKINS_DEV_TOKEN
    name: Jenkins DEV
    url: https://jenkins-dev.example.com
  - id: int_qa
    name: Jenkins QA
    url: https://jenkins-qa.example.com
  - id: pro
    name: Jenkins PRO
    url: https://jenkins-pro.example.com
    verify_ssl: true
```

| Campo | Obligatorio | Descripción |
|---|---|---|
| `search.folder_depth` | No (5) | Profundidad máxima de carpetas a recorrer. Entre 1 y 20. |
| `search.timeout_seconds` | No (10) | Timeout HTTP en segundos (≥ 1). |
| `frequent_apps` | No | Patrones que aparecen como botones. Se limpian espacios, vacíos y duplicados. Si se omite, la sección no se muestra. |
| `instances` | **Sí** | Lista con al menos un Jenkins. |
| `instances[].id` | **Sí** | Identificador único. Solo `[a-z0-9_]` (minúsculas, números y guion bajo; **no** admite guiones). Determina los nombres de las variables del `.env`. |
| `instances[].name` | **Sí** | Nombre visible en la interfaz. |
| `instances[].url` | **Sí** | URL base del Jenkins. |
| `instances[].verify_ssl` | No (`true`) | Validación del certificado TLS. Déjala en `true`; desactivarla solo sirve para diagnosticar. |

Para usar un fichero en otra ubicación, define la variable de entorno `JOB_ENABLER_CONFIG`:

```powershell
$env:JOB_ENABLER_CONFIG = "C:\ruta\a\mi-jenkins.yaml"
```

### 2. `.env`

Copia `.env.example` como `.env` y rellena **una pareja de variables por cada `id`** del YAML, con el id en mayúsculas:

```dotenv
JENKINS_DEV_USER=mi.usuario
JENKINS_DEV_TOKEN=11abc...
JENKINS_INT_QA_USER=mi.usuario
JENKINS_INT_QA_TOKEN=11def...
JENKINS_PRO_USER=mi.usuario
JENKINS_PRO_TOKEN=11ghi...
```

- **Usuario**: el ID de usuario de Jenkins (visible en `/user/<id>/`), no el nombre completo ni el correo.
- **Token**: un *API token* generado en `Jenkins → tu usuario → Configure → API Token`. Es **independiente por instancia**: el de un Jenkins no vale en otro.
- **Permisos**: el usuario necesita permiso de lectura y de configuración sobre los jobs que quieras activar o desactivar.
- **Prioridad**: las variables de entorno del sistema tienen prioridad sobre el `.env`, útil para inyectar secretos desde un gestor o un pipeline.
- `.env` está en `.gitignore`: no lo subas al repositorio.

### 3. Comprobación

1. Arranca la aplicación: `python -m uv run streamlit run src/job_enabler/ui/app.py`.
2. Si falta algo, la interfaz muestra *Error de configuración* y lista las variables ausentes o el campo inválido del YAML.
3. Si un Jenkins no es alcanzable o rechaza las credenciales, se avisa en la propia página y el resto sigue funcionando.
4. Comprobación manual de credenciales:

   ```powershell
   curl.exe -u "USUARIO:TOKEN" https://jenkins-dev.example.com/whoAmI/api/json
   ```

   Debe devolver `"authenticated": true`.

## Desarrollo

```powershell
python -m uv sync                                  # incluye las dependencias de desarrollo
python -m uv run pytest                            # tests unitarios
python -m uv run pytest -m integration             # criterios de aceptación contra el laboratorio
python -m uv run ruff check . ; python -m uv run ruff format --check .
python -m uv run mypy src tests lab                # tipado estricto
python -m uv run pre-commit install                # ruff + mypy antes de cada commit
```

Estructura de tests:

| Ruta | Contenido |
|---|---|
| `tests/unit/` | Servicio, gateway de Jenkins, configuración y UI, con dobles de prueba (`fakes.py`). No necesitan red. |
| `tests/integration/` | Criterios de aceptación de la historia de usuario contra el laboratorio Docker. |

## Arquitectura

Arquitectura hexagonal: el dominio no depende de nada y la UI solo habla con el servicio de aplicación.

```
src/job_enabler/
├── domain/          # modelos, errores y el puerto JenkinsGateway (sin I/O)
├── application/     # JobService: search, set_state, preview_exclusive, activate_exclusively
├── infrastructure/  # settings (YAML + .env), adaptador python-jenkins, factoría
└── ui/              # Streamlit (solo llama a JobService)
lab/                 # laboratorio Docker y CLI de bootstrap
config/              # jenkins.yaml
tests/               # unit/ e integration/
```

`JobService` recibe un `JenkinsGateway` por instancia (un `Protocol` definido en `domain/ports.py`), por lo que la lógica se prueba con dobles sin red y el adaptador `python-jenkins` es intercambiable.

## Limitaciones conocidas

- La activación exclusiva **no tiene rollback**: si un Jenkins falla a mitad, el resto de cambios se mantienen y la UI informa del resultado de cada ubicación.
- La UI **no autentica a quien la usa**: todas las acciones se ejecutan con el token de servicio del `.env`. Despliégala solo en un entorno de confianza.

## Licencia

Distribuido bajo la licencia [Apache 2.0](LICENSE).
