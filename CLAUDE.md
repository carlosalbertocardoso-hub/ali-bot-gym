# Gym Bot Alicia - Handover para Claude Code

## Objetivo

Automatizar reservas de clases en la app Technogym para Alicia en el club Mercantil / Sports Center Mercantil.

Reservas deseadas:

- Domingo 22:00 -> reservar Body Tono del lunes a las 18:00
- Martes 22:00 -> reservar Body Tono del miercoles a las 18:00
- Miercoles 22:00 -> reservar POWER del jueves a las 19:00

Arquitectura actual (producción):

```text
GitHub Actions (cron schedule) -> run_bot.sh -> Android Emulator (CI) -> uiautomator2/ADB -> Technogym App
```

Arquitectura local (desarrollo):

```text
Windows Task Scheduler -> python gym_bot.py -> uiautomator2/ADB -> Android Emulator -> Technogym App
```

## Carpeta y archivos

Proyecto:

```powershell
C:\Users\ccard\Proyectos\gym-bot-alicia
```

Archivos importantes:

- `gym_bot.py`: script principal con toda la lógica de automatización.
- `run_bot.sh`: script de arranque para GitHub Actions (instala APK, init uiautomator2, lanza bot).
- `.github/workflows/gym-bot.yml`: workflow de GitHub Actions con cron y `workflow_dispatch`.
- `test_login.py`: test rápido del login.
- `setup_tasks.ps1`: alta de tareas programadas en Windows.
- `technogym.apk`: APK antiguo 2.9.1. NO tiene flujo moderno de reservas. No usar.
- `technogym-3.43.2.xapk`: app moderna descargada.
- `technogym-3.43.2-xapk\`: XAPK extraído con APK base y splits.
- `screenshots\`: capturas del mapeo.
- `platform-tools\adb.exe`: ADB local.
- `jdk17\jdk-17.0.19+10`: JDK local para `sdkmanager` / `avdmanager`.

## Credenciales

Están en `gym_bot.py`:

```python
EMAIL = "aliciaramirezcaballero@gmail.com"
PASSWORD = "gimnasio"
```

## App Technogym

Paquete:

```text
com.technogym.tgapp
```

Version moderna:

- Technogym - fitness & workout
- Version `3.43.2`
- versionCode `3244`
- Publicada alrededor del 21 mayo 2026
- Fuente usada: APKPure / APKMirror

Archivo local:

```powershell
.\technogym-3.43.2.xapk
```

Contenido extraído:

```text
technogym-3.43.2-xapk\com.technogym.tgapp.apk
technogym-3.43.2-xapk\config.arm64_v8a.apk
technogym-3.43.2-xapk\config.en.apk
technogym-3.43.2-xapk\config.xxhdpi.apk
technogym-3.43.2-xapk\config.zh.apk
technogym-3.43.2-xapk\manifest.json
```

Instalación:

```powershell
.\platform-tools\adb.exe -s emulator-5554 install-multiple -r `
  .\technogym-3.43.2-xapk\com.technogym.tgapp.apk `
  .\technogym-3.43.2-xapk\config.en.apk `
  .\technogym-3.43.2-xapk\config.xxhdpi.apk `
  .\technogym-3.43.2-xapk\config.arm64_v8a.apk
```

## Emuladores

### AVD malo / insuficiente

`GymBotAVD30`

- Android 11 / API 30
- `system-images;android-30;google_apis;x86_64`
- Problema: Play Services viejo (`201817023`). Technogym 3.43.2 se queda en splash.

### AVD correcto

`GymBotPlayAVD`

- Android 14 / API 34
- `system-images;android-34;google_apis_playstore;x86_64`
- Play Services: `versionCode=231818047`, `versionName=23.18.18`.
- Technogym 3.43.2 pasa del splash a la UI moderna.
- Problema: en modo headless va lento y puede lanzar ANR de System UI / Pixel Launcher. Se usa 4 GB RAM en CI.

Nota 2026-05-28: se probó `system-images;android-34;google_apis;x86_64` para evitar ANRs. El emulador arrancó más limpio, pero Technogym no expuso correctamente el onboarding/login: uiautomator solo veía el reloj y no aparecía el campo email. Se revirtió a `google_apis_playstore`, que sigue siendo el target correcto para esta app.

`gym_bot.py` apunta a:

```python
AVD_NAME = "GymBotPlayAVD"
DEVICE_SERIAL = "emulator-5554"
```

Arranque local para pruebas (con ventana visible):

```powershell
Start-Process -FilePath "$env:LOCALAPPDATA\Android\Sdk\emulator\emulator.exe" `
  -ArgumentList @(
    '-avd','GymBotPlayAVD',
    '-no-audio',
    '-gpu','swiftshader_indirect',
    '-memory','4096',
    '-cores','4',
    '-port','5554',
    '-no-snapshot-load',
    '-no-metrics'
  )
```

No usar `-no-window` hasta que el bot esté estable.

Comprobaciones:

```powershell
.\platform-tools\adb.exe devices -l
.\platform-tools\adb.exe -s emulator-5554 shell getprop sys.boot_completed
.\platform-tools\adb.exe -s emulator-5554 shell getprop ro.build.version.release
```

## GitHub Actions

### Workflow: `.github/workflows/gym-bot.yml`

Cron schedules (UTC, = 21:40 Madrid hora de verano):

- Domingo 19:40 UTC → reserva Body Tono lunes 18:00
- Martes 19:40 UTC → reserva Body Tono miércoles 18:00
- Miércoles 19:40 UTC → reserva POWER jueves 19:00

El workflow también acepta `workflow_dispatch` con input `force_class`.

### run_bot.sh

Detecta serial del emulador dinámicamente (no hardcodeado), instala APK, inicia uiautomator2, lanza `gym_bot.py`:

```bash
SERIAL=$(adb devices | grep emulator | awk '{print $1}' | head -1)
adb -s "$SERIAL" install-multiple -r technogym-3.43.2-xapk/...
python -m uiautomator2 init -s "$SERIAL"
DEVICE_SERIAL="$SERIAL" python gym_bot.py
```

### Git LFS

Los binarios APK están en Git LFS. El workflow usa `actions/checkout@v4` con `lfs: true`.

### Artefactos en caso de fallo

- `screenshots/` + `login_failed_hierarchy.xml` → artifact `screenshots-{run_id}` (7 días)
- `gym_bot.log` → artifact `gym-bot-log-{run_id}` (30 días)
- Capturas útiles recientes:
  - `blind_login_fallback_*.png`: antes de tocar LOG IN por coordenadas cuando uiautomator no ve la pantalla inicial.
  - `login_form_not_found_*.png`: cuando se cree estar en formulario pero no aparece el campo email.
  - `after_adb_type_*.png`: después de escribir texto por ADB, para confirmar foco/teclado.

### Test manual

Lanzar desde GitHub Actions > "Gym Bot Reserva" > "Run workflow" con el campo `force_class` relleno, por ejemplo:

```
CICLO,18:00,3
```

Formato: `NOMBRE,HH:MM,dia_weekday` donde `dia_weekday` es el weekday Python de la clase (0=lun, 1=mar, 2=mié, 3=jue, 4=vie, 5=sáb, 6=dom).

Equivale a `FORCE_CLASS` env var en el bot. Salta la comprobación de hora y día.

**IMPORTANTE**: El campo en el formulario GitHub Actions es el texto que aparece bajo "Forzar clase". Hay que teclearlo explícitamente — si se deja vacío, `FORCE_CLASS` llega vacía y el bot usa el modo cron normal.

La variable `FORCE_CLASS` está declarada a nivel de **job** (no de step) para garantizar que el subproceso del emulador la hereda:

```yaml
jobs:
  reserva:
    env:
      FORCE_CLASS: ${{ github.event.inputs.force_class }}
```

## Estado de gym_bot.py

### Flujo completo implementado

1. `ensure_emulator()` — arranca el AVD si no está online
2. `u2.connect()` + retry loop (10×3s) — espera a que el servidor uiautomator2 esté listo para JSON-RPC
3. `login(device)` — detecta pantalla inicial → pulsa LOG IN → rellena email/password → espera home del club
4. `navigate_to_colectivas(device)` — va al tab COLECTIVAS; si no es visible, usa "Reserva una clase" como puerta de entrada
5. `book_class_with_refresh(device, clase)` — espera hasta 3 min refrescando cada 5s, llama a `find_card_and_book`
6. `find_card_and_book(device, nombre, hora)` — parsea XML, detecta RESERVAR / CANCELAR / ÚNETE, hace tap

### Conexión uiautomator2 — retry loop

Tras `u2.connect()`, el servidor HTTP en el emulador puede tardar varios segundos en aceptar peticiones JSON-RPC. El bot reintenta hasta 10 veces con 3s de pausa antes de abortar:

```python
device = u2.connect(DEVICE_SERIAL)
for _attempt in range(10):
    try:
        info = device.info
        log.info(f"Connected: {info.get('productName', '?')}")
        break
    except Exception:
        log.info("Waiting for uiautomator2 server to be ready...")
        time.sleep(3)
else:
    log.error("uiautomator2 server never became ready — aborting")
    return
```

### Login — resource-ids mapeados

- Pantalla inicial: `onboarding.alreadySignedIn.button` = botón LOG IN
- Campo email: `loginPage.username.textfield`
- Campo password: `loginPage.password.textfield`
- Botón login: `loginPage.login.button`
- Fallback ADB tap LOG IN: coordenadas `(540, 1710)` en 1080x1920
- Si la pantalla inicial no está expuesta a uiautomator y solo se ve el reloj, `login()` prueba ese fallback en los intentos 5, 10 y 15.

### Login — entrada de texto en Android 14

No usar `device.send_keys(...)` para email/password en Android 14 / API 34.

Fallo visto en CI el 28 mayo 2026:

```text
uiautomator2.exceptions.RPCUnknownError: java.lang.SecurityException:
Package android does not belong to 2000
uiautomator2.exceptions.InputIMEError: install AdbKeyboard ime failed
```

Causa: `uiautomator2.send_keys` intenta usar clipboard y, si falla, instalar/activar `AdbKeyboard`. En Android 14 el acceso al clipboard desde el proceso de uiautomator puede fallar con `SecurityException`.

Solución actual en `gym_bot.py`:

```python
enter_text(device, field, text)
```

El helper no usa `device.send_keys`, clipboard ni `AdbKeyboard`. Tampoco depende ya de `field.set_text`.

Secuencia actual:

1. Espera a que no haya ANR (`wait_for_no_anr`).
2. Trae Technogym al foreground con `monkey -p com.technogym.tgapp`.
3. Enfoca y limpia el campo.
4. Escribe con ADB:
   - trozos alfanuméricos con `adb shell input text ...`
   - `@` con `KEYCODE_AT`
   - `.` con `KEYCODE_PERIOD`
5. Vuelve a leer el campo si `verify=True`.

```bash
adb shell input text ...
```

El login llama a `enter_text(device, email_el, EMAIL)` y `enter_text(device, pw_el, PASSWORD)`.

Si el campo sigue vacío, mirar en los artifacts `after_adb_type_loginPage.username.textfield*.png`, `login_failed_hierarchy.xml` y `gym_bot.log` para saber si el problema es foco, overlay/ANR o que la pantalla real no es el formulario.

### Post-login detection (bucle de 20 iteraciones)

Después de pulsar login, el bot espera hasta 20×3s = ~60s para que aparezca la home del club.
Indicadores reconocidos:

```python
HOME_INDICATORS = ["COLECTIVAS", "Colectivas", "Reserva una clase", "Tus citas",
                   "Entrenador", "Explorar", "MOVERGY", "Tus planes"]
```

En cada iteración: descarta ANR, loguea los textos visibles, descarta diálogos (CONTINUE, SKIP, OK, Allow, etc.).
Si falla tras 20 intentos: captura screenshot `login_failed` + guarda XML en `login_failed_hierarchy.xml`.

PENDIENTE: Validar en CI con run manual. Los logs "Post-login iter X/20 texts: [...]" mostrarán qué ve el bot.

### Weekday en Python vs cron

El campo `dia_reserva`/`dia_clase` en `CLASES` y en `FORCE_CLASS` usa `datetime.weekday()`:
- 0=lun, 1=mar, 2=mié, 3=jue, 4=vie, 5=sáb, 6=dom

Diferente del cron de GitHub Actions donde 0=dom, 7=dom.

### Navegación a COLECTIVAS

```python
def navigate_to_colectivas(device):
    # 1. Intenta tab COLECTIVAS en bottom nav
    # 2. Si no: pulsa "Reserva una clase" (botón en home, confirmado por screenshot del usuario)
    #    y luego busca tab COLECTIVAS desde ahí
```

### Reserva con refresco

```python
def book_class_with_refresh(device, clase):
    # Loop 3 min, pull-to-refresh + re-selección de día cada 5s
    # Llama a find_card_and_book que parsea XML
    # Maneja estados: 'booked', 'already', 'waitlist', 'full'
```

### Selección de día

Calcula fecha exacta (dias_ahead desde hoy), busca etiqueta+número en XML (ej. "JUE 29"), fallback solo abreviatura. Maneja acentos: MIÉ/MIE, SÁB/SAB.

### FORCE_CLASS

Variable de entorno `FORCE_CLASS="NOMBRE,HH:MM,dia_weekday"` salta comprobación de hora/día.

Ejemplo: `FORCE_CLASS=POWER,19:00,3` reserva POWER 19:00 el próximo jueves.

En CI: si `FORCE_CLASS` no está presente y es el turno de cron, el bot espera en COLECTIVAS hasta las 22:00 Madrid (20:00 UTC) antes de intentar la reserva.

## Pantallas de la app (mapeadas por usuario)

Home del club:

- Cabecera: `SPORTS CENTER ...`
- Tarjeta `Tus citas`
- Botón `Reserva una clase` (icono calendario + `+`) — **este es el botón correcto para entrar a reservas**
- Bottom tabs: `Entrenador`, `COLECTIVAS`, `Explorar`, `Retos`, `Resultados`

Pantalla COLECTIVAS:

- Selector de días horizontal: `MIE 27`, `JUE 28`, `VIE 29`, etc.
- Lista de tarjetas con nombre de clase, hora y botón de estado (RESERVAR / CANCELAR / ÚNETE)

## Estado actual / pendientes

Último commit conocido empujado antes de esta nota:

```text
9b87d69 Restore Play Store emulator for Technogym login
```

Estado real a 2026-05-28:

1. **El target correcto vuelve a ser `google_apis_playstore`**: el ensayo con `google_apis` quitó parte de la inestabilidad, pero no mostró el onboarding/login de Technogym.
2. **Login todavía pendiente de un CI verde**: el fallo inicial de `send_keys`/`AdbKeyboard` está mitigado con escritura ADB por chunks, pero los últimos runs fallaron antes de validar un login completo.
3. **ANR mejor gestionado**: `dismiss_anr()` busca botones reales `Wait` / `Esperar` y los toca por bounds; si no puede, usa fallback aproximado `(725, 1090)`.
4. **Pantalla inicial parcialmente oculta a uiautomator**: cuando solo aparece el reloj, `login()` hace fallback de tap en LOG IN `(540, 1710)` y guarda capturas `blind_login_fallback_*.png`.
5. **Post-login detection no validada en CI**: los 20 intentos (×3s) deberían bastar, pero falta confirmar qué textos aparecen tras login.
6. **Flujo de reserva no validado end-to-end**: el código está implementado pero aún no ha llegado a hacer click en RESERVAR con éxito en CI.
7. **Nombre real de la clase CICLO**: puede ser "Ciclo", "Cycling", "Indoor Cycling" u otro. Se sabrá cuando `find_card_and_book` llegue a la lista de clases. La búsqueda es case-insensitive (`nombre.upper() in l.upper()`).
8. **Split arm64_v8a en x86_64**: el emulador puede estar usando traducción binaria, explicando parte de la lentitud.
9. **Cuenta/club**: no confirmado que la cuenta quede automáticamente asociada al club Mercantil en el emulador; podría requerir configuración manual la primera vez.

Siguiente diagnóstico recomendado si falla otro run:

1. Revisar `gym_bot.log`.
2. Abrir `login_failed_hierarchy.xml`.
3. Comparar las capturas `blind_login_fallback_*.png`, `login_form_not_found_*.png` y `after_adb_type_*.png`.
4. Si el campo email existe pero queda vacío, el problema es foco/input.
5. Si el campo email no existe, el problema sigue siendo onboarding/renderizado/ANR, no la escritura de texto.

## Comandos útiles

Inicializar uiautomator2:

```powershell
python -m uiautomator2 init -s emulator-5554
```

Arrancar app:

```powershell
.\platform-tools\adb.exe -s emulator-5554 shell monkey -p com.technogym.tgapp 1
```

Limpiar datos app:

```powershell
.\platform-tools\adb.exe -s emulator-5554 shell pm clear com.technogym.tgapp
```

Captura sin uiautomator:

```powershell
.\platform-tools\adb.exe -s emulator-5554 exec-out screencap -p > screenshots\capture.png
```

Logcat filtrado:

```powershell
.\platform-tools\adb.exe -s emulator-5554 logcat -d -t 500 |
  Select-String -Pattern 'technogym|tgapp|FATAL|AndroidRuntime|Exception|ANR|GooglePlayServices|Flutter|WebView' -CaseSensitive:$false
```

Dump de jerarquía UI:

```python
import uiautomator2 as u2
d = u2.connect("emulator-5554")
print(d.dump_hierarchy())
```

JDK para herramientas Android:

```powershell
$env:JAVA_HOME='C:\Users\ccard\Proyectos\gym-bot-alicia\jdk17\jdk-17.0.19+10'
```

## Cuidado

- No volver al APK viejo (2.9.1): no tiene el flujo moderno de reservas.
- No usar `GymBotAVD30` salvo para comparar; el bueno es `GymBotPlayAVD`.
- Si el emulador se queda lento, usar ventana visible, esperar, cerrar ANR con `Wait`.
- No probar reservas reales sin que el usuario lo sepa, salvo que haya pedido expresamente reservar una disponible.
- Los archivos APK están en Git LFS; cualquier `git clone` nuevo necesita `git lfs pull`.
