"""
Gym Bot — Reserva automática de clases en Technogym
=====================================================
- Domingo 22:00  → Body Tono lunes 18:00
- Martes 22:00   → Body Tono miércoles 18:00
- Miércoles 22:00 → POWER jueves 19:00
"""
import uiautomator2 as u2
import time
import logging
import os
import re
import subprocess
from datetime import datetime, timedelta

# ============================================================
# CONFIGURACIÓN
# ============================================================
EMAIL = "aliciaramirezcaballero@gmail.com"
PASSWORD = "gimnasio"
APP_PACKAGE = "com.technogym.tgapp"
ADBKEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"
DEVICE_SERIAL = os.environ.get("DEVICE_SERIAL", "emulator-5554")
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

CLASES = [
    {"nombre": "BODYTONO", "hora": "18:00", "dia_clase": 0, "dia_reserva": 6},
    {"nombre": "BODYTONO", "hora": "18:00", "dia_clase": 2, "dia_reserva": 1},
    {"nombre": "POWER",    "hora": "19:00", "dia_clase": 3, "dia_reserva": 2},
]

# Indicadores de que estamos en la home real del club (Sports Center Mercantil)
HOME_INDICATORS = [
    "colectivas", "reserva una clase", "tus citas", "entrenador",
    "explorar", "movergy", "tus planes", "sports center", "mercantil",
    "book a class", "your appointments",
]

# Indicadores de que estamos autenticados en Technogym pero aún no en la home del club
AUTHENTICATED_INDICATORS = [
    EMAIL.lower(), "daily moves", "movergy index", "coach", "results",
    "challenges", "precision program",
]

# Indicadores de que seguimos en el formulario de login (no confundir con home)
LOGIN_FORM_INDICATORS = [
    "loginpage.username.textfield", "loginpage.password.textfield",
    "loginpage.login.button", "loginpage.next.button",
]

# Botones de onboarding/permisos a descartar por resource-id (orden de prioridad)
DISMISS_RESOURCE_IDS = [
    "pushNotificationPermission.dismiss.button",
    "authHealthPage.skip.button",
]

# Textos de botones de descarte genérico (post-login y durante login)
DISMISS_TEXTS = [
    "MAYBE LATER", "Maybe Later", "Not now", "No thanks",
    "SKIP FOR NOW", "SKIP", "CONTINUE", "OK", "Allow",
    "While using the app", "Only this time",
    "START", "Empezar", "Siguiente", "ACEPTAR",
    "Permitir", "Mientras se usa la app", "Solo esta vez",
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
# ADB
# ============================================================

def adb_path():
    for path in (LOCAL_ADB, SDK_ADB, "adb"):
        if path == "adb" or os.path.exists(path):
            return path
    return "adb"


def run_adb(*args, timeout=20):
    cmd = [adb_path(), "-s", DEVICE_SERIAL, *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr="timeout")


def emulator_is_online():
    try:
        result = subprocess.run([adb_path(), "devices"], capture_output=True, text=True, timeout=10)
        return f"{DEVICE_SERIAL}\tdevice" in result.stdout
    except Exception:
        return False


def android_is_ready():
    if not emulator_is_online():
        return False
    result = run_adb("shell", "getprop", "sys.boot_completed", timeout=10)
    return result.returncode == 0 and result.stdout.strip() == "1"


def ensure_emulator():
    if android_is_ready():
        log.info(f"Emulator already ready: {DEVICE_SERIAL}")
        return

    if emulator_is_online():
        log.info("Emulator online but Android not ready — killing")
        run_adb("emu", "kill", timeout=10)
        time.sleep(5)

    if not os.path.exists(EMULATOR_EXE):
        raise FileNotFoundError(f"emulator not found: {EMULATOR_EXE}")

    log.info(f"Starting emulator {AVD_NAME}...")
    subprocess.Popen(
        [EMULATOR_EXE, "-avd", AVD_NAME, "-no-window", "-no-audio",
         "-gpu", "swiftshader_indirect", "-memory", "4096", "-cores", "4",
         "-port", "5554", "-no-snapshot-load", "-no-metrics"],
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
    )

    deadline = time.time() + 300
    while time.time() < deadline:
        if android_is_ready():
            log.info("Emulator ready")
            run_adb("shell", "input", "keyevent", "KEYCODE_WAKEUP", timeout=10)
            time.sleep(5)
            return
        time.sleep(5)
    raise TimeoutError(f"Emulator did not come online: {DEVICE_SERIAL}")


def setup_ime():
    """Activa AdbKeyboard como IME por defecto via secure settings (Android 14 compatible)."""
    run_adb("shell", "settings", "put", "secure", "show_ime_with_hard_keyboard", "1", timeout=5)
    run_adb("shell", "settings", "put", "secure", "enabled_input_methods", ADBKEYBOARD_IME, timeout=5)
    r = run_adb("shell", "settings", "put", "secure", "default_input_method", ADBKEYBOARD_IME, timeout=5)
    if r.returncode != 0:
        log.warning(f"IME setup warning: {(r.stdout + r.stderr).strip()}")
    else:
        log.info("AdbKeyboard IME active")


def grant_permissions():
    for perm in ("android.permission.ACCESS_FINE_LOCATION", "android.permission.ACCESS_COARSE_LOCATION"):
        run_adb("shell", "pm", "grant", APP_PACKAGE, perm, timeout=10)


# ============================================================
# DEVICE — conexión robusta con reconexión automática
# ============================================================

def _try_connect():
    device = u2.connect(DEVICE_SERIAL)
    _ = device.info  # lanza excepción si el servidor no está listo
    return device


def connect_device(max_wait=60):
    """Conecta uiautomator2, reintentando hasta max_wait segundos."""
    deadline = time.time() + max_wait
    last_exc = None
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        try:
            device = _try_connect()
            log.info(f"u2 connected (attempt {attempt}): {device.info.get('productName', '?')}")
            return device
        except Exception as exc:
            last_exc = exc
            log.info(f"  u2 not ready (attempt {attempt}): {exc}")
            time.sleep(3)
    raise RuntimeError(f"u2 server never ready after {max_wait}s: {last_exc}")


def safe_dump(device, retries=3):
    """dump_hierarchy con reconexión automática si el device se desconecta."""
    for attempt in range(1, retries + 1):
        try:
            return device.dump_hierarchy()
        except Exception as exc:
            log.warning(f"dump_hierarchy failed (attempt {attempt}/{retries}): {exc}")
            if attempt == retries:
                raise
            _wait_for_adb_online()
            try:
                device.__dict__.update(_try_connect().__dict__)
            except Exception:
                pass
            time.sleep(3)


def _wait_for_adb_online(timeout=60):
    deadline = time.time() + timeout
    while time.time() < deadline:
        if emulator_is_online():
            log.info("ADB back online")
            return True
        log.info("  Waiting for ADB...")
        time.sleep(5)
    return False


# ============================================================
# UI HELPERS
# ============================================================

def screenshot(device, name):
    path = os.path.join(SCREENSHOT_DIR, f"{name}_{datetime.now():%H%M%S}.png")
    try:
        device.screenshot(path)
    except Exception:
        try:
            result = subprocess.run(
                [adb_path(), "-s", DEVICE_SERIAL, "exec-out", "screencap", "-p"],
                capture_output=True, timeout=15,
            )
            if result.returncode == 0 and result.stdout:
                with open(path, "wb") as f:
                    f.write(result.stdout)
        except Exception:
            pass
    return path


def save_hierarchy(device, name):
    try:
        xml = safe_dump(device)
        path = os.path.join(BASE_DIR, f"{name}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        return xml
    except Exception as exc:
        log.warning(f"Could not save hierarchy {name}: {exc}")
        return ""


def xml_contains_any(xml, needles):
    haystack = xml.lower()
    return any(n.lower() in haystack for n in needles)


def xml_visible_strings(xml):
    values = []
    for attr in ("text", "content-desc", "resource-id"):
        values.extend(v for v in re.findall(fr'{attr}="([^"]+)"', xml) if v.strip())
    return values


def tap_adb(x, y):
    run_adb("shell", "input", "tap", str(x), str(y), timeout=10)
    time.sleep(0.8)


def tap_by_bounds(element):
    b = element.info.get("bounds", {})
    cx = (b["left"] + b["right"]) // 2
    cy = (b["top"] + b["bottom"]) // 2
    tap_adb(cx, cy)
    return cx, cy


def bring_app_foreground():
    run_adb("shell", "monkey", "-p", APP_PACKAGE, "-c", "android.intent.category.LAUNCHER", "1", timeout=15)
    time.sleep(2)


def dismiss_anr(device):
    """Descarta ANR si está presente. Devuelve True si había ANR."""
    try:
        xml = safe_dump(device)
    except Exception:
        return False
    if "isn't responding" not in xml and "not responding" not in xml.lower():
        return False
    log.info("ANR detected — dismissing")
    for label in ("Wait", "Esperar"):
        btn = device(text=label)
        if btn.exists:
            try:
                tap_by_bounds(btn)
                time.sleep(3)
                return True
            except Exception:
                pass
    tap_adb(725, 1090)
    time.sleep(3)
    return True


def dismiss_any_overlay(device):
    """
    Descarta overlays de onboarding/permisos en un solo paso.
    Primero intenta resource-ids conocidos, luego textos genéricos.
    Devuelve True si descartó algo.
    """
    for rid in DISMISS_RESOURCE_IDS:
        try:
            btn = device(resourceId=rid)
            if btn.exists:
                btn.click()
                log.info(f"  Dismissed overlay: {rid}")
                time.sleep(2)
                return True
        except Exception:
            pass

    for text in DISMISS_TEXTS:
        try:
            el = device(textContains=text)
            if el.exists:
                el.click()
                log.info(f"  Dismissed overlay text: {text}")
                time.sleep(2)
                return True
        except Exception:
            pass

    return False


def wait_for_element(device, resource_id, timeout=15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        dismiss_anr(device)
        el = device(resourceId=resource_id)
        if el.exists:
            return el
        time.sleep(1)
    return None


def click_element(device, resource_id=None, text=None, fallback_xy=None, timeout=10):
    """Pulsa un elemento por resource-id o texto, con fallback a coordenadas."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        dismiss_anr(device)
        el = device(resourceId=resource_id) if resource_id else device(textContains=text)
        if el.exists:
            try:
                tap_by_bounds(el)
                log.info(f"  Clicked: {resource_id or text}")
                return True
            except Exception:
                pass
        if text and not resource_id:
            el2 = device(textContains=text)
            if el2.exists:
                try:
                    tap_by_bounds(el2)
                    log.info(f"  Clicked (text): {text}")
                    return True
                except Exception:
                    pass
        time.sleep(0.5)

    if fallback_xy:
        log.info(f"  Fallback tap at {fallback_xy} for {resource_id or text}")
        tap_adb(*fallback_xy)
        return True

    log.info(f"  Not found: {resource_id or text}")
    return False


# ============================================================
# ENTRADA DE TEXTO
# ============================================================

def adb_type(text):
    safe = text.replace("%", "%25").replace(" ", "%s")
    r = run_adb("shell", "input", "text", safe, timeout=30)
    if r.returncode not in (0, 124):
        log.warning(f"adb input text rc={r.returncode}: {r.stderr.strip()}")


def enter_text(device, resource_id, text, fallback_xy=(540, 315)):
    """
    Escribe texto en un campo Flutter via AdbKeyboard.
    Secuencia: foco → clear → type → screenshot diagnóstico.
    Flutter no expone el texto en el árbol de accesibilidad, así que
    no podemos verificar el contenido — asumimos OK si no hay excepción.
    """
    el = device(resourceId=resource_id)

    # Foco en el campo
    if el.exists:
        try:
            tap_by_bounds(el)
        except Exception:
            tap_adb(*fallback_xy)
    else:
        tap_adb(*fallback_xy)
    time.sleep(0.5)

    # Limpiar campo existente
    run_adb("shell", "input", "keyevent", "KEYCODE_SELECT_ALL", timeout=5)
    time.sleep(0.2)
    run_adb("shell", "input", "keyevent", "KEYCODE_DEL", timeout=5)
    time.sleep(0.3)

    # Refoco y escritura
    if el.exists:
        try:
            tap_by_bounds(el)
        except Exception:
            tap_adb(*fallback_xy)
    else:
        tap_adb(*fallback_xy)
    time.sleep(0.3)

    adb_type(text)
    time.sleep(0.5)
    screenshot(device, f"after_type_{resource_id.split('.')[-1]}")
    log.info(f"  Text entered in {resource_id}")


# ============================================================
# LOGIN
# ============================================================

def _tap_login_button(device):
    """Pulsa el botón LOG IN de la pantalla inicial."""
    btn = device(resourceId="onboarding.alreadySignedIn.button")
    if btn.exists:
        try:
            cx, cy = tap_by_bounds(btn)
            log.info(f"  Tapped LOG IN at ({cx}, {cy})")
            return True
        except Exception:
            pass
    # Fallback por coordenada fija (1080x1920, botón en la parte baja)
    log.info("  LOG IN fallback tap (540, 1710)")
    tap_adb(540, 1710)
    return True


def login(device):
    log.info("--- LOGIN ---")
    screenshot(device, "login_start")

    # Esperar pantalla inicial o detectar que ya estamos en home
    for attempt in range(25):
        dismiss_anr(device)
        try:
            xml = safe_dump(device)
        except Exception:
            time.sleep(3)
            continue

        if xml_contains_any(xml, HOME_INDICATORS):
            log.info("Already at club home — skipping login")
            return True

        if "onboarding.alreadySignedin.button" in xml.lower() or \
           "already signed in" in xml.lower() or \
           "log in" in xml.lower():
            _tap_login_button(device)
            time.sleep(6)
            break

        if "loginpage.username.textfield" in xml.lower():
            log.info("Login form already visible")
            break

        # Descartar cualquier overlay que bloquee la pantalla inicial
        if dismiss_any_overlay(device):
            continue

        # Tras varios intentos en blanco, tap ciego al botón LOG IN
        if attempt in (5, 10, 15, 20):
            log.info(f"  Blind LOG IN tap (attempt {attempt})")
            screenshot(device, f"blind_login_{attempt}")
            _tap_login_button(device)
            time.sleep(6)

        time.sleep(3)

    # Esperar campo email
    time.sleep(3)
    screenshot(device, "login_form")
    email_el = wait_for_element(device, "loginPage.username.textfield", timeout=20)
    if not email_el:
        log.warning("Email field not found")
        save_hierarchy(device, "login_failed_hierarchy")
        screenshot(device, "login_form_not_found")
        return False

    # Paso 1: email
    enter_text(device, "loginPage.username.textfield", EMAIL, fallback_xy=(540, 315))
    log.info(f"Email entered: {EMAIL}")
    time.sleep(1)

    # NEXT → paso de password
    click_element(device, resource_id="loginPage.next.button", fallback_xy=(540, 1328), timeout=5)
    log.info("Tapped NEXT after email")
    time.sleep(3)

    # Paso 2: password
    pw_el = wait_for_element(device, "loginPage.password.textfield", timeout=15)
    if not pw_el:
        log.warning("Password field not found")
        screenshot(device, "login_pw_not_found")
        return False

    enter_text(device, "loginPage.password.textfield", PASSWORD, fallback_xy=(540, 525))
    log.info("Password entered")
    time.sleep(1)

    # LOGIN / NEXT
    if not click_element(device, resource_id="loginPage.login.button", timeout=3):
        click_element(device, resource_id="loginPage.next.button", fallback_xy=(540, 1328), timeout=5)
    log.info("Login submitted")
    time.sleep(8)
    screenshot(device, "after_login_submit")

    # Esperar home del club — descartar overlays en cada iteración
    for i in range(40):
        dismiss_anr(device)
        try:
            xml = safe_dump(device)
        except Exception:
            time.sleep(5)
            continue

        visible = xml_visible_strings(xml)
        log.info(f"  Post-login {i+1}/40: {visible[:12]}")

        if xml_contains_any(xml, HOME_INDICATORS):
            log.info("Club home reached")
            screenshot(device, "home_reached")
            return True

        # Descartar overlays de onboarding — si descartamos algo, volver a evaluar
        if dismiss_any_overlay(device):
            continue

        # Home genérica de Technogym (sin club específico todavía)
        if xml_contains_any(xml, AUTHENTICATED_INDICATORS) and \
           not xml_contains_any(xml, LOGIN_FORM_INDICATORS):
            log.info("Authenticated home (club home not yet visible)")
            return True

        # Si lleva mucho tiempo cargando, relanzar la app una vez
        if i == 20 and "contentloading" in xml.lower():
            log.info("Still loading at iter 20 — restarting app")
            device.app_stop(APP_PACKAGE)
            time.sleep(3)
            device.app_start(APP_PACKAGE)
            time.sleep(15)

        time.sleep(5)

    log.warning("Login timeout — could not reach home")
    screenshot(device, "login_failed")
    save_hierarchy(device, "login_failed_hierarchy")
    return False


# ============================================================
# NAVEGACIÓN
# ============================================================

def navigate_to_colectivas(device):
    """
    Pulsa 'Reserva una clase' desde la home del club.
    Eso lleva directamente a la pantalla de clases colectivas con la lista de tarjetas.
    No hay selector de días — todas las clases aparecen en una lista única.
    """
    log.info("--- NAVIGATE TO COLECTIVAS ---")
    time.sleep(2)

    for attempt in range(3):
        dismiss_anr(device)

        for label in ("Reserva una clase", "Book a class"):
            el = device(textContains=label)
            if el.exists:
                try:
                    tap_by_bounds(el)
                    log.info(f"  Tapped '{label}' — now on colectivas screen")
                    time.sleep(3)
                    screenshot(device, "colectivas_screen")
                    return True
                except Exception as exc:
                    log.warning(f"  '{label}' tap failed: {exc}")

        log.info(f"  'Reserva una clase' not found (attempt {attempt+1}/3), retrying...")
        time.sleep(3)

    log.warning("Could not navigate to colectivas screen")
    screenshot(device, "nav_failed")
    save_hierarchy(device, "nav_failed_hierarchy")
    return False


# ============================================================
# RESERVA
# ============================================================

def select_day(device, dia_clase):
    DAY_LABELS = {
        0: ["LUN", "MON"], 1: ["MAR", "TUE"], 2: ["MIÉ", "MIE", "WED"],
        3: ["JUE", "THU"], 4: ["VIE", "FRI"], 5: ["SÁB", "SAB", "SAT"],
        6: ["DOM", "SUN"],
    }
    today = datetime.now()
    days_ahead = (dia_clase - today.weekday()) % 7 or 7
    target = today + timedelta(days=days_ahead)
    day_num = str(target.day)
    log.info(f"  Looking for {target.strftime('%a %d')} (weekday {dia_clase})")

    try:
        xml = safe_dump(device)
    except Exception:
        xml = ""

    # Buscar combinación abreviatura+número en el XML
    for label in DAY_LABELS[dia_clase]:
        pattern = rf'text="({re.escape(label)}\s*{re.escape(day_num)}|{re.escape(day_num)}\s*{re.escape(label)})"'
        m = re.search(pattern, xml, re.IGNORECASE)
        if m:
            el = device(text=m.group(1))
            if not el.exists:
                el = device(textContains=label)
            if el.exists:
                try:
                    tap_by_bounds(el)
                    log.info(f"  Selected day: {m.group(1)}")
                    time.sleep(2)
                    return True
                except Exception:
                    pass

    # Fallback: solo abreviatura
    for label in DAY_LABELS[dia_clase]:
        el = device(textContains=label)
        if el.exists:
            try:
                tap_by_bounds(el)
                log.info(f"  Selected day (fallback label): {label}")
                time.sleep(2)
                return True
            except Exception:
                pass

    log.warning(f"  Day not found: weekday {dia_clase}")
    return False


def find_and_tap_booking_button(device, nombre, hora):
    """
    Parsea el XML buscando una tarjeta con nombre+hora y pulsa el botón de reserva.
    Devuelve: 'booked', 'already', 'waitlist', 'full', None.
    """
    try:
        xml = safe_dump(device)
    except Exception as exc:
        log.warning(f"  dump_hierarchy failed in find_card: {exc}")
        return None

    lines = xml.split('\n')
    hora_idx = [i for i, l in enumerate(lines) if hora in l]
    nombre_idx = [i for i, l in enumerate(lines) if nombre.upper() in l.upper()]

    log.info(f"  '{hora}' at lines {hora_idx[:5]}, '{nombre}' at lines {nombre_idx[:5]}")

    # Encontrar la tarjeta donde hora y nombre están próximos (±40 líneas)
    card_line = None
    for hi in hora_idx:
        for ni in nombre_idx:
            if abs(hi - ni) <= 40:
                card_line = hi
                break
        if card_line is not None:
            break

    if card_line is None:
        log.info(f"  No card found for {nombre} @ {hora}")
        return None

    start = max(0, card_line - 50)
    end = min(len(lines), card_line + 50)
    block = '\n'.join(lines[start:end])

    if 'CANCELAR' in block or 'Cancelar' in block:
        log.info(f"  Already booked (CANCELAR)")
        return 'already'

    if re.search(r'[ÚU]NETE', block, re.IGNORECASE):
        log.info(f"  Class full — trying waitlist")
        m = re.search(r'text="[ÚúUu]NETE"[^>]*/?>?\s*<[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', block)
        if not m:
            m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="[ÚúUu]NETE"', block)
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            tap_adb((x1 + x2) // 2, (y1 + y2) // 2)
            return 'waitlist'
        el = device(textContains="NETE")
        if el.exists:
            el.click()
            return 'waitlist'
        return 'full'

    # Buscar botón RESERVAR
    m = re.search(r'text="RESERVAR"[^>]*/?>?\s*<[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', block)
    if not m:
        m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="RESERVAR"', block)
    if m:
        x1, y1, x2, y2 = map(int, m.groups())
        tap_adb((x1 + x2) // 2, (y1 + y2) // 2)
        log.info(f"  Tapped RESERVAR at ({(x1+x2)//2}, {(y1+y2)//2})")
        return 'booked'

    el = device(text="RESERVAR")
    if el.exists:
        el.click()
        log.info("  Clicked RESERVAR via u2")
        return 'booked'

    log.info("  RESERVAR not found in card block")
    return None


def select_station(device):
    """
    Maneja la pantalla 'Elige tu estación' que aparece en clases de spinning (CICLO).
    Pulsa cualquier bici con texto 'Disponible' y luego el botón RESERVAR.
    """
    if not device(textContains="Elige tu estación").exists and \
       not device(textContains="Elige tu estacion").exists:
        return False

    log.info("  Station selection screen detected")
    screenshot(device, "station_selection")

    # Pulsar cualquier plaza disponible
    for label in ("Disponible", "Available"):
        el = device(textContains=label)
        if el.exists:
            try:
                tap_by_bounds(el)
                log.info(f"  Selected station: {label}")
                time.sleep(2)
                break
            except Exception as exc:
                log.warning(f"  Station tap failed: {exc}")

    # Pulsar RESERVAR en la parte inferior
    for label in ("RESERVAR", "Reservar", "RESERVE"):
        el = device(textContains=label)
        if el.exists:
            try:
                tap_by_bounds(el)
                log.info("  Tapped RESERVAR on station screen")
                time.sleep(3)
                return True
            except Exception as exc:
                log.warning(f"  RESERVAR tap failed on station screen: {exc}")

    log.warning("  Could not complete station selection")
    return False


def confirm_booking(device):
    """Descarta el diálogo '¿Quieres guardar en calendario?' que aparece tras reservar."""
    for text in ("AHORA NO", "Ahora no", "NOT NOW", "Now now"):
        el = device(textContains=text)
        if el.exists:
            try:
                el.click()
                log.info(f"  Dismissed calendar dialog: {text}")
                time.sleep(2)
                return True
            except Exception:
                pass
    # Fallback: otros textos de confirmación genéricos
    for text in ("CONFIRMAR", "Confirmar", "OK", "ACEPTAR"):
        el = device(textContains=text)
        if el.exists:
            try:
                el.click()
                log.info(f"  Booking confirmed: {text}")
                time.sleep(2)
                return True
            except Exception:
                pass
    return False


def book_class_with_refresh(device, clase):
    """
    Reintenta reservar durante hasta 3 minutos refrescando cada 5 segundos.
    No hay selector de días — la lista muestra todas las clases juntas.
    Para CICLO maneja la pantalla intermedia de selección de bici.
    """
    nombre = clase["nombre"]
    hora = clase["hora"]

    log.info(f"--- BOOK: {nombre} {hora} ---")
    screenshot(device, "colectivas_before_book")

    deadline = time.time() + 180
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        dismiss_anr(device)
        log.info(f"  Booking attempt {attempt}...")

        result = find_and_tap_booking_button(device, nombre, hora)

        if result == 'already':
            log.info(f"Already booked: {nombre} {hora}")
            screenshot(device, "already_booked")
            return True

        if result in ('booked', 'waitlist'):
            time.sleep(3)
            screenshot(device, f"after_{result}_tap")
            # Para CICLO: puede aparecer pantalla de selección de bici
            select_station(device)
            time.sleep(2)
            # Descartar diálogo de calendario
            confirm_booking(device)
            time.sleep(2)
            screenshot(device, result)
            log.info(f"{'RESERVED' if result == 'booked' else 'WAITLIST'}: {nombre} {hora}")
            return True

        if result == 'full':
            log.warning(f"Class full, no waitlist: {nombre} {hora}")
            screenshot(device, "class_full")
            return False

        # Tarjeta no disponible aún (SEGUIR) — pull-to-refresh y esperar
        log.info("  RESERVAR not found yet — refreshing")
        time.sleep(5)
        try:
            device.swipe(540, 600, 540, 1200, duration=0.4)
            time.sleep(2)
        except Exception:
            pass

    log.warning(f"Booking timeout: {nombre} {hora}")
    screenshot(device, "book_timeout")
    save_hierarchy(device, "book_timeout")
    return False


# ============================================================
# ENTRY POINT
# ============================================================

def get_today_class():
    force = os.environ.get("FORCE_CLASS")
    if force:
        parts = force.split(",")
        nombre = parts[0].strip()
        hora = parts[1].strip() if len(parts) > 1 else "18:00"
        dia = int(parts[2].strip()) if len(parts) > 2 else datetime.now().weekday()
        log.info(f"FORCE_CLASS: {nombre} {hora} weekday {dia}")
        return {"nombre": nombre, "hora": hora, "dia_clase": dia, "dia_reserva": -1}

    today = datetime.now().weekday()
    for c in CLASES:
        if c["dia_reserva"] == today:
            return c
    return None


def main():
    log.info("=" * 50)
    log.info(f"GYM BOT — {datetime.now():%Y-%m-%d %H:%M}")

    force = os.environ.get("FORCE_CLASS")
    now = datetime.now()

    if not os.environ.get("CI") and not force and now.hour != 22:
        log.info("Not reservation time (22:00). Exiting.")
        return

    clase = get_today_class()
    if not clase:
        log.info("No class scheduled today. Exiting.")
        return

    log.info(f"Target: {clase['nombre']} {clase['hora']} (weekday {clase['dia_clase']})")

    device = None
    try:
        ensure_emulator()
        grant_permissions()
        device = connect_device()
        setup_ime()

        device.screen_on()
        time.sleep(2)

        # Esperar 3 ciclos consecutivos sin ANR antes de lanzar la app
        log.info("Waiting for system to stabilize...")
        stable = 0
        for _ in range(30):
            if dismiss_anr(device):
                bring_app_foreground()
                stable = 0
                time.sleep(4)
            else:
                stable += 1
                log.info(f"  Stable {stable}/3")
                if stable >= 3:
                    break
                time.sleep(3)
        log.info("System stable")

        device.app_stop(APP_PACKAGE)
        time.sleep(3)
        device.app_start(APP_PACKAGE)
        log.info("App started — waiting 30s...")
        time.sleep(30)

        if not login(device):
            log.error("Login failed — aborting")
            return

        if not navigate_to_colectivas(device):
            log.error("Navigation failed — aborting")
            return

        # En CI sin forzado: esperar hasta las 22:00 Madrid (20:00 UTC)
        if os.environ.get("CI") and not force:
            utc_now = datetime.utcnow()
            target = utc_now.replace(hour=20, minute=0, second=0, microsecond=0)
            wait_secs = (target - utc_now).total_seconds()
            if wait_secs > 0:
                log.info(f"Waiting {wait_secs:.0f}s until 22:00 Madrid...")
                time.sleep(wait_secs)
            log.info("22:00 — starting booking")

        book_class_with_refresh(device, clase)

    except Exception as exc:
        log.error(f"Unhandled error: {exc}", exc_info=True)
        if device:
            try:
                screenshot(device, "crash")
                save_hierarchy(device, "crash_hierarchy")
            except Exception:
                pass

    log.info("=" * 50)


if __name__ == "__main__":
    main()
