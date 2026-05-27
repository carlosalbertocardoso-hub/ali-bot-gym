# Gym Bot Alicia

Bot local para reservar clases dirigidas en Technogym usando Android Emulator, ADB y `uiautomator2`.

## Objetivo

- Domingo 22:00 -> Body Tono lunes 18:00
- Martes 22:00 -> Body Tono miercoles 18:00
- Miercoles 22:00 -> POWER jueves 19:00

Club objetivo: Mercantil / Sports Center Mercantil.

## Estado

El bot aun no esta terminado. Ya se instalo la app moderna Technogym `3.43.2`, pero falta mapear login moderno y flujo de reserva.

El APK antiguo `technogym.apk` abre y permite login, pero no muestra la pantalla moderna de reservas. No debe usarse para terminar el bot.

## Requisitos

```powershell
pip install uiautomator2 pillow
```

Inicializar agente:

```powershell
python -m uiautomator2 init -s emulator-5554
```

## Emulador recomendado

AVD:

```text
GymBotPlayAVD
```

Imagen:

```text
system-images;android-34;google_apis_playstore;x86_64
```

Arranque recomendado para depurar:

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

Para automatizacion final se puede probar con `-no-window`, pero durante el mapeo conviene usar ventana visible porque Android 14 Play Store va lento en este equipo.

## App

Paquete:

```text
com.technogym.tgapp
```

Version moderna local:

```text
technogym-3.43.2.xapk
```

Instalar:

```powershell
.\platform-tools\adb.exe -s emulator-5554 install-multiple -r `
  .\technogym-3.43.2-xapk\com.technogym.tgapp.apk `
  .\technogym-3.43.2-xapk\config.en.apk `
  .\technogym-3.43.2-xapk\config.xxhdpi.apk `
  .\technogym-3.43.2-xapk\config.arm64_v8a.apk
```

Abrir app:

```powershell
.\platform-tools\adb.exe -s emulator-5554 shell monkey -p com.technogym.tgapp 1
```

## Tests

Login:

```powershell
python .\test_login.py
```

Script principal:

```powershell
python .\gym_bot.py
```

Nota: `gym_bot.py` solo actua a las 22:00 y si ese dia hay reserva programada.

## Capturas utiles

Las capturas estan en:

```text
screenshots\
```

Capturas destacadas:

- `technogym_play_after_wait.png`: pantalla moderna inicial con `CREATE ACCOUNT` y `LOG IN`.
- `technogym_4gb_after_login_tap.png`: ejemplo de ANR del emulador.
- `technogym_direct_after_login_click.png`: intento de click directo en `LOG IN`.

## Problemas conocidos

- `GymBotAVD30` tiene Play Services viejo y Technogym 3.43.2 se queda en splash.
- `GymBotPlayAVD` abre la app moderna, pero puede mostrar `System UI isn't responding`.
- El flujo moderno de login no esta terminado.
- El flujo de reserva real aun no esta mapeado.
- Hay poco disco libre; evitar descargar mas imagenes de Android sin limpiar.

Ver `CLAUDE.md` para el traspaso tecnico completo.
