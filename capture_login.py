"""
Captura HTTP: solo login + un rato esperando.
NO navega a COLECTIVAS (eso es lo que dispara el OOM en CI).
Importa primitivas del bot principal.
"""
import os
import time
import logging
import subprocess

import gym_bot

log = logging.getLogger(__name__)


def main():
    serial = os.environ.get("DEVICE_SERIAL", "emulator-5554")
    log.info(f"=== CAPTURE_LOGIN starting on {serial} ===")

    # Conectar uiautomator2
    device = gym_bot.connect_device(max_wait=90)
    log.info(f"u2 connected: {device.info.get('productName', '?')}")

    # Arrancar Technogym
    subprocess.run(
        [gym_bot.adb_path(), "-s", serial, "shell", "monkey", "-p",
         gym_bot.APP_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1"],
        capture_output=True, timeout=20,
    )
    log.info("App started, waiting 30s for splash...")
    time.sleep(30)

    # Login completo (el flujo que ya funciona en CI hasta el momento del OOM)
    try:
        gym_bot.login(device)
        log.info("Login finished")
    except Exception as exc:
        log.warning(f"Login raised: {exc}")

    # Dar tiempo a que la app pegue los requests post-login (refresh token,
    # me, club info, lista de clases…) — mitmproxy va capturando todo.
    # NO tocamos la UI, así no disparamos el render que mata al emulador.
    log.info("Sleeping 90s to let app finish post-login HTTP traffic...")
    for i in range(9):
        time.sleep(10)
        log.info(f"  capture progress {(i+1)*10}/90s")

    log.info("=== CAPTURE_LOGIN done ===")


if __name__ == "__main__":
    main()
