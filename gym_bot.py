"""
Gym Bot — Reserva automática de clases en Technogym
=====================================================
Programado vía Windows Task Scheduler:
- Domingo 22:00  → Body Tono lunes 18:00
- Martes 22:00   → Body Tono miércoles 18:00
- Miércoles 22:00 → POWER jueves 19:00

Ejecutar: python gym_bot.py
"""
import uiautomator2 as u2
import time
import logging
import os
import re
import subprocess
from datetime import datetime

# ============================================================
# CONFIGURACIÓN
# ============================================================
EMAIL = "aliciaramirezcaballero@gmail.com"
PASSWORD = "gimnasio"
APP_PACKAGE = "com.technogym.tgapp"
DEVICE_SERIAL = "emulator-5554"
AVD_NAME = "GymBotPlayAVD"
BASE_DIR = os.path.dirname(__file__)

if os.name == "nt":
    LOCAL_ADB = os.path.join(BASE_DIR, "platform-tools", "adb.exe")
    SDK_ADB = os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\platform-tools\adb.exe")
    EMULATOR_EXE = os.path.expandvars(r"%LOCALAPPDATA%\Android\Sdk\emulator\emulator.exe")
else:
    LOCAL_ADB = "adb"
    SDK_ADB = "adb"
    EMULATOR_EXE = "emulator"

# dia_reserva = weekday() en que se lanza el bot (0=lun…6=dom)
# dia_clase   = weekday() de la clase a reservar
CLASES = [
    {"nombre": "BODYTONO", "hora": "18:00", "dia_clase": 0, "dia_reserva": 6},
    {"nombre": "BODYTONO", "hora": "18:00", "dia_clase": 2, "dia_reserva": 1},
    {"nombre": "POWER",    "hora": "19:00", "dia_clase": 3, "dia_reserva": 2},
]

LOG_FILE = os.path.join(BASE_DIR, "gym_bot.log")
SCREENSHOT_DIR = os.path.join(BASE_DIR, "screenshots")
os.makedirs(SCREENSHOT_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
log = logging.getLogger(__name__)

# ============================================================
# ADB / EMULADOR
# ============================================================

def adb_path():
    for path in (LOCAL_ADB, SDK_ADB, "adb"):
        if path == "adb" or os.path.exists(path):
            return path
    return "adb"


def run_adb(*args, timeout=20):
    cmd = [adb_path(), "-s", DEVICE_SERIAL, *args]
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def emulator_is_online():
    try:
        result = subprocess.run([adb_path(), "devices"], capture_output=True, text=True, timeout=10)
    except Exception:
        return False
    return f"{DEVICE_SERIAL}\tdevice" in result.stdout


def android_is_ready():
    if not emulator_is_online():
        return False
    try:
        result = run_adb("shell", "getprop", "sys.boot_completed", timeout=10)
    except Exception:
        return False
    return result.returncode == 0 and result.stdout.strip() == "1"


def stop_broken_emulator():
    try:
        run_adb("emu", "kill", timeout=10)
        time.sleep(5)
    except Exception as exc:
        log.info(f"Could not stop emulator cleanly: {exc}")


def ensure_emulator():
    if android_is_ready():
        log.info(f"Emulator already ready: {DEVICE_SERIAL}")
        return

    if emulator_is_online():
        log.info("Emulator online but Android not ready — restarting")
        stop_broken_emulator()

    if not os.path.exists(EMULATOR_EXE):
        raise FileNotFoundError(f"emulator.exe not found: {EMULATOR_EXE}")

    log.info(f"Starting emulator {AVD_NAME} (4 GB, 4 cores)...")
    subprocess.Popen(
        [
            EMULATOR_EXE,
            "-avd", AVD_NAME,
            "-no-window",
            "-no-audio",
            "-gpu", "swiftshader_indirect",
            "-memory", "4096",
            "-cores", "4",
            "-port", "5554",
            "-no-snapshot-load",
            "-no-metrics",
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    deadline = time.time() + 240
    while time.time() < deadline:
        if android_is_ready():
            log.info("Emulator ready")
            run_adb("shell", "input", "keyevent", "KEYCODE_WAKEUP", timeout=10)
            time.sleep(5)  # let Play Services settle
            return
        time.sleep(5)
    raise TimeoutError(f"Emulator did not come online: {DEVICE_SERIAL}")


def grant_app_permissions():
    for permission in (
        "android.permission.ACCESS_FINE_LOCATION",
        "android.permission.ACCESS_COARSE_LOCATION",
    ):
        try:
            run_adb("shell", "pm", "grant", APP_PACKAGE, permission, timeout=10)
        except Exception:
            pass


# ============================================================
# UI HELPERS
# ============================================================

def screenshot(device, name):
    path = os.path.join(SCREENSHOT_DIR, f"{name}_{datetime.now():%H%M%S}.png")
    try:
        device.screenshot(path)
    except Exception:
        run_adb("exec-out", "screencap", "-p", timeout=10)
    return path


def get_texts(device):
    xml = device.dump_hierarchy()
    return [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]


def tap_adb(x, y):
    """Tap directo por ADB cuando uiautomator2 no responde."""
    run_adb("shell", "input", "tap", str(x), str(y), timeout=10)
    time.sleep(1)


def dismiss_anr(device):
    """Descarta diálogos ANR 'System UI isn't responding' / 'Process system isn't responding'."""
    xml = device.dump_hierarchy()
    if "isn't responding" in xml or "not responding" in xml.lower():
        log.info("ANR detected — tapping Wait")
        # Coordenadas del botón Wait en 1080x1920
        tap_adb(350, 1090)
        time.sleep(3)
        return True
    return False


def wait_for_text(device, *texts, timeout=10):
    """Espera hasta que alguno de los textos sea visible."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        dismiss_anr(device)
        visible = get_texts(device)
        for t in texts:
            if any(t.lower() in v.lower() for v in visible):
                return t
        time.sleep(1)
    return None


def click_text(device, text, timeout=8):
    """Espera a que aparezca un elemento por texto y lo pulsa."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        dismiss_anr(device)
        el = device(textContains=text)
        if el.exists:
            el.click()
            log.info(f"  Clicked: {text}")
            time.sleep(2)
            return True
        time.sleep(0.5)
    log.info(f"  Not found: {text}")
    return False


def click_if_present(device, *texts, timeout=2):
    for text in texts:
        if click_text(device, text, timeout=timeout):
            return text
    return None


# ============================================================
# LOGIN
# ============================================================

def login(device):
    log.info("--- LOGIN ---")
    screenshot(device, "login_start")
    time.sleep(4)

    # Descartar cualquier diálogo inicial hasta que veamos la pantalla de inicio
    for _ in range(12):
        dismiss_anr(device)
        texts = get_texts(device)
        log.info(f"Login loop texts: {texts[:6]}")

        # Ya estamos en la home del club
        if any(t in texts for t in ["COLECTIVAS", "Colectivas", "Reserva una clase", "Tus citas"]):
            log.info("Already at club home — skipping login")
            return True

        # Pantalla inicial moderna — botón LOG IN por resource-id
        login_btn = device(resourceId="onboarding.alreadySignedIn.button")
        if login_btn.exists:
            log.info("Initial screen detected — tapping LOG IN")
            login_btn.click()
            time.sleep(4)
            break

        if any("LOG IN" in t or "Log in" in t for t in texts):
            log.info("Initial screen (text fallback) — tapping LOG IN")
            if not click_text(device, "LOG IN", timeout=5):
                tap_adb(540, 1710)
            time.sleep(4)
            break

        # Descartar diálogos de onboarding / permisos
        dismissed = click_if_present(device, "OK", "CONTINUE", "SKIP", "Allow",
                                     "While using the app", timeout=1)
        if dismissed:
            continue

        time.sleep(2)

    # Rellenar formulario de login
    time.sleep(3)
    screenshot(device, "login_form")
    texts = get_texts(device)
    log.info(f"Login form texts: {texts[:10]}")

    # El formulario puede usar placeholders "Email" / "Password"
    # o campos vacíos identificables por resource-id
    filled = False
    for attempt in range(3):
        dismiss_anr(device)

        email_el = device(resourceId="loginPage.username.textfield")
        if email_el.exists:
            email_el.click()
            time.sleep(1)
            email_el.set_text(EMAIL)
            log.info(f"Email entered: {EMAIL}")

            pw_el = device(resourceId="loginPage.password.textfield")
            pw_el.click()
            time.sleep(1)
            pw_el.set_text(PASSWORD)
            log.info("Password entered")

            device.press("enter")
            time.sleep(2)
            filled = True
            break

        time.sleep(2)

    if not filled:
        log.warning("Could not find login form fields")
        screenshot(device, "login_form_not_found")
        return False

    # Pulsar botón de login
    login_btn = device(resourceId="loginPage.login.button")
    if login_btn.exists:
        login_btn.click()
        log.info("  Clicked login button")
    else:
        click_if_present(device, "LOG IN", "LOGIN", "Log in", timeout=6)

    log.info("Waiting for login to complete...")
    time.sleep(8)
    screenshot(device, "after_login")

    # Descartar posibles diálogos post-login (permisos, tutorial)
    for _ in range(6):
        dismiss_anr(device)
        texts = get_texts(device)
        if any(t in texts for t in ["COLECTIVAS", "Colectivas", "Reserva una clase", "Tus citas",
                                     "Entrenador", "Explorar"]):
            log.info("Club home reached")
            return True
        click_if_present(device, "CONTINUE", "SKIP", "OK", "Allow",
                         "While using the app", "START", timeout=2)
        time.sleep(2)

    log.warning("Login may have failed — could not find club home")
    screenshot(device, "login_failed")
    return False


# ============================================================
# NAVEGACIÓN Y RESERVA
# ============================================================

def navigate_to_colectivas(device):
    """Pulsa el tab COLECTIVAS del bottom navigation."""
    log.info("--- NAVIGATE TO COLECTIVAS ---")
    time.sleep(2)

    # El tab puede llamarse "COLECTIVAS" o "Colectivas"
    if click_text(device, "COLECTIVAS", timeout=5) or click_text(device, "Colectivas", timeout=3):
        time.sleep(3)
        screenshot(device, "colectivas_screen")
        return True

    # Si no está visible, intentar desde "Reserva una clase"
    if click_text(device, "Reserva una clase", timeout=5):
        time.sleep(3)
        screenshot(device, "reserva_screen")
        return True

    log.warning("Could not navigate to COLECTIVAS")
    screenshot(device, "nav_failed")
    return False


def select_day(device, dia_clase):
    """Selecciona el día correcto en el selector horizontal de días."""
    log.info(f"--- SELECT DAY: weekday {dia_clase} ---")
    DAY_LABELS = {0: "LUN", 1: "MAR", 2: "MIÉ", 3: "JUE", 4: "VIE", 5: "SÁB", 6: "DOM"}
    # También en inglés por si la app está en inglés
    DAY_LABELS_EN = {0: "MON", 1: "TUE", 2: "WED", 3: "THU", 4: "FRI", 5: "SAT", 6: "SUN"}

    label_es = DAY_LABELS[dia_clase]
    label_en = DAY_LABELS_EN[dia_clase]

    # Buscar celda que contenga el label del día (puede ser "LUN 25", "LUN\n25", etc.)
    for label in (label_es, label_en):
        el = device(textContains=label)
        if el.exists:
            el.click()
            log.info(f"  Selected day: {label}")
            time.sleep(2)
            return True

    log.warning(f"Day not found: {label_es}")
    return False


def book_class(device, clase):
    """Reserva una clase específica en la pantalla de COLECTIVAS."""
    nombre = clase["nombre"]
    hora = clase["hora"]
    dia = clase["dia_clase"]

    log.info(f"--- BOOK: {nombre} {hora} (weekday {dia}) ---")

    if not select_day(device, dia):
        log.warning("Could not select day")
        screenshot(device, "day_not_found")
        return False

    time.sleep(2)
    screenshot(device, "day_selected")

    # Buscar la tarjeta de la clase por nombre
    if not click_text(device, nombre, timeout=8):
        log.warning(f"Class not found: {nombre}")
        screenshot(device, "class_not_found")
        return False

    time.sleep(2)
    screenshot(device, "class_selected")

    # En algunas vistas la hora aparece dentro de la tarjeta; en otras hay que entrar y confirmar
    # Intentar buscar la hora concreta si hay varias sesiones del mismo nombre
    hora_el = device(textContains=hora)
    if hora_el.exists:
        hora_el.click()
        log.info(f"  Selected time slot: {hora}")
        time.sleep(2)

    # Confirmar reserva
    booked = click_if_present(device, "RESERVAR", "Reservar", "BOOK", "Book",
                               "CONFIRMAR", "Confirmar", "Confirm", "OK", timeout=6)
    if booked:
        log.info(f"RESERVED: {nombre} {hora}")
        time.sleep(3)
        screenshot(device, "booked")
        return True

    log.warning(f"Could not confirm booking for {nombre} {hora}")
    screenshot(device, "book_failed")
    return False


# ============================================================
# ENTRY POINT
# ============================================================

def get_today_class():
    today = datetime.now().weekday()
    for c in CLASES:
        if c["dia_reserva"] == today:
            return c
    return None


def main():
    log.info("=" * 50)
    log.info(f"GYM BOT — {datetime.now():%Y-%m-%d %H:%M}")

    now = datetime.now()
    # En CI (GitHub Actions) el cron ya controla la hora, no filtrar
    if not os.environ.get("CI") and now.hour != 22:
        log.info("Not reservation time (22:00). Exiting.")
        return

    clase = get_today_class()
    if not clase:
        log.info("No reservation scheduled today. Exiting.")
        return

    log.info(f"Target: {clase['nombre']} {clase['hora']} (weekday {clase['dia_clase']})")

    device = None
    try:
        ensure_emulator()
        grant_app_permissions()

        device = u2.connect(DEVICE_SERIAL)
        log.info(f"Connected: {device.info.get('productName', '?')}")

        device.screen_on()
        time.sleep(2)

        device.app_stop(APP_PACKAGE)
        time.sleep(2)
        device.app_start(APP_PACKAGE)
        time.sleep(10)

        if not login(device):
            log.error("Login failed — aborting")
            return

        if not navigate_to_colectivas(device):
            log.error("Navigation failed — aborting")
            return

        book_class(device, clase)

    except Exception as e:
        log.error(f"Unhandled error: {e}", exc_info=True)
        if device:
            try:
                screenshot(device, "crash")
            except Exception:
                pass

    log.info("=" * 50)


if __name__ == "__main__":
    main()
