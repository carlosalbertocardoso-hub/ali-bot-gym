# Gym Bot Alicia - Handover para Claude Code

## Objetivo

Automatizar reservas de clases en la app Technogym para Alicia en el club Mercantil / Sports Center Mercantil.

Reservas deseadas:

- Domingo 22:00 -> reservar Body Tono del lunes a las 18:00
- Martes 22:00 -> reservar Body Tono del miercoles a las 18:00
- Miercoles 22:00 -> reservar POWER del jueves a las 19:00

Arquitectura prevista:

```text
Windows Task Scheduler -> python gym_bot.py -> uiautomator2/ADB -> Android Emulator -> Technogym App
```

## Carpeta y archivos

Proyecto:

```powershell
C:\Users\ccard\Proyectos\gym-bot-alicia
```

Archivos importantes:

- `gym_bot.py`: script principal.
- `test_login.py`: test rapido del login.
- `setup_tasks.ps1`: alta de tareas programadas.
- `technogym.apk`: APK antiguo, version 2.9.1 build 75. Funciona mejor, pero NO tiene la pantalla moderna de reservas.
- `technogym-3.43.2.xapk`: app moderna descargada.
- `technogym-3.43.2-xapk\`: XAPK extraido con APK base y splits.
- `screenshots\`: capturas del mapeo.
- `platform-tools\adb.exe`: ADB local.
- `jdk17\jdk-17.0.19+10`: JDK local para `sdkmanager` / `avdmanager`.

## Credenciales

Estan en `gym_bot.py`:

```python
EMAIL = "aliciaramirezcaballero@gmail.com"
PASSWORD = "gimnasio"
```

## App Technogym

Paquete:

```text
com.technogym.tgapp
```

Version moderna localizada y descargada:

- Technogym - fitness & workout
- Version `3.43.2`
- versionCode `3244`
- Publicada alrededor del 21 mayo 2026
- Fuente usada: APKPure
- Tambien localizada en APKMirror

Archivo local:

```powershell
.\technogym-3.43.2.xapk
```

Contenido extraido:

```text
technogym-3.43.2-xapk\com.technogym.tgapp.apk
technogym-3.43.2-xapk\config.arm64_v8a.apk
technogym-3.43.2-xapk\config.en.apk
technogym-3.43.2-xapk\config.xxhdpi.apk
technogym-3.43.2-xapk\config.zh.apk
technogym-3.43.2-xapk\manifest.json
```

Instalacion usada:

```powershell
.\platform-tools\adb.exe -s emulator-5554 install-multiple -r `
  .\technogym-3.43.2-xapk\com.technogym.tgapp.apk `
  .\technogym-3.43.2-xapk\config.en.apk `
  .\technogym-3.43.2-xapk\config.xxhdpi.apk `
  .\technogym-3.43.2-xapk\config.arm64_v8a.apk
```

Comprobacion:

```powershell
.\platform-tools\adb.exe -s emulator-5554 shell dumpsys package com.technogym.tgapp | Select-String -Pattern 'versionName|versionCode|primaryCpuAbi'
```

## Emuladores

### AVD malo / insuficiente

`GymBotAVD30`

- Android 11 / API 30
- `system-images;android-30;google_apis;x86_64`
- Arranca y es relativamente estable.
- Problema: Play Services viejo (`201817023`).
- Technogym 3.43.2 se queda en splash porque requiere Play Services mas nuevo (`203400000` o superior).
- El APK antiguo 2.9.1 si abre y permite login, pero solo muestra home antigua generica, no reservas modernas.

### AVD correcto a continuar

`GymBotPlayAVD`

- Android 14 / API 34
- `system-images;android-34;google_apis_playstore;x86_64`
- Google Play / Play Services incluido.
- Play Services visto: `versionCode=231818047`, `versionName=23.18.18`.
- Technogym 3.43.2 instalada y pasa del splash a la UI moderna.
- Problema actual: en modo headless va muy lento y lanza dialogos `System UI isn't responding` / `Process system isn't responding`.
- Se aumento a 4 GB RAM y 4 cores, pero sigue justo.

`gym_bot.py` ya apunta a:

```python
AVD_NAME = "GymBotPlayAVD"
DEVICE_SERIAL = "emulator-5554"
```

Arranque recomendado para pruebas:

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

Nota: para terminar el mapeo conviene arrancarlo CON ventana visible, al menos durante el primer flujo:

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

Es decir, no usar `-no-window` hasta que el bot este estable.

Comprobaciones:

```powershell
.\platform-tools\adb.exe devices -l
.\platform-tools\adb.exe -s emulator-5554 emu avd name
.\platform-tools\adb.exe -s emulator-5554 shell getprop sys.boot_completed
.\platform-tools\adb.exe -s emulator-5554 shell getprop ro.build.version.release
```

## Estado real de la UI

Capturas importantes:

- `screenshots\technogym_play_after_wait.png`: app moderna en pantalla inicial, con `CREATE ACCOUNT` y `LOG IN`.
- `screenshots\technogym_4gb_after_login_tap.png`: dialogo `System UI isn't responding`.
- `screenshots\technogym_direct_after_login_click.png`: ultima captura por ADB directo tras intentar click en login.
- Capturas antiguas de APK viejo:
  - `screenshots\home_scrolled_for_reserva_143354.png`
  - `screenshots\top_left_menu_143504.png`
  - `screenshots\settings_screen_143626.png`

La app moderna muestra:

- Logo Technogym
- Titulo `Technogym Coach`
- Boton amarillo `CREATE ACCOUNT`
- Boton oscuro `LOG IN`

El usuario corrigio que hay que pulsar `LOG IN`, no `CREATE ACCOUNT`.

Coordenadas aproximadas en 1080x1920:

- `LOG IN`: centro aprox `(540, 1710)`
- `CREATE ACCOUNT`: centro aprox `(540, 1540)`
- Dialogo ANR `Wait`: aprox `(350, 1090)`

Usar ADB si uiautomator2 se atasca:

```powershell
.\platform-tools\adb.exe -s emulator-5554 shell input tap 350 1090
.\platform-tools\adb.exe -s emulator-5554 shell input tap 540 1710
.\platform-tools\adb.exe -s emulator-5554 exec-out screencap -p > screenshots\capture.png
```

## Flujo antiguo ya mapeado

Con APK 2.9.1:

1. Compat dialog -> `OK`
2. Onboarding -> `CONTINUE`
3. Auth -> `CONNETTITI CON TECHNOGYM`
4. Login form -> `Email` -> `Password` -> `LOGIN`
5. Tutorial post-login:
   - varias pantallas `CONTINUE`
   - ultimo boton `START`
   - dialogo S Health `SKIP`
   - dialogo ubicacion `OK`
   - permiso Android `While using the app`
6. Home antigua:
   - `MOVERGY INDEX`
   - `DAILY MOVES`
   - menu lateral con `Find a club`, `Settings`, etc.

Problema: esa version no muestra `Tus citas`, `Reserva una clase` ni `COLECTIVAS`.

## Pantallas esperadas segun capturas del telefono del usuario

Home correcta del club:

- Cabecera con club: `SPORTS CENTER ...`
- Tarjeta `Tus citas`
- Boton `Reserva una clase` con icono/calendario y `+`
- Bottom tabs:
  - `Entrenador`
  - `COLECTIVAS`
  - `Explorar`
  - `Retos`
  - `Resultados`

Pantalla de reserva:

- Pestaña `Colectivas`
- Selector/filtro arriba: `Hora de inicio`
- Dias: `MIE 27`, `JUE 28`, `VIE 29`, `SAB 30`, etc.
- Lista de clases:
  - `BODYTONO`
  - `CICLO`
  - `CROSS TRAINING`
- Cada tarjeta tiene hora (`10:00`, `11:00`, `14:30`, etc.) y estado (`Completado`, `EN CURSO`, etc.).

El club correcto es Mercantil / Sports Center Mercantil en Espana.

## Problemas actuales

1. La automatizacion todavia NO reserva.
2. El script principal aun conserva mucho flujo del APK antiguo.
3. Falta mapear el login moderno de Technogym 3.43.2.
4. Falta confirmar si la cuenta queda asociada automaticamente al club Mercantil en el emulador moderno.
5. Falta mapear `Tus citas` -> `Reserva una clase` -> clase -> confirmar reserva.
6. El AVD Play Store Android 14 va muy lento en headless y lanza ANR de System UI.
7. Hay poco disco libre visto durante pruebas: unos 6-9 GB. Evitar descargar mas imagenes pesadas sin limpiar.
8. El XAPK instalado trae split `arm64_v8a`; Android 14 x86_64 lo acepto, pero puede estar usando traduccion binaria y eso explicaria parte de la lentitud. Si es posible, buscar bundle/splits con `x86_64` o usar Play Store oficial dentro del AVD.

## Siguiente plan recomendado

1. Arrancar `GymBotPlayAVD` con ventana visible y 4 GB RAM.
2. Esperar a que estabilice Android y cerrar/Wait en cualquier ANR.
3. Abrir Technogym 3.43.2.
4. Pulsar `LOG IN`.
5. Mapear campos reales del login moderno con:

```python
import uiautomator2 as u2, re
d = u2.connect("emulator-5554")
xml = d.dump_hierarchy()
print(xml)
```

6. Completar `login(device)` para:
   - detectar pantalla inicial moderna
   - pulsar `LOG IN`
   - rellenar email/password
   - aceptar permisos/dialogos
   - detectar home del club
7. Una vez en home, mapear:
   - `Reserva una clase`
   - tab `COLECTIVAS`
   - selector de dia
   - clase por nombre+hora
   - boton de confirmar reserva
8. Separar script en pasos testeables:
   - `test_login.py`
   - `test_home.py`
   - `test_book_available.py`
9. Solo al final reactivar Windows Task Scheduler con `setup_tasks.ps1`.

## Comandos utiles

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

Instalar app moderna:

```powershell
.\platform-tools\adb.exe -s emulator-5554 install-multiple -r `
  .\technogym-3.43.2-xapk\com.technogym.tgapp.apk `
  .\technogym-3.43.2-xapk\config.en.apk `
  .\technogym-3.43.2-xapk\config.xxhdpi.apk `
  .\technogym-3.43.2-xapk\config.arm64_v8a.apk
```

JDK para herramientas Android:

```powershell
$env:JAVA_HOME='C:\Users\ccard\Proyectos\gym-bot-alicia\jdk17\jdk-17.0.19+10'
```

## Cuidado

- No volver al APK viejo para terminar reservas: no tiene el flujo moderno.
- No usar `GymBotAVD30` salvo para comparar; el bueno es `GymBotPlayAVD`.
- Si el emulador se queda lento, usar ventana visible, esperar, cerrar ANR con `Wait`, y evitar reiniciar ADB en bucle.
- No probar reservas reales sin que el usuario lo sepa, salvo que haya pedido expresamente reservar una disponible.
