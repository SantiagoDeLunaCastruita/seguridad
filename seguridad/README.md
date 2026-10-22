# CIBERGUARD

Simulador educativo de ciberseguridad con API FastAPI y persistencia SQLite.

## Requisitos

- Python 3.10 o posterior.

## Ejecutar en Windows

Abre PowerShell en la carpeta del proyecto y ejecuta:

```powershell
python -m pip install -r requirements.txt
python -m uvicorn backend:app --host 127.0.0.1 --port 8000
```

Abre `http://127.0.0.1:8000`. La aplicación usa el mismo origen para la interfaz y la API; no uses `python -m http.server` para iniciarla. Si Windows no reconoce `python`, usa el ejecutable de Python instalado con `python -m pip` y `python -m uvicorn` desde la terminal de VS Code.

## Variaciones con IA (OpenRouter)

Crea una clave de API en OpenRouter y configúrala en PowerShell antes de iniciar CIBERGUARD. La clave se mantiene en el servidor: no la pongas en el código, en `app.js` ni en archivos que vayas a publicar.

```powershell
$env:CIBERGUARD_OPENROUTER_API_KEY = "tu-clave-de-openrouter"
$env:CIBERGUARD_OPENROUTER_MODEL = "minimax/minimax-m3.1-flash:free"
.\.venv\Scripts\python.exe -m uvicorn backend:app --host 127.0.0.1 --port 8000
```

El modelo gratuito predeterminado puede cambiar o alcanzar límites de uso; configura `CIBERGUARD_OPENROUTER_MODEL` con otro identificador gratuito disponible si es necesario. En el Centro de Entrenamiento, pulsa **Variación IA (API)** para crear una nueva versión del ejercicio mostrado. OpenRouter genera únicamente remitente, asunto y descripción; las opciones, respuestas correctas, evaluación y puntos permanecen definidos y comprobados por CIBERGUARD. Si faltan la clave, la cuota o el servicio, la app muestra el error y puedes continuar usando el generador local.

La base de datos se crea automáticamente en `instance/ciberguard.sqlite3`; ese directorio contiene datos de cuentas y progreso y debe excluirse de cualquier copia pública del proyecto.

## Funciones

- Registro e inicio de sesión por correo y contraseña.
- Contraseñas almacenadas como hash scrypt con sal aleatoria; nunca se guardan en texto claro.
- Sesiones aleatorias persistidas en SQLite, con cookie `HttpOnly`, `SameSite=Strict` y vencimiento de 8 horas.
- Progreso y perfil guardados por cuenta, no en `localStorage`.
- Puntuaciones, riesgo, decisiones y recompensas validados por el servidor.
- Ruta técnica de ciberseguridad organizada en seis etapas, con programación, sistemas, redes, defensa, prácticas de laboratorio y respuesta a incidentes. Incluye 12 problemas interactivos (dos por etapa), con evaluación y explicación del servidor.
- Glosario ampliado con conceptos de fundamentos, redes y Wi-Fi, sistemas, desarrollo seguro, nube, monitoreo, gobernanza y forense digital.
- Simulaciones defensivas y ficticias de redes impostoras, desconexiones sospechosas, avisos de privacidad y protección del router. Las respuestas se evalúan en el servidor y cada tipo de ejercicio solo otorga puntos una vez.
- Respuestas correctas CTF omitidas de la API y del JSON público; el servidor compara los envíos.
- 11 escenarios, ramas de contención, laboratorio de contraseña local, 20 términos de glosario e insignias.
- Reporte y QR servidos por la misma aplicación. El QR contiene solo el identificador de estudiante, no su nombre ni puntos.

## Seguridad y límites

Esta configuración es para desarrollo local. El servicio se enlaza a `127.0.0.1` para que no sea accesible desde otras computadoras. No lo publiques directamente en Internet.

Para producción se necesita HTTPS detrás de un proxy correctamente configurado, `CIBERGUARD_COOKIE_SECURE=1`, secretos/respaldos gestionados, controles de abuso adicionales, verificación de correo, monitoreo y una revisión de seguridad. La limitación local de intentos de inicio de sesión no sustituye el rate limiting de un proxy de producción. El diploma de participación no es una certificación institucional verificable.

El laboratorio de contraseñas se ejecuta en el navegador y no envía ni almacena la contraseña introducida. Utiliza solamente valores ficticios.

La ruta es una progresión técnica de aprendizaje, no un plan escolar oficial. Las prácticas se limitan a sistemas propios o laboratorios expresamente autorizados.

Las simulaciones de ataques solo presentan situaciones ficticias para aprender a reconocer señales, proteger cuentas y reportar incidentes. No escanean, alteran ni se conectan a redes reales, ni enseñan a ejecutar ataques. Al solicitar una variación, solo el contexto del ejercicio se envía a OpenRouter; no se envían datos de cuenta o perfil. Los textos generados se validan y se muestran como texto, no como HTML.

## Pruebas del API

```powershell
python -m unittest discover -s tests -v
```
