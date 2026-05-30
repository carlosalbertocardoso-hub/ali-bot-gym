# Gym Bot Alicia - Handover para Claude Code

## Objetivo

Automatizar la reserva o seguimiento de clases en la app Technogym para Alicia.

Reservas habituales configuradas en `gym_bot.py`:

- Domingo 22:00 -> BODYTONO del lunes a las 18:00
- Martes 22:00 -> BODYTONO del miercoles a las 18:00
- Miercoles 22:00 -> POWER del jueves a las 19:00

Pruebas manuales se lanzan con `FORCE_CLASS` / `force_class`, por ejemplo:

```text
OMNIA,09:30,6
```

El tercer campo usa `datetime.weekday()` de Python:

```text
0=lun, 1=mar, 2=mie, 3=jue, 4=vie, 5=sab, 6=dom
```

## Arquitectura Actual

Produccion actual:

```text
GitHub Actions -> Geelark cloud phone -> ADB remoto -> uiautomator2 -> Technogym app
```

El flujo antiguo con Android Emulator / `run_bot.sh` queda como referencia historica. El camino activo es `gym_bot.py` usando Geelark.

Archivos principales:

- `gym_bot.py`: script principal.
- `.github/workflows/gym-bot.yml`: cron, workflow manual y dependencias.
- `screenshots/`: capturas generadas durante runs.
- `gym_bot.log`: log del run.
- `CAPTURE_LOCAL.md`: notas/capturas locales no necesariamente versionadas.

## Credenciales y Config

Credenciales de Technogym en `gym_bot.py`:

```python
EMAIL = "aliciaramirezcaballero@gmail.com"
PASSWORD = "gimnasio"
APP_PACKAGE = "com.technogym.tgapp"
```

Credenciales Geelark por GitHub Secrets / env vars:

```text
GEELARK_APP_ID
GEELARK_API_KEY
GEELARK_PHONE_ID
```

## GitHub Actions

Workflow:

```text
.github/workflows/gym-bot.yml
```

El workflow instala:

```bash
pip install uiautomator2 requests pytesseract
sudo apt-get install -y adb tesseract-ocr
```

Motivo: el XML de uiautomator no siempre expone los textos reales de Technogym, asi que OCR es parte del flujo normal.

`workflow_dispatch` acepta:

```text
force_class = NOMBRE,HH:MM,dia_weekday
```

Ejemplos:

```text
POWER,19:00,3
OMNIA,09:30,6
```

Artefactos:

- `screenshots-{run_id}`: capturas y XML de diagnostico si existen.
- `gym-bot-log-{run_id}`: `gym_bot.log`.

## Geelark Cloud Phone

El bot resuelve el telefono, lo arranca, habilita ADB, obtiene ip/puerto/password y conecta por ADB remoto.

Estados vistos:

- `status=1`: running.
- `status=2`: arrancando.
- `status=0`: parado.
- `status=-1`: phone id no encontrado.

Cambio importante:

```python
gl.ensure_phone_running(phone_id, attempts=2, timeout=240)
```

Si el telefono se queda en `status=2`, el bot:

1. Espera hasta 240s.
2. Si no llega a running, hace `stop_phone`.
3. Espera 20s.
4. Reintenta start + wait otros 240s.

Esto evita fallos frecuentes tipo:

```text
Phone *** did not reach running status in 180s
```

## uiautomator2

No usar `python -m uiautomator2 init` en el run normal.

Motivo: en Geelark el cloud phone ya tiene u2 instalado y `u2.connect()` arranca/conecta el servidor si hace falta. El `init` se colgaba y consumia 120s.

Flujo actual:

```python
device = connect_u2(serial, max_wait=60)
```

`connect_u2()` reintenta `u2.connect(serial)` y `device.info`.

## Navegacion en Technogym

Puntos validos para entrar a reservas desde home:

1. Card `Reserva una clase`.
2. Pestaña inferior `COLECTIVAS`.

No buscar ni usar `SPORTS CENTER`, `Mercantil`, ni el nombre del club como target de navegacion. Es solo texto incidental de pantalla.

En la app del movil se ve:

- Home: `Entrenador`, tarjeta `Reserva una clase`, bottom nav `COLECTIVAS`.
- Pantalla de clases: pestaña superior `Colectivas`, filtros `Hora de inicio`, `Entrenador`, selector de dias y tarjetas.

El XML de uiautomator puede exponer textos internos diferentes o no exponer los textos visibles. Por eso la navegacion actual es OCR-first:

1. OCR busca y toca `Reserva una clase` en la zona de la card.
2. OCR busca y toca `COLECTIVAS` en bottom nav.
3. XML se usa solo como respaldo.
4. Coordenadas relativas quedan como ultimo fallback.

Fallback de coordenadas actual para la card:

```python
(x=38%, y=64%)  # zona texto/card Reserva una clase
(x=88%, y=64%)  # zona + de la misma fila
```

Fallback para bottom nav:

```python
(x=30%, y=94%)  # COLECTIVAS
```

## OCR

El OCR existe porque XML/uiautomator no detecta de forma fiable:

- `Reserva una clase`
- `COLECTIVAS`
- `Hora de inicio`
- `OMNIA`
- `9:30`
- `SEGUIR`
- `RESERVAR`
- `DEJAR DE SEGUIR`

OCR se usa para:

- Confirmar navegacion.
- Leer tarjetas de clases.
- Emparejar `nombre + hora + boton`.
- Verificar estado posterior a una accion.

El OCR prueba varias versiones:

- pantalla completa;
- recorte de zona de tarjetas;
- gris con autocontraste;
- invertida;
- invertida con umbral;
- Tesseract `--psm 11` para texto disperso.

Funciones importantes:

```python
ocr_screen_words(...)
ocr_lines(...)
find_and_tap_by_ocr(...)
tap_nav_text_by_ocr(...)
verify_action_result(...)
```

## Reglas Anti-Falso-Positivo

Muy importante: el bot no debe inventar exito.

No basta con tocar una coordenada. Despues de cualquier accion debe verificar el nuevo estado por XML u OCR.

Verificaciones actuales:

- Si toca `SEGUIR`, debe aparecer `DEJAR DE SEGUIR`.
- Si toca `RESERVAR`, debe aparecer una señal de reserva, por ejemplo `CANCELAR`, `RESERVADA`, `BOOKED`.
- Si toca `UNETE` / lista de espera, debe aparecer una señal de lista o cancelacion.

Si no se verifica:

- guarda screenshot;
- guarda hierarchy XML;
- devuelve fallo;
- no escribe `SEGUIR`, `RESERVED` ni `WAITLIST` como exito.

Funcion:

```python
verify_action_result(device, serial, result)
```

## SEGUIR vs DEJAR DE SEGUIR

En Technogym:

- Antes de seguir una clase aparece `SEGUIR`.
- Despues de seguirla debe aparecer `DEJAR DE SEGUIR`.

El log debe usar la terminologia de la app:

```text
SEGUIR verified by OCR/XML: DEJARDESEGUIR visible
SEGUIR: OMNIA 09:30
```

No usar `FOLLOWED` en mensajes al usuario/log final, aunque internamente el resultado de codigo pueda llamarse `followed`.

## Flujo Principal Actual

1. Resolver `phone_id`.
2. `ensure_phone_running()`.
3. Habilitar ADB.
4. Conectar ADB remoto con `glogin`.
5. Esperar ADB ready.
6. `connect_u2()`.
7. Encender pantalla.
8. Reiniciar app Technogym.
9. Login si hace falta.
10. Navegar a `COLECTIVAS` OCR-first.
11. Seleccionar dia.
12. Buscar tarjeta OCR-first por `nombre + hora`.
13. Tocar `SEGUIR`, `RESERVAR`, `UNETE` o detectar `CANCELAR`.
14. Verificar estado final antes de reportar exito.
15. Parar cloud phone en `finally`.

## Seleccion de Dia

`select_day()` calcula el proximo dia de clase con:

```python
days_ahead = (dia_clase - today.weekday()) % 7 or 7
```

Busca abreviatura + numero:

- `LUN`, `MAR`, `MIE/MIÉ`, `JUE`, `VIE`, `SAB/SÁB`, `DOM`
- numero de dia visible.

Si XML no expone el dia, actualmente puede fallar con:

```text
Day not found: weekday 6
```

No debe abortar automaticamente por eso si ya esta en la pantalla correcta; la tarjeta aun puede estar visible.

## FORCE_CLASS

`FORCE_CLASS` tiene formato:

```text
NOMBRE,HH:MM,dia_weekday
```

Ejemplos:

```text
OMNIA,09:30,6
BODYTONO,18:00,0
POWER,19:00,3
```

El bot acepta variantes de hora:

```text
09:30 == 9:30
```

Funcion:

```python
time_variants(hora)
```

## Logs Importantes

Buscar estas lineas:

```text
Geelark start attempt
Phone status code
u2 connected
--- NAVIGATE TO COLECTIVAS ---
OCR nav tapping
Navigation confirmed by OCR marker
--- BOOK: ...
OCR words
OCR matches
OCR tapping
SEGUIR verified
RESERVAR verified
not verified
```

Si aparece:

```text
Phone status code: 2
Phone did not reach running status
```

El fallo es Geelark/arranque del cloud phone, no Technogym ni OCR.

Si aparece:

```text
OCR matches: time=[], name=[], actions=[]
```

OCR no esta leyendo la tarjeta. Revisar screenshots del artifact.

## Estado de Pruebas Recientes

Cambios recientes ya pusheados:

- Quitado `uiautomator2 init`.
- Navegacion OCR-first para `Reserva una clase` y `COLECTIVAS`.
- OCR-first para tarjetas de reserva.
- Verificacion obligatoria antes de reportar exito.
- Logs usan `SEGUIR`, no `FOLLOWED`.
- Eliminadas referencias a `SPORTS CENTER` como indicador/target.
- Reintento de arranque Geelark si el phone queda en `status=2`.

Ultimo objetivo de prueba usado:

```text
OMNIA,09:30,6
```

Hubo un run que reporto `SEGUIR` por fallback visual, pero el movil del usuario no lo reflejo. Se corrigio para no reportar exito si no aparece `DEJAR DE SEGUIR`.

## Pendientes Reales

1. Validar un run donde el cloud phone arranque correctamente y OCR-first navegue por `Reserva una clase` o `COLECTIVAS`.
2. Confirmar que OCR lee la tarjeta de clase (`OMNIA`, `9:30`, `SEGUIR`).
3. Confirmar que tras tocar `SEGUIR` aparece `DEJAR DE SEGUIR`.
4. Si OCR sigue sin leer tarjetas, descargar artifact `screenshots-{run_id}` y ajustar preprocesado/recorte.
5. Para reservas reales, verificar `RESERVAR -> CANCELAR/RESERVADA`.

## Comandos Utiles Locales

Compilar sintaxis:

```powershell
python -m py_compile .\gym_bot.py
```

Ver estado git:

```powershell
git status --short --branch
```

Buscar logs locales:

```powershell
Get-Content .\gym_bot.log -Tail 200
```

ADB basico:

```powershell
adb devices
adb shell getprop sys.boot_completed
adb shell monkey -p com.technogym.tgapp 1
```

## Cuidado

- No usar `SPORTS CENTER` / `Mercantil` como target de navegacion.
- No declarar exito sin verificar estado posterior.
- No usar coordenadas fijas como exito; solo como ultimo fallback para intentar navegar.
- No reinstalar ni hacer `uiautomator2 init` en cada run Geelark.
- No probar reservas reales salvo que el usuario lo pida expresamente.
- Los archivos locales grandes (`android-tools/`, APKs extraidos, etc.) pueden estar sin trackear y no deben meterse en commits salvo peticion expresa.
