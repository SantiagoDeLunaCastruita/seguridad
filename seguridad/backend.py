from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

import httpx
import qrcode
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, Response as RawResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError
from qrcode.image.svg import SvgPathImage


ROOT = Path(__file__).resolve().parent
DATA_PATH = ROOT / "data" / "scenarios.json"
STUDY_ROADMAP_PATH = ROOT / "data" / "study_roadmap.json"
STUDY_EXERCISES_PATH = ROOT / "data" / "study_exercises.json"
DB_PATH = Path(os.environ.get("CIBERGUARD_DB", ROOT / "instance" / "ciberguard.sqlite3"))
COOKIE_NAME = "ciberguard_session"
SESSION_SECONDS = 8 * 60 * 60
PASSWORD_SALT_BYTES = 16
PASSWORD_HASH_BYTES = 32
PASSWORD_SCRYPT_N = 2**14
PASSWORD_SCRYPT_R = 8
PASSWORD_SCRYPT_P = 1
EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,189}\.[^@\s]{2,63}$")
SCENARIO_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,100}$")
OPENROUTER_CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"
AI_TIMEOUT_SECONDS = 45
DEFAULT_AI_MODEL = "minimax/minimax-m3.1-flash:free"


with DATA_PATH.open(encoding="utf-8") as data_file:
    SIMULATOR_DATA: dict[str, Any] = json.load(data_file)
with STUDY_ROADMAP_PATH.open(encoding="utf-8") as roadmap_file:
    STUDY_ROADMAP: dict[str, Any] = json.load(roadmap_file)
with STUDY_EXERCISES_PATH.open(encoding="utf-8") as exercises_file:
    STUDY_EXERCISES: dict[str, dict[str, Any]] = {
        exercise["id"]: exercise for exercise in json.load(exercises_file)
    }
SCENARIOS = {scenario["id"]: scenario for scenario in SIMULATOR_DATA["trainingScenarios"]}
CTFS = {challenge["id"]: challenge for challenge in SIMULATOR_DATA["ctfChallenges"]}

WIFI_SCENARIO_VARIANTS = [
    {
        "family": "wifi-unknown-network",
        "subject": "Dos redes con nombres casi iguales",
        "body": "En {place}, tu dispositivo muestra una red con un nombre muy parecido al de la red oficial. No puedes confirmar cuál es auténtica.",
        "safe_text": "No conectarte todavía; confirmar el nombre exacto con el personal por un canal oficial y usar datos móviles mientras tanto.",
        "safe_feedback": "Correcto: el nombre de una red no demuestra quién la administra. Confirma los datos con la institución o el establecimiento.",
        "safe_consequence": "Evitas enviar información a una red no verificada y notificas la duda al responsable.",
        "unsafe_texts": [
            "Elegir la red con la señal más intensa e iniciar sesión con tu cuenta.",
            "Conectarte y compartir la contraseña institucional para comprobar si funciona.",
        ],
    },
    {
        "family": "wifi-credential-prompt",
        "subject": "La conexión solicita datos de tu cuenta",
        "body": "Al conectarte a la red de {place}, aparece una página inesperada que solicita la contraseña de tu cuenta y un código de verificación.",
        "safe_text": "Cerrar la página sin escribir datos; confirmar el acceso mediante la app o el soporte oficial y reportar el aviso.",
        "safe_feedback": "Bien hecho: no compartas contraseñas ni códigos en una página inesperada. Verifica el acceso desde un canal oficial independiente.",
        "safe_consequence": "No entregas credenciales y el equipo responsable puede revisar la página simulada.",
        "unsafe_texts": [
            "Introducir la contraseña y el código para terminar la conexión rápidamente.",
            "Usar la misma contraseña con una pequeña variación para probar el formulario.",
        ],
    },
    {
        "family": "wifi-unexpected-disconnect",
        "subject": "La red se desconecta repetidamente",
        "body": "Mientras estudias en {place}, tu dispositivo pierde la conexión varias veces y vuelve a mostrar redes guardadas. No sabes qué causó el cambio.",
        "safe_text": "Desconectarte, evitar reconexiones automáticas, usar datos móviles y reportar el comportamiento al soporte por un canal conocido.",
        "safe_feedback": "Correcto: una desconexión inesperada no permite confirmar que la red sea segura. Evita reconectarte a ciegas y consulta al soporte.",
        "safe_consequence": "Mantienes tus cuentas fuera de una conexión dudosa y reportas el incidente sin investigar la red por tu cuenta.",
        "unsafe_texts": [
            "Volver a conectarte repetidamente a la primera red disponible.",
            "Desactivar las protecciones del dispositivo para que la conexión no se interrumpa.",
        ],
    },
    {
        "family": "wifi-home-router",
        "subject": "Aviso de configuración del router",
        "body": "La app oficial de tu router en {place} muestra que hay una actualización de seguridad pendiente y que la configuración debe revisarse.",
        "safe_text": "Abrir la app o panel oficial del fabricante, instalar actualizaciones disponibles y pedir ayuda al proveedor para revisar que WPS esté desactivado y usar seguridad moderna.",
        "safe_feedback": "Buena respuesta: administra el router desde la app o el panel oficial, mantén su software actualizado y usa opciones de seguridad modernas. No sigas enlaces recibidos inesperadamente.",
        "safe_consequence": "Revisas la configuración desde el canal legítimo y mantienes el equipo actualizado.",
        "unsafe_texts": [
            "Ignorar todas las actualizaciones y mantener la configuración predeterminada indefinidamente.",
            "Buscar un enlace de configuración en un mensaje no solicitado y escribir allí tus datos.",
        ],
    },
    {
        "family": "wifi-public-network",
        "subject": "Red pública para una tarea urgente",
        "body": "En {place}, necesitas consultar una cuenta importante y la única red disponible es pública y no has podido verificar quién la administra.",
        "safe_text": "Esperar a una conexión verificada o usar datos móviles; no introducir información sensible mientras la red no esté confirmada.",
        "safe_feedback": "Correcto: una red pública desconocida no es el lugar adecuado para introducir información sensible. Usa una conexión confiable.",
        "safe_consequence": "Proteges la cuenta y completas la tarea desde una conexión que puedes verificar.",
        "unsafe_texts": [
            "Iniciar sesión y realizar la operación sensible en esa red porque tiene buena señal.",
            "Desactivar las advertencias de seguridad del navegador para continuar.",
        ],
    },
    {
        "family": "wifi-evil-twin",
        "kind": "attack-simulation",
        "subject": "Simulación: una red impostora intenta obtener credenciales",
        "body": "En {place}, aparece una red ficticia con un nombre casi idéntico al oficial. Tras conectarte, una pantalla simulada pide tu contraseña institucional y un código de acceso. No introduzcas información: analiza las señales y decide cómo responder.",
        "safe_text": "Cerrar la pantalla, desconectarte de esa red y verificar el nombre de la red con el personal por un canal oficial.",
        "safe_feedback": "Correcto: una red con nombre parecido y una solicitud inesperada de credenciales son señales de riesgo. No compartas contraseñas ni códigos.",
        "safe_consequence": "El incidente ficticio queda contenido: no se entregan credenciales y se notifica al responsable de la red.",
        "unsafe_texts": [
            "Escribir tu contraseña y el código para poder usar Internet.",
            "Probar con una contraseña anterior para averiguar si la página es legítima.",
        ],
    },
    {
        "family": "wifi-disconnection-incident",
        "kind": "attack-simulation",
        "subject": "Simulación: interrupciones sospechosas de conexión",
        "body": "Durante una sesión en {place}, varios dispositivos pierden la conexión y muestran avisos de reconexión que no esperaban. El personal de soporte confirma que investigará el incidente. No realices pruebas en la red: elige una respuesta segura.",
        "safe_text": "Desconectarte de la red afectada, desactivar la reconexión automática si está disponible y avisar al soporte por un canal conocido.",
        "safe_feedback": "Bien: las desconexiones inesperadas pueden tener varias causas. Evita reconectarte a ciegas y deja la investigación técnica al personal autorizado.",
        "safe_consequence": "Usas una conexión alternativa confiable y el responsable recibe el reporte para investigar de forma autorizada.",
        "unsafe_texts": [
            "Reconectarte repetidamente y seguir usando la red para comprobar si vuelve a ocurrir.",
            "Intentar interrumpir la conexión de otros dispositivos para identificar el origen.",
        ],
    },
    {
        "family": "wifi-traffic-warning",
        "kind": "attack-simulation",
        "subject": "Simulación: advertencia de privacidad en una red pública",
        "body": "En {place}, el navegador muestra una advertencia de privacidad al abrir un servicio. La red es pública y no has confirmado quién la administra. En esta práctica, el aviso indica que debes pausar antes de enviar información.",
        "safe_text": "No continuar ni enviar datos; desconectarte y volver a abrir el servicio desde una conexión confiable o datos móviles.",
        "safe_feedback": "Correcto: no ignores advertencias de seguridad, especialmente en redes no verificadas. Usa una conexión confiable y el sitio o app oficial.",
        "safe_consequence": "No envías información a través de una conexión cuya privacidad no puedes confirmar.",
        "unsafe_texts": [
            "Ignorar la advertencia e iniciar sesión porque necesitas terminar rápido.",
            "Enviar la información y cambiar la contraseña solo si algo sale mal.",
        ],
    },
    {
        "family": "wifi-router-hardening",
        "kind": "attack-simulation",
        "subject": "Simulación: revisión preventiva de la red doméstica",
        "body": "La app oficial del router en {place} indica que el equipo necesita una revisión de seguridad. No hay una intrusión confirmada. La práctica consiste en elegir medidas preventivas, no en probar ataques.",
        "safe_text": "Entrar desde la app oficial, actualizar el router, usar WPA2-AES o WPA3 y desactivar WPS si no lo necesitas.",
        "safe_feedback": "Bien: mantener el firmware actualizado, usar cifrado moderno y desactivar funciones de configuración que no uses reduce riesgos.",
        "safe_consequence": "La configuración se revisa desde la interfaz legítima del fabricante y se aplican medidas defensivas.",
        "unsafe_texts": [
            "Dejar el router con la configuración predeterminada y posponer todas las actualizaciones.",
            "Descargar una herramienta desconocida que promete revisar la red y darle acceso al router.",
        ],
    },
]

WIFI_SCENARIO_PLACES = [
    "la biblioteca del campus",
    "una cafetería concurrida",
    "la sala de estudio",
    "un espacio público durante un viaje",
    "el laboratorio de informática",
    "tu hogar",
]


class RegisterRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=12, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    institution: str = Field(min_length=1, max_length=100)


class LoginRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=128)


class ProfileRequest(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)

    name: str = Field(min_length=1, max_length=80)
    institution: str = Field(min_length=1, max_length=100)


class DecisionRequest(BaseModel):
    decision_index: int = Field(ge=0, le=20)


class StudyExerciseAnswerRequest(BaseModel):
    answer_index: int = Field(ge=0, le=20)


class ScenarioVariationRequest(BaseModel):
    scenario_id: str = Field(min_length=1, max_length=100, pattern=SCENARIO_ID_RE.pattern)


class GeneratedScenarioText(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    sender: str = Field(min_length=3, max_length=120)
    subject: str = Field(min_length=5, max_length=160)
    body: str = Field(min_length=30, max_length=700)


class RecoveryRequest(BaseModel):
    safe: bool


class CtfSubmission(BaseModel):
    answer: str = Field(min_length=1, max_length=200)


class PasswordQuizSubmission(BaseModel):
    option_id: str = Field(min_length=1, max_length=20)


class PasswordLabCompletion(BaseModel):
    completed: bool


@contextmanager
def connect_db() -> Iterator[sqlite3.Connection]:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA journal_mode = WAL")
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def initialize_database() -> None:
    with connect_db() as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                email TEXT NOT NULL UNIQUE COLLATE NOCASE,
                password_salt BLOB NOT NULL,
                password_hash BLOB NOT NULL,
                name TEXT NOT NULL,
                institution TEXT NOT NULL,
                created_at INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY,
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                expires_at INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS sessions_expiry_idx ON sessions(expires_at);
            CREATE TABLE IF NOT EXISTS progress (
                user_id INTEGER PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
                points INTEGER NOT NULL DEFAULT 0,
                phishing_completed INTEGER NOT NULL DEFAULT 0,
                vulnerability INTEGER NOT NULL DEFAULT 35,
                correct_decisions INTEGER NOT NULL DEFAULT 0,
                total_decisions INTEGER NOT NULL DEFAULT 0,
                safe_streak INTEGER NOT NULL DEFAULT 0,
                password_lab_completed INTEGER NOT NULL DEFAULT 0,
                password_quiz_completed INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS scenario_attempts (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL,
                decision_index INTEGER NOT NULL,
                safe INTEGER NOT NULL,
                answered_at INTEGER NOT NULL,
                recovery_safe INTEGER,
                PRIMARY KEY (user_id, scenario_id)
            );
            CREATE TABLE IF NOT EXISTS generated_scenarios (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                scenario_id TEXT NOT NULL,
                family_id TEXT NOT NULL,
                scenario_json TEXT NOT NULL,
                created_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, scenario_id)
            );
            CREATE INDEX IF NOT EXISTS generated_scenarios_family_idx
                ON generated_scenarios(user_id, family_id);
            CREATE TABLE IF NOT EXISTS ctf_solves (
                user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                challenge_id INTEGER NOT NULL,
                solved_at INTEGER NOT NULL,
                PRIMARY KEY (user_id, challenge_id)
            );
            CREATE TABLE IF NOT EXISTS login_limits (
                client_key TEXT PRIMARY KEY,
                failures INTEGER NOT NULL,
                window_started INTEGER NOT NULL,
                locked_until INTEGER NOT NULL DEFAULT 0
            );
            """
        )
        connection.execute("DELETE FROM sessions WHERE expires_at <= ?", (int(time.time()),))


@asynccontextmanager
async def lifespan(_: FastAPI):
    initialize_database()
    yield


app = FastAPI(
    title="CIBERGUARD API",
    version="1.0.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; "
        "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
        "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com "
        "https://cdn.jsdelivr.net https://cdnjs.cloudflare.com; "
        "font-src 'self' https://fonts.gstatic.com https://cdnjs.cloudflare.com data:; "
        "img-src 'self' data: blob:; connect-src 'self'; "
        "object-src 'none'; base-uri 'self'; frame-ancestors 'none'"
    )
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def verify_same_origin(request: Request) -> None:
    origin = request.headers.get("origin")
    expected = f"{request.url.scheme}://{request.url.netloc}"
    if not origin or origin != expected:
        raise HTTPException(status_code=403, detail="Origen de solicitud no permitido.")


def get_password_hash(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=PASSWORD_SCRYPT_N,
        r=PASSWORD_SCRYPT_R,
        p=PASSWORD_SCRYPT_P,
        dklen=PASSWORD_HASH_BYTES,
    )


def validate_email(email: str) -> str:
    normalized = email.lower()
    if not EMAIL_RE.fullmatch(normalized):
        raise HTTPException(status_code=422, detail="Escribe un correo electrónico válido.")
    return normalized


def create_session(response: Response, user_id: int) -> None:
    token = secrets.token_urlsafe(32)
    expires_at = int(time.time()) + SESSION_SECONDS
    with connect_db() as connection:
        connection.execute(
            "INSERT INTO sessions (token_hash, user_id, expires_at) VALUES (?, ?, ?)",
            (hashlib.sha256(token.encode("ascii")).hexdigest(), user_id, expires_at),
        )
    response.set_cookie(
        COOKIE_NAME,
        token,
        max_age=SESSION_SECONDS,
        httponly=True,
        secure=os.environ.get("CIBERGUARD_COOKIE_SECURE") == "1",
        samesite="strict",
        path="/",
    )


def authenticated_user(request: Request) -> sqlite3.Row:
    token = request.cookies.get(COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Inicia sesión para continuar.")

    token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
    now = int(time.time())
    with connect_db() as connection:
        row = connection.execute(
            """
            SELECT users.id, users.email, users.name, users.institution
            FROM sessions
            JOIN users ON users.id = sessions.user_id
            WHERE sessions.token_hash = ? AND sessions.expires_at > ?
            """,
            (token_hash, now),
        ).fetchone()
        if row is None:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
            raise HTTPException(status_code=401, detail="La sesión venció. Inicia sesión otra vez.")
        return row


def current_user_id(request: Request) -> int:
    return int(authenticated_user(request)["id"])


def user_view(user: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": f"CG-{int(user['id']):06d}",
        "email": user["email"],
        "name": user["name"],
        "institution": user["institution"],
    }


def progress_view(user_id: int) -> dict[str, Any]:
    with connect_db() as connection:
        row = connection.execute(
            "SELECT * FROM progress WHERE user_id = ?", (user_id,)
        ).fetchone()
        attempts = connection.execute(
            """
            SELECT scenario_attempts.scenario_id, decision_index, safe, recovery_safe,
                   generated_scenarios.family_id, generated_scenarios.scenario_json
            FROM scenario_attempts
            LEFT JOIN generated_scenarios
                ON generated_scenarios.user_id = scenario_attempts.user_id
                AND generated_scenarios.scenario_id = scenario_attempts.scenario_id
            WHERE scenario_attempts.user_id = ?
            """,
            (user_id,),
        ).fetchall()
        solves = connection.execute(
            "SELECT challenge_id FROM ctf_solves WHERE user_id = ?", (user_id,)
        ).fetchall()
        user = connection.execute(
            "SELECT id, email, name, institution FROM users WHERE id = ?", (user_id,)
        ).fetchone()

    if row is None or user is None:
        raise HTTPException(status_code=401, detail="La cuenta ya no existe.")

    correct_decisions = row["correct_decisions"]
    safe_streak = row["safe_streak"]
    completed_scenarios = {attempt["scenario_id"] for attempt in attempts}
    completed_password_scenarios = sum(
        1
        for scenario_id in completed_scenarios
        if SCENARIOS.get(scenario_id, {}).get("type") == "password"
    )
    completed_types = set()
    for attempt in attempts:
        if attempt["scenario_id"] in SCENARIOS:
            completed_types.add(SCENARIOS[attempt["scenario_id"]]["type"])
        elif attempt["scenario_json"]:
            completed_types.add(json.loads(attempt["scenario_json"])["type"])
    badges: list[str] = []
    if correct_decisions >= 3:
        badges.append("sharp-eye")
    if completed_password_scenarios >= 2:
        badges.append("account-guardian")
    if safe_streak >= 3:
        badges.append("safe-streak")
    if len(completed_types) >= 5:
        badges.append("all-rounder")
    if row["password_lab_completed"] and row["password_quiz_completed"]:
        badges.append("password-pro")

    return {
        "user": user_view(user),
        "points": row["points"],
        "phishingCompleted": row["phishing_completed"],
        "vulnerability": row["vulnerability"],
        "correctDecisions": correct_decisions,
        "totalDecisions": row["total_decisions"],
        "safeStreak": safe_streak,
        "solvedCtfs": [solve["challenge_id"] for solve in solves],
        "completedScenarios": sorted(completed_scenarios),
        "completedBranches": sorted(
            attempt["scenario_id"] for attempt in attempts if attempt["recovery_safe"] is not None
        ),
        "attempts": [
            {
                "scenarioId": attempt["scenario_id"],
                "decisionIndex": attempt["decision_index"],
                "safe": bool(attempt["safe"]),
                "recoverySafe": (
                    None if attempt["recovery_safe"] is None else bool(attempt["recovery_safe"])
                ),
            }
            for attempt in attempts
        ],
        "badges": badges,
        "passwordLabCompleted": bool(row["password_lab_completed"]),
        "passwordQuizCompleted": bool(row["password_quiz_completed"]),
    }


def award_safe_decision(
    connection: sqlite3.Connection,
    user_id: int,
    reward: int,
    risk_delta: int,
    phishing: bool,
) -> None:
    connection.execute(
        """
        UPDATE progress
        SET points = points + ?,
            phishing_completed = phishing_completed + ?,
            vulnerability = MIN(100, MAX(0, vulnerability + ?)),
            correct_decisions = correct_decisions + 1,
            total_decisions = total_decisions + 1,
            safe_streak = safe_streak + 1
        WHERE user_id = ?
        """,
        (reward, int(phishing), risk_delta, user_id),
    )


@app.get("/")
def homepage() -> FileResponse:
    return FileResponse(ROOT / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/app.js")
def frontend_script() -> FileResponse:
    return FileResponse(ROOT / "app.js", media_type="text/javascript", headers={"Cache-Control": "no-cache"})


@app.get("/styles.css")
def frontend_styles() -> FileResponse:
    return FileResponse(ROOT / "styles.css", media_type="text/css", headers={"Cache-Control": "no-cache"})


@app.post("/api/auth/register")
def register(payload: RegisterRequest, request: Request, response: Response) -> dict[str, Any]:
    verify_same_origin(request)
    email = validate_email(payload.email)
    salt = secrets.token_bytes(PASSWORD_SALT_BYTES)
    password_hash = get_password_hash(payload.password, salt)
    try:
        with connect_db() as connection:
            cursor = connection.execute(
                """
                INSERT INTO users (email, password_salt, password_hash, name, institution, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (email, salt, password_hash, payload.name, payload.institution, int(time.time())),
            )
            user_id = int(cursor.lastrowid)
            connection.execute("INSERT INTO progress (user_id) VALUES (?)", (user_id,))
    except sqlite3.IntegrityError as error:
        raise HTTPException(status_code=409, detail="Ya existe una cuenta con ese correo.") from error

    create_session(response, user_id)
    return {"user": {"id": f"CG-{user_id:06d}", "email": email, "name": payload.name, "institution": payload.institution}}


def check_login_rate_limit(client_key: str) -> None:
    now = int(time.time())
    with connect_db() as connection:
        row = connection.execute(
            "SELECT failures, window_started, locked_until FROM login_limits WHERE client_key = ?",
            (client_key,),
        ).fetchone()
        if row and row["locked_until"] > now:
            raise HTTPException(status_code=429, detail="Demasiados intentos. Espera unos minutos antes de probar otra vez.")


def record_login_failure(client_key: str) -> None:
    now = int(time.time())
    with connect_db() as connection:
        row = connection.execute(
            "SELECT failures, window_started FROM login_limits WHERE client_key = ?",
            (client_key,),
        ).fetchone()
        if row is None or now - row["window_started"] > 900:
            failures, window_started = 1, now
        else:
            failures, window_started = row["failures"] + 1, row["window_started"]
        locked_until = now + 900 if failures >= 5 else 0
        connection.execute(
            """
            INSERT INTO login_limits (client_key, failures, window_started, locked_until)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(client_key) DO UPDATE SET
                failures = excluded.failures,
                window_started = excluded.window_started,
                locked_until = excluded.locked_until
            """,
            (client_key, failures, window_started, locked_until),
        )


@app.post("/api/auth/login")
def login(payload: LoginRequest, request: Request, response: Response) -> dict[str, Any]:
    verify_same_origin(request)
    email = validate_email(payload.email)
    client_key = request.client.host if request.client else "unknown"
    check_login_rate_limit(client_key)
    with connect_db() as connection:
        user = connection.execute(
            "SELECT id, email, password_salt, password_hash, name, institution FROM users WHERE email = ?",
            (email,),
        ).fetchone()
    if user is None:
        get_password_hash(payload.password, b"ciberguard-dummy")
        record_login_failure(client_key)
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")

    supplied_hash = get_password_hash(payload.password, bytes(user["password_salt"]))
    if not hmac.compare_digest(supplied_hash, bytes(user["password_hash"])):
        record_login_failure(client_key)
        raise HTTPException(status_code=401, detail="Correo o contraseña incorrectos.")

    with connect_db() as connection:
        connection.execute("DELETE FROM login_limits WHERE client_key = ?", (client_key,))
    create_session(response, int(user["id"]))
    return {"user": user_view(user)}


@app.post("/api/auth/logout")
def logout(request: Request, response: Response) -> dict[str, bool]:
    verify_same_origin(request)
    token = request.cookies.get(COOKIE_NAME)
    if token:
        token_hash = hashlib.sha256(token.encode("ascii", errors="ignore")).hexdigest()
        with connect_db() as connection:
            connection.execute("DELETE FROM sessions WHERE token_hash = ?", (token_hash,))
    response.delete_cookie(COOKIE_NAME, path="/", httponly=True, samesite="strict")
    return {"ok": True}


@app.get("/api/auth/me")
def get_current_user(request: Request) -> dict[str, Any]:
    return {"user": user_view(authenticated_user(request))}


@app.get("/api/progress")
def get_progress(request: Request) -> dict[str, Any]:
    return progress_view(current_user_id(request))


@app.put("/api/profile")
def update_profile(payload: ProfileRequest, request: Request) -> dict[str, Any]:
    verify_same_origin(request)
    user_id = current_user_id(request)
    with connect_db() as connection:
        connection.execute(
            "UPDATE users SET name = ?, institution = ? WHERE id = ?",
            (payload.name, payload.institution, user_id),
        )
    return progress_view(user_id)


@app.get("/api/scenarios")
def get_scenarios(request: Request) -> list[dict[str, Any]]:
    current_user_id(request)
    return [
        {
            "id": scenario["id"],
            "type": scenario["type"],
            "category": scenario["category"],
            "channel": scenario["channel"],
            "sender": scenario["sender"],
            "subject": scenario["subject"],
            "body": scenario["body"],
            "decisions": [{"text": decision["text"]} for decision in scenario["decisions"]],
        }
        for scenario in SCENARIOS.values()
    ]


def public_scenario(scenario: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": scenario["id"],
        "type": scenario["type"],
        "category": scenario["category"],
        "channel": scenario["channel"],
        "sender": scenario["sender"],
        "subject": scenario["subject"],
        "body": scenario["body"],
        "liveGenerated": bool(scenario.get("liveGenerated")),
        "simulationKind": scenario.get("simulationKind", "wifi-awareness"),
        "decisions": [{"text": decision["text"]} for decision in scenario["decisions"]],
    }


def scenario_for_user(user_id: int, scenario_id: str) -> dict[str, Any] | None:
    scenario = SCENARIOS.get(scenario_id)
    if scenario is not None:
        return scenario

    with connect_db() as connection:
        row = connection.execute(
            """
            SELECT scenario_json FROM generated_scenarios
            WHERE user_id = ? AND scenario_id = ?
            """,
            (user_id, scenario_id),
        ).fetchone()
    if row is None:
        return None
    return json.loads(row["scenario_json"])


def generated_family_rewarded(
    connection: sqlite3.Connection,
    user_id: int,
    scenario_id: str,
) -> bool:
    generated = connection.execute(
        """
        SELECT family_id FROM generated_scenarios
        WHERE user_id = ? AND scenario_id = ?
        """,
        (user_id, scenario_id),
    ).fetchone()
    if generated is None:
        return False
    previous_reward = connection.execute(
        """
        SELECT 1 FROM scenario_attempts
        JOIN generated_scenarios
            ON generated_scenarios.user_id = scenario_attempts.user_id
            AND generated_scenarios.scenario_id = scenario_attempts.scenario_id
        WHERE scenario_attempts.user_id = ?
            AND generated_scenarios.family_id = ?
            AND scenario_attempts.scenario_id != ?
            AND (scenario_attempts.safe = 1 OR scenario_attempts.recovery_safe = 1)
        LIMIT 1
        """,
        (user_id, generated["family_id"], scenario_id),
    ).fetchone()
    return previous_reward is not None


async def generate_ai_scenario_text(scenario: dict[str, Any]) -> GeneratedScenarioText:
    api_key = os.environ.get("CIBERGUARD_OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(
            status_code=503,
            detail="Configura CIBERGUARD_OPENROUTER_API_KEY en el servidor para activar las variaciones con IA.",
        )
    model = os.environ.get("CIBERGUARD_OPENROUTER_MODEL", DEFAULT_AI_MODEL)
    prompt_context = {
        "category": scenario["category"],
        "channel": scenario["channel"],
        "subject_to_vary": scenario["subject"],
        "original_situation": scenario["body"],
    }
    try:
        async with httpx.AsyncClient(timeout=AI_TIMEOUT_SECONDS) as client:
            response = await client.post(
                OPENROUTER_CHAT_URL,
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model,
                    "stream": False,
                    "temperature": 0.8,
                    "max_tokens": 300,
                    "messages": [
                        {
                            "role": "system",
                            "content": (
                                "Eres un creador de material educativo de ciberseguridad defensiva. "
                                "Responde solo con JSON que tenga exactamente los campos sender, subject y body, "
                                "todos como texto en español. Crea una variación ficticia y realista que conserve "
                                "el mismo tipo de riesgo y permita usar las mismas opciones de respuesta del ejercicio "
                                "original. No escribas instrucciones para perpetrar ataques, código, herramientas, "
                                "direcciones web, credenciales reales, datos personales ni pasos operativos ofensivos. "
                                "Enmarca la situación desde la perspectiva de quien la recibe y no reveles cuál opción "
                                "es correcta. Usa un remitente inventado claramente no real."
                            ),
                        },
                        {
                            "role": "user",
                            "content": json.dumps(prompt_context, ensure_ascii=False),
                        },
                    ],
                },
            )
    except httpx.ConnectError as error:
        raise HTTPException(
            status_code=503,
            detail="No se pudo conectar con OpenRouter. Comprueba tu conexión a Internet.",
        ) from error
    except httpx.TimeoutException as error:
        raise HTTPException(
            status_code=504,
            detail="OpenRouter tardó demasiado en generar el ejercicio. Inténtalo de nuevo.",
        ) from error
    except httpx.RequestError as error:
        raise HTTPException(
            status_code=502,
            detail="Falló la solicitud a OpenRouter. Comprueba el servicio e inténtalo de nuevo.",
        ) from error

    if response.status_code == 401:
        raise HTTPException(
            status_code=503,
            detail="OpenRouter rechazó la clave API. Revisa CIBERGUARD_OPENROUTER_API_KEY en el servidor.",
        )
    if response.status_code == 402:
        raise HTTPException(
            status_code=503,
            detail="OpenRouter no pudo atender la solicitud con la cuota disponible. Revisa los límites de tu cuenta.",
        )
    if response.status_code == 429:
        raise HTTPException(
            status_code=503,
            detail="Se alcanzó el límite temporal de OpenRouter. Inténtalo más tarde.",
        )
    if response.status_code == 404:
        model = os.environ.get("CIBERGUARD_OPENROUTER_MODEL", DEFAULT_AI_MODEL)
        raise HTTPException(
            status_code=503,
            detail=f"OpenRouter no encontró el modelo '{model}'. Configura CIBERGUARD_OPENROUTER_MODEL con un modelo disponible.",
        )
    if not response.is_success:
        raise HTTPException(
            status_code=502,
            detail=f"OpenRouter respondió con HTTP {response.status_code}; no se generó el ejercicio.",
        )

    try:
        api_result = response.json()
        message = api_result["choices"][0]["message"]["content"]
        generated = GeneratedScenarioText.model_validate_json(message)
    except (KeyError, TypeError, ValueError, ValidationError):
        raise HTTPException(
            status_code=502,
            detail="OpenRouter no devolvió un ejercicio con el formato esperado. Inténtalo de nuevo.",
        ) from None

    if any(
        re.search(r"https?://|www\.|<[^>]*>", value, re.IGNORECASE)
        for value in (generated.sender, generated.subject, generated.body)
    ):
        raise HTTPException(
            status_code=502,
            detail="La respuesta de OpenRouter no pasó la validación de contenido. Inténtalo de nuevo.",
        )
    return generated


@app.post("/api/scenarios/ai")
async def generate_ai_scenario(
    payload: ScenarioVariationRequest,
    request: Request,
) -> dict[str, Any]:
    verify_same_origin(request)
    user_id = current_user_id(request)
    source = scenario_for_user(user_id, payload.scenario_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Escenario de referencia no encontrado.")

    generated_text = await generate_ai_scenario_text(source)
    scenario_id = f"ai-{uuid4().hex}"
    scenario = {
        **source,
        "id": scenario_id,
        "sender": generated_text.sender,
        "subject": generated_text.subject,
        "body": generated_text.body,
        "liveGenerated": True,
        "simulationKind": "ai-generated",
    }
    with connect_db() as connection:
        source_record = connection.execute(
            """
            SELECT family_id FROM generated_scenarios
            WHERE user_id = ? AND scenario_id = ?
            """,
            (user_id, payload.scenario_id),
        ).fetchone()
        family_id = source_record["family_id"] if source_record else payload.scenario_id
        connection.execute(
            """
            INSERT INTO generated_scenarios
                (user_id, scenario_id, family_id, scenario_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, scenario_id, family_id, json.dumps(scenario), int(time.time())),
        )
    return public_scenario(scenario)


@app.post("/api/scenarios/live")
def generate_live_scenario(request: Request) -> dict[str, Any]:
    verify_same_origin(request)
    user_id = current_user_id(request)
    variant = secrets.choice(WIFI_SCENARIO_VARIANTS)
    place = secrets.choice(WIFI_SCENARIO_PLACES)
    scenario_id = f"live-wifi-{uuid4().hex}"
    decisions = [
        {
            "text": variant["safe_text"],
            "safe": True,
            "score": 15,
            "riskDelta": -10,
            "feedback": variant["safe_feedback"],
            "consequence": variant["safe_consequence"],
        },
        *[
            {
                "text": text,
                "safe": False,
                "score": 0,
                "riskDelta": 12,
                "feedback": "No conectes dispositivos ni compartas credenciales en una red que no has podido verificar.",
                "consequence": "En esta simulación, detén la interacción, desconéctate y consulta al soporte por un canal oficial.",
            }
            for text in variant["unsafe_texts"]
        ],
    ]
    secrets.SystemRandom().shuffle(decisions)
    scenario = {
        "id": scenario_id,
        "type": "wifi",
        "category": (
            "Simulación de ataque ficticio · Wi-Fi"
            if variant.get("kind") == "attack-simulation"
            else "Seguridad de redes Wi-Fi"
        ),
        "channel": "Simulación defensiva",
        "sender": f"Situación ficticia · {place}",
        "subject": variant["subject"],
        "body": variant["body"].format(place=place),
        "liveGenerated": True,
        "simulationKind": variant.get("kind", "wifi-awareness"),
        "decisions": decisions,
    }
    with connect_db() as connection:
        connection.execute(
            """
            INSERT INTO generated_scenarios
                (user_id, scenario_id, family_id, scenario_json, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, scenario_id, variant["family"], json.dumps(scenario), int(time.time())),
        )
    return public_scenario(scenario)


@app.post("/api/scenarios/{scenario_id}/decision")
def submit_decision(
    scenario_id: str,
    payload: DecisionRequest,
    request: Request,
) -> dict[str, Any]:
    verify_same_origin(request)
    user_id = current_user_id(request)
    scenario = scenario_for_user(user_id, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Escenario no encontrado.")
    if payload.decision_index >= len(scenario["decisions"]):
        raise HTTPException(status_code=422, detail="Opción de decisión no válida.")

    decision = scenario["decisions"][payload.decision_index]
    with connect_db() as connection:
        existing = connection.execute(
            "SELECT decision_index, safe, recovery_safe FROM scenario_attempts WHERE user_id = ? AND scenario_id = ?",
            (user_id, scenario_id),
        ).fetchone()
        if existing is not None:
            saved_decision = scenario["decisions"][existing["decision_index"]]
            return {
                "alreadyRecorded": True,
                "safe": bool(existing["safe"]),
                "score": 0,
                "feedback": saved_decision["feedback"],
                "consequence": saved_decision["consequence"],
                "recoveryAvailable": not bool(existing["safe"]) and existing["recovery_safe"] is None,
                "progress": progress_view(user_id),
            }

        connection.execute(
            """
            INSERT INTO scenario_attempts (user_id, scenario_id, decision_index, safe, answered_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (user_id, scenario_id, payload.decision_index, int(decision["safe"]), int(time.time())),
        )
        reward = 0
        if decision["safe"]:
            is_phishing = scenario["type"] in {"phishing", "smishing", "vishing"}
            reward = int(decision["score"])
            if scenario.get("liveGenerated") and generated_family_rewarded(
                connection, user_id, scenario_id
            ):
                reward = 0
            award_safe_decision(
                connection,
                user_id,
                reward,
                int(decision["riskDelta"]),
                is_phishing,
            )
        else:
            connection.execute(
                """
                UPDATE progress
                SET vulnerability = MIN(100, MAX(0, vulnerability + ?)),
                    total_decisions = total_decisions + 1,
                    safe_streak = 0
                WHERE user_id = ?
                """,
                (int(decision["riskDelta"]), user_id),
            )

    progress = progress_view(user_id)
    return {
        "alreadyRecorded": False,
        "safe": bool(decision["safe"]),
        "score": reward if decision["safe"] else 0,
        "practiceOnly": bool(scenario.get("liveGenerated") and decision["safe"] and reward == 0),
        "feedback": decision["feedback"],
        "consequence": decision["consequence"],
        "recoveryAvailable": not bool(decision["safe"]),
        "progress": progress,
    }


@app.post("/api/scenarios/{scenario_id}/recovery")
def submit_recovery(
    scenario_id: str,
    payload: RecoveryRequest,
    request: Request,
) -> dict[str, Any]:
    verify_same_origin(request)
    user_id = current_user_id(request)
    scenario = scenario_for_user(user_id, scenario_id)
    if scenario is None:
        raise HTTPException(status_code=404, detail="Escenario no encontrado.")
    with connect_db() as connection:
        attempt = connection.execute(
            """
            SELECT safe, recovery_safe FROM scenario_attempts
            WHERE user_id = ? AND scenario_id = ?
            """,
            (user_id, scenario_id),
        ).fetchone()
        if attempt is None or attempt["safe"]:
            raise HTTPException(status_code=409, detail="No hay una ruta insegura pendiente de contener.")
        if attempt["recovery_safe"] is not None:
            raise HTTPException(status_code=409, detail="La decisión de contención ya fue registrada.")
        connection.execute(
            "UPDATE scenario_attempts SET recovery_safe = ? WHERE user_id = ? AND scenario_id = ?",
            (int(payload.safe), user_id, scenario_id),
        )
        if payload.safe:
            recovery_reward = 5
            if scenario.get("liveGenerated") and generated_family_rewarded(
                connection, user_id, scenario_id
            ):
                recovery_reward = 0
            connection.execute(
                """
                UPDATE progress
                SET points = points + ?,
                    vulnerability = MAX(0, vulnerability - 8),
                    correct_decisions = correct_decisions + 1,
                    total_decisions = total_decisions + 1,
                    safe_streak = safe_streak + 1
                WHERE user_id = ?
                """,
                (recovery_reward, user_id),
            )
        else:
            connection.execute(
                """
                UPDATE progress
                SET vulnerability = MIN(100, vulnerability + 10),
                    total_decisions = total_decisions + 1,
                    safe_streak = 0
                WHERE user_id = ?
                """,
                (user_id,),
            )

    return {
        "safe": payload.safe,
        "feedback": (
            "Contuviste la simulación y notificaste por un canal confiable."
            if payload.safe
            else "La exposición aumentó en esta ruta simulada. Detén la interacción y notifícalo."
        ),
        "score": recovery_reward if payload.safe else 0,
        "practiceOnly": bool(scenario.get("liveGenerated") and payload.safe and recovery_reward == 0),
        "progress": progress_view(user_id),
    }


@app.get("/api/glossary")
def get_glossary(request: Request) -> list[dict[str, Any]]:
    current_user_id(request)
    return SIMULATOR_DATA["glossary"]


@app.get("/api/study-roadmap")
def get_study_roadmap(request: Request) -> dict[str, Any]:
    current_user_id(request)
    return STUDY_ROADMAP


@app.get("/api/study-exercises")
def get_study_exercises(request: Request) -> list[dict[str, Any]]:
    current_user_id(request)
    return [
        {
            key: value
            for key, value in exercise.items()
            if key not in {"correctIndex", "explanation"}
        }
        for exercise in STUDY_EXERCISES.values()
    ]


@app.post("/api/study-exercises/{exercise_id}/answer")
def answer_study_exercise(
    exercise_id: str,
    payload: StudyExerciseAnswerRequest,
    request: Request,
) -> dict[str, Any]:
    verify_same_origin(request)
    current_user_id(request)
    exercise = STUDY_EXERCISES.get(exercise_id)
    if exercise is None:
        raise HTTPException(status_code=404, detail="Ejercicio no encontrado.")
    if payload.answer_index >= len(exercise["options"]):
        raise HTTPException(status_code=422, detail="La opción seleccionada no es válida.")
    correct_index = exercise["correctIndex"]
    return {
        "correct": payload.answer_index == correct_index,
        "correctIndex": correct_index,
        "explanation": exercise["explanation"],
    }


@app.get("/api/ctf")
def get_ctfs(request: Request) -> list[dict[str, Any]]:
    current_user_id(request)
    return [
        {key: value for key, value in challenge.items() if key != "flag"}
        for challenge in CTFS.values()
    ]


@app.post("/api/ctf/{challenge_id}/submit")
def submit_ctf(challenge_id: int, payload: CtfSubmission, request: Request) -> dict[str, Any]:
    verify_same_origin(request)
    user_id = current_user_id(request)
    challenge = CTFS.get(challenge_id)
    if challenge is None:
        raise HTTPException(status_code=404, detail="Reto no encontrado.")
    correct = hmac.compare_digest(
        payload.answer.strip().casefold().encode("utf-8"),
        challenge["flag"].strip().casefold().encode("utf-8"),
    )
    if not correct:
        return {"correct": False, "progress": progress_view(user_id)}

    with connect_db() as connection:
        cursor = connection.execute(
            "INSERT OR IGNORE INTO ctf_solves (user_id, challenge_id, solved_at) VALUES (?, ?, ?)",
            (user_id, challenge_id, int(time.time())),
        )
        first_solve = cursor.rowcount == 1
        if first_solve:
            connection.execute(
                "UPDATE progress SET points = points + 30 WHERE user_id = ?", (user_id,)
            )
    return {
        "correct": True,
        "awarded": 30 if first_solve else 0,
        "progress": progress_view(user_id),
    }


@app.get("/api/password-quiz")
def get_password_quiz(request: Request) -> list[dict[str, str]]:
    current_user_id(request)
    return [
        {"id": "seasonal", "text": "Sol2026!"},
        {"id": "common", "text": "p4ssw0rd"},
        {"id": "long-unique", "text": "nube-limon-cobre-rio-74"},
    ]


@app.post("/api/password-quiz")
def submit_password_quiz(
    payload: PasswordQuizSubmission,
    request: Request,
) -> dict[str, Any]:
    verify_same_origin(request)
    user_id = current_user_id(request)
    is_correct = payload.option_id == "long-unique"
    with connect_db() as connection:
        row = connection.execute(
            "SELECT password_quiz_completed FROM progress WHERE user_id = ?", (user_id,)
        ).fetchone()
        if row["password_quiz_completed"]:
            return {
                "correct": is_correct,
                "alreadyCompleted": True,
                "feedback": "Este reto ya quedó registrado. Recuerda preferir claves largas, únicas y guardadas con un gestor.",
                "progress": progress_view(user_id),
            }
        if is_correct:
            connection.execute(
                """
                UPDATE progress
                SET password_quiz_completed = 1, points = points + 10
                WHERE user_id = ?
                """,
                (user_id,),
            )

    return {
        "correct": is_correct,
        "alreadyCompleted": False,
        "feedback": (
            "Correcto: una clave larga y única ofrece más resistencia a la adivinación. Usa un gestor para crearla y guardarla."
            if is_correct
            else "No es la mejor opción: es corta o sigue un patrón conocido. Intenta otra vez; el reto aún no se ha completado."
        ),
        "progress": progress_view(user_id),
    }


@app.post("/api/password-lab/completed")
def complete_password_lab(
    payload: PasswordLabCompletion,
    request: Request,
) -> dict[str, Any]:
    verify_same_origin(request)
    user_id = current_user_id(request)
    awarded = False
    if payload.completed:
        with connect_db() as connection:
            cursor = connection.execute(
                """
                UPDATE progress
                SET password_lab_completed = 1,
                    points = points + CASE WHEN password_lab_completed = 0 THEN 5 ELSE 0 END
                WHERE user_id = ? AND password_lab_completed = 0
                """,
                (user_id,),
            )
            awarded = cursor.rowcount == 1
    return {"progress": progress_view(user_id), "awarded": awarded}


@app.get("/api/report")
def export_report(request: Request) -> JSONResponse:
    state = progress_view(current_user_id(request))
    report = {
        "app": "CIBERGUARD - Entrenador de Ciberseguridad",
        "version": "3.0",
        "student": state["user"]["name"],
        "institution": state["user"]["institution"],
        "studentId": state["user"]["id"],
        "totalPointsXP": state["points"],
        "phishingCasesCompleted": state["phishingCompleted"],
        "ctfChallengesSolved": len(state["solvedCtfs"]),
        "trainingScenariosCompleted": len(state["completedScenarios"]),
        "trainingAccuracy": (
            round(state["correctDecisions"] / state["totalDecisions"] * 100)
            if state["totalDecisions"]
            else 0
        ),
        "badges": state["badges"],
        "vulnerability": state["vulnerability"],
        "exportDate": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    return JSONResponse(
        report,
        headers={"Content-Disposition": f'attachment; filename="Reporte_CiberGuard_{state["user"]["id"]}.json"'},
    )


@app.get("/api/credential/qr")
def get_credential_qr(request: Request) -> RawResponse:
    user_id = current_user_id(request)
    content = f"CIBERGUARD:{user_id:06d}"
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=6, border=2)
    qr.add_data(content)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    return RawResponse(
        content=image.to_string(encoding="unicode"),
        media_type="image/svg+xml",
        headers={"Cache-Control": "no-store"},
    )
