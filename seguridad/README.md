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

La base de datos se crea automáticamente en `instance/ciberguard.sqlite3`; ese directorio contiene datos de cuentas y progreso y debe excluirse de cualquier copia pública del proyecto.

## Funciones

- Registro e inicio de sesión por correo y contraseña.
- Contraseñas almacenadas como hash scrypt con sal aleatoria; nunca se guardan en texto claro.
- Sesiones aleatorias persistidas en SQLite, con cookie `HttpOnly`, `SameSite=Strict` y vencimiento de 8 horas.
- Progreso y perfil guardados por cuenta, no en `localStorage`.
- Puntuaciones, riesgo, decisiones y recompensas validados por el servidor.
- Respuestas correctas CTF omitidas de la API y del JSON público; el servidor compara los envíos.
- 11 escenarios, ramas de contención, laboratorio de contraseña local, 20 términos de glosario e insignias.
- Reporte y QR servidos por la misma aplicación. El QR contiene solo el identificador de estudiante, no su nombre ni puntos.

## Seguridad y límites

Esta configuración es para desarrollo local. El servicio se enlaza a `127.0.0.1` para que no sea accesible desde otras computadoras. No lo publiques directamente en Internet.

Para producción se necesita HTTPS detrás de un proxy correctamente configurado, `CIBERGUARD_COOKIE_SECURE=1`, secretos/respaldos gestionados, controles de abuso adicionales, verificación de correo, monitoreo y una revisión de seguridad. La limitación local de intentos de inicio de sesión no sustituye el rate limiting de un proxy de producción. El diploma de participación no es una certificación institucional verificable.

El laboratorio de contraseñas se ejecuta en el navegador y no envía ni almacena la contraseña introducida. Utiliza solamente valores ficticios.

## Pruebas del API

```powershell
python -m unittest discover -s tests -v
```
