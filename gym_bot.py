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


def adb_input_text(text):
    """Escribe texto con ADB, evitando clipboard/IME de uiautomator2 en Android 14."""
    escaped = text.replace("%", "%25").replace(" ", "%s")
    result = run_adb("shell", "input", "text", escaped, timeout=10)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "adb input text failed")


def enter_text(device, field, text):
    """Rellena un campo sin usar device.send_keys, que puede fallar con SecurityException."""
    try:
        device.clear_text()
    except Exception:
        run_adb("shell", "input", "keyevent", "KEYCODE_CTRL_LEFT", "KEYCODE_A", timeout=10)
        run_adb("shell", "input", "keyevent", "KEYCODE_DEL", timeout=10)
    time.sleep(0.5)

    try:
        field.set_text(text)
        return
    except Exception as exc:
        log.info(f"uiautomator set_text failed, falling back to adb input: {exc}")

    adb_input_text(text)


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
    INIT_DIALOGS = ["OK", "CONTINUE", "SKIP", "Allow", "While using the app"]
    for _ in range(20):
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
            try:
                info = login_btn.info
                bounds = info.get("bounds", {})
                cx = (bounds.get("left", 0) + bounds.get("right", 1080)) // 2
                cy = (bounds.get("top", 0) + bounds.get("bottom", 1920)) // 2
                log.info(f"  LOG IN bounds: {bounds}, tapping ({cx}, {cy})")
                tap_adb(cx, cy)
            except Exception:
                tap_adb(540, 1710)
            time.sleep(6)
            break

        if any("LOG IN" in t or "Log in" in t for t in texts):
            log.info("Initial screen (text fallback) — tapping LOG IN")
            tap_adb(540, 1710)
            time.sleep(6)
            break

        # Descartar diálogos de onboarding / permisos — sin timeout, solo .exists
        for dlg in INIT_DIALOGS:
            el = device(textContains=dlg)
            if el.exists:
                try:
                    el.click()
                    log.info(f"  Dismissed init dialog: {dlg}")
                    time.sleep(2)
                    break
                except Exception:
                    pass

        time.sleep(3)

    # Rellenar formulario de login — flujo de dos pasos: email→NEXT, password→NEXT
    time.sleep(3)
    screenshot(device, "login_form")
    texts = get_texts(device)
    log.info(f"Login form texts: {texts[:10]}")

    # Paso 1: email
    filled_email = False
    for attempt in range(5):
        dismiss_anr(device)
        email_el = device(resourceId="loginPage.username.textfield")
        if email_el.exists:
            try:
                b = email_el.info.get("bounds", {})
                cx = (b.get("left", 0) + b.get("right", 1080)) // 2
                cy = (b.get("top", 0) + b.get("bottom", 400)) // 2
                tap_adb(cx, cy)
            except Exception:
                tap_adb(540, 315)
            time.sleep(1)
            enter_text(device, email_el, EMAIL)
            time.sleep(1)
            log.info(f"Email entered: {EMAIL}")
            filled_email = True
            break
        time.sleep(2)

    if not filled_email:
        log.warning("Could not find email field")
        screenshot(device, "login_form_not_found")
        return False

    # Pulsar NEXT para avanzar al paso de password
    next_btn = device(resourceId="loginPage.next.button")
    if next_btn.exists:
        try:
            b = next_btn.info.get("bounds", {})
            cx = (b.get("left", 0) + b.get("right", 1080)) // 2
            cy = (b.get("top", 0) + b.get("bottom", 1920)) // 2
            tap_adb(cx, cy)
        except Exception:
            tap_adb(540, 1328)
    else:
        # NEXT por texto o coordenada fija (abajo de pantalla)
        el = device(text="NEXT")
        if el.exists:
            try:
                b = el.info.get("bounds", {})
                tap_adb((b["left"]+b["right"])//2, (b["top"]+b["bottom"])//2)
            except Exception:
                tap_adb(540, 1328)
        else:
            tap_adb(540, 1328)
    log.info("Tapped NEXT after email")
    time.sleep(3)

    # Paso 2: password
    filled_pw = False
    for attempt in range(5):
        dismiss_anr(device)
        pw_el = device(resourceId="loginPage.password.textfield")
        if pw_el.exists:
            try:
                b = pw_el.info.get("bounds", {})
                cx = (b.get("left", 0) + b.get("right", 1080)) // 2
                cy = (b.get("top", 0) + b.get("bottom", 600)) // 2
                tap_adb(cx, cy)
            except Exception:
                tap_adb(540, 525)
            time.sleep(1)
            enter_text(device, pw_el, PASSWORD)
            time.sleep(1)
            log.info("Password entered")
            filled_pw = True
            break
        time.sleep(2)

    if not filled_pw:
        log.warning("Could not find password field")
        screenshot(device, "login_pw_not_found")
        return False

    # Pulsar NEXT / LOGIN para enviar
    login_btn = device(resourceId="loginPage.login.button")
    next_btn2 = device(resourceId="loginPage.next.button")
    if login_btn.exists:
        try:
            b = login_btn.info.get("bounds", {})
            tap_adb((b["left"]+b["right"])//2, (b["top"]+b["bottom"])//2)
        except Exception:
            tap_adb(540, 1328)
        log.info("  Clicked login button")
    elif next_btn2.exists:
        try:
            b = next_btn2.info.get("bounds", {})
            tap_adb((b["left"]+b["right"])//2, (b["top"]+b["bottom"])//2)
        except Exception:
            tap_adb(540, 1328)
        log.info("  Clicked NEXT (login step)")
    else:
        el = device(text="NEXT")
        if el.exists:
            try:
                b = el.info.get("bounds", {})
                tap_adb((b["left"]+b["right"])//2, (b["top"]+b["bottom"])//2)
            except Exception:
                tap_adb(540, 1328)
        else:
            tap_adb(540, 1328)
        log.info("  Tapped NEXT/LOGIN by fallback")

    log.info("Waiting for login to complete...")
    time.sleep(8)
    screenshot(device, "after_login")

    # Descartar posibles diálogos post-login (permisos, tutorial, onboarding)
    # En un emulador fresco la app puede tardar 3-4 min en cargar el club
    HOME_INDICATORS = ["COLECTIVAS", "Colectivas", "Reserva una clase", "Tus citas",
                       "Entrenador", "Explorar", "MOVERGY", "Tus planes"]
    DIALOG_TEXTS = ["CONTINUE", "SKIP", "OK", "Allow",
                    "While using the app", "Only this time",
                    "START", "Empezar", "Siguiente", "ACEPTAR"]
    for i in range(40):
        dismiss_anr(device)
        xml = device.dump_hierarchy()
        texts = [t for t in re.findall(r'text="([^"]+)"', xml) if t.strip()]
        log.info(f"  Post-login iter {i+1}/40 texts: {texts[:15]}")

        # Guardar XML y screenshot ADB cada 5 iteraciones para diagnóstico
        if i % 5 == 0:
            try:
                xml_path = os.path.join(BASE_DIR, f"postlogin_iter{i+1:02d}.xml")
                with open(xml_path, "w", encoding="utf-8") as f:
                    f.write(xml)
            except Exception:
                pass
            try:
                img_path = os.path.join(SCREENSHOT_DIR, f"postlogin_iter{i+1:02d}.png")
                result = subprocess.run(
                    [adb_path(), "-s", DEVICE_SERIAL, "exec-out", "screencap", "-p"],
                    capture_output=True, timeout=15
                )
                if result.returncode == 0 and result.stdout:
                    with open(img_path, "wb") as f:
                        f.write(result.stdout)
            except Exception:
                pass

        if any(t in texts for t in HOME_INDICATORS):
            log.info("Club home reached")
            return True

        # Descarte rápido de diálogos — sin timeout, solo .exists
        for dlg in DIALOG_TEXTS:
            el = device(textContains=dlg)
            if el.exists:
                try:
                    el.click()
                    log.info(f"  Dismissed: {dlg}")
                    time.sleep(2)
                    break
                except Exception:
                    pass

        time.sleep(5)

    log.warning("Login may have failed — could not find club home")
    screenshot(device, "login_failed")
    try:
        xml = device.dump_hierarchy()
        xml_path = os.path.join(BASE_DIR, "login_failed_hierarchy.xml")
        with open(xml_path, "w", encoding="utf-8") as f:
            f.write(xml)
        log.info(f"Saved UI hierarchy to {xml_path}")
    except Exception as e:
        log.warning(f"Could not dump hierarchy: {e}")
    return False


# ============================================================
# NAVEGACIÓN Y RESERVA
# ============================================================

def navigate_to_colectivas(device):
    """Pulsa el tab COLECTIVAS del bottom navigation."""
    log.info("--- NAVIGATE TO COLECTIVAS ---")
    time.sleep(2)

    # Intentar el tab COLECTIVAS directamente (bottom nav)
    if click_text(device, "COLECTIVAS", timeout=5) or click_text(device, "Colectivas", timeout=3):
        time.sleep(3)
        screenshot(device, "colectivas_screen")
        return True

    # Si no está visible, intentar desde "Reserva una clase" (botón en home)
    if click_text(device, "Reserva una clase", timeout=5):
        time.sleep(3)
        screenshot(device, "reserva_screen")
        # Desde la pantalla de reserva, pulsar COLECTIVAS si aparece
        if click_text(device, "COLECTIVAS", timeout=5) or click_text(device, "Colectivas", timeout=3):
            time.sleep(3)
            screenshot(device, "colectivas_screen")
        return True

    log.warning("Could not navigate to COLECTIVAS")
    screenshot(device, "nav_failed")
    try:
        texts = get_texts(device)
        log.info(f"  Nav failed — visible texts: {texts[:20]}")
    except Exception:
        pass
    return False


def select_day(device, dia_clase):
    """Selecciona el día correcto en el selector horizontal de días."""
    log.info(f"--- SELECT DAY: weekday {dia_clase} ---")
    # Variantes con y sin tilde, más inglés
    DAY_CANDIDATES = {
        0: ["LUN", "MON"],
        1: ["MAR", "TUE"],
        2: ["MIÉ", "MIE", "WED"],
        3: ["JUE", "THU"],
        4: ["VIE", "FRI"],
        5: ["SÁB", "SAB", "SAT"],
        6: ["DOM", "SUN"],
    }

    # Calcular la fecha exacta del día de la clase (puede ser mañana o pasado mañana)
    from datetime import timedelta
    today = datetime.now()
    days_ahead = (dia_clase - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7  # si hoy es el mismo día, es la semana que viene
    target_date = today + timedelta(days=days_ahead)
    day_number = str(target_date.day)
    log.info(f"  Looking for day {dia_clase} = {target_date.strftime('%a %d')}, day number: {day_number}")

    # Intentar primero buscando etiqueta + número de día (más preciso)
    for label in DAY_CANDIDATES[dia_clase]:
        # Buscar elemento que contenga la abreviatura del día Y el número
        xml = device.dump_hierarchy()
        pattern = rf'text="({re.escape(label)}\s*{re.escape(day_number)}|{re.escape(day_number)}\s*{re.escape(label)})"'
        match = re.search(pattern, xml, re.IGNORECASE)
        if match:
            el = device(text=match.group(1))
            if not el.exists:
                el = device(textContains=label)
            if el.exists:
                el.click()
                log.info(f"  Selected day: {match.group(1)}")
                time.sleep(2)
                return True

    # Fallback: solo por abreviatura
    for label in DAY_CANDIDATES[dia_clase]:
        el = device(textContains=label)
        if el.exists:
            el.click()
            log.info(f"  Selected day (fallback): {label}")
            time.sleep(2)
            return True

    log.warning(f"Day not found: weekday {dia_clase}")
    return False


def find_card_and_book(device, nombre, hora):
    """
    Parsea el XML de la pantalla buscando una tarjeta que contenga
    tanto el nombre de clase como la hora, y pulsa RESERVAR en ella.
    Descarta tarjetas con CANCELAR (ya reservada) o ÚNETE (llena).
    Devuelve: 'booked', 'already', 'full', o None si no encontrada.
    """
    xml = device.dump_hierarchy()

    # Dividir el XML en bloques aproximados por tarjeta.
    # Cada tarjeta contiene la hora, el nombre, y uno de: RESERVAR / CANCELAR / ÚNETE
    # Buscar bloques que contengan la hora Y el nombre de clase
    # Trabajamos sobre el XML plano buscando proximidad de texto
    lines = xml.split('\n')

    # Encontrar índices de líneas que contengan la hora y el nombre
    hora_indices = [i for i, l in enumerate(lines) if hora in l]
    nombre_indices = [i for i, l in enumerate(lines) if nombre.upper() in l.upper() or nombre.lower() in l.lower()]

    log.info(f"  hora '{hora}' found at lines: {hora_indices[:5]}")
    log.info(f"  nombre '{nombre}' found at lines: {nombre_indices[:5]}")

    # Para cada aparición de la hora, buscar si hay un nombre cercano (ventana de ±40 líneas)
    matched_hora_line = None
    for hi in hora_indices:
        for ni in nombre_indices:
            if abs(hi - ni) <= 40:
                matched_hora_line = hi
                log.info(f"  Card matched: hora line {hi}, nombre line {ni}")
                break
        if matched_hora_line is not None:
            break

    if matched_hora_line is None:
        log.warning(f"  No card found with {nombre} at {hora}")
        return None

    # Extraer el bloque de la tarjeta (±50 líneas alrededor de la hora)
    start = max(0, matched_hora_line - 50)
    end = min(len(lines), matched_hora_line + 50)
    block = '\n'.join(lines[start:end])

    # Detectar estado
    if 'CANCELAR' in block or 'Cancelar' in block:
        log.info(f"  Class {nombre} {hora} already booked (CANCELAR found)")
        return 'already'

    # Clase llena — intentar apuntarse a la lista de espera pulsando ÚNETE
    unete_block = block.upper()
    if 'ÚNETE' in block or 'UNETE' in unete_block or 'únete' in block.lower():
        log.info(f"  Class {nombre} {hora} is full — trying waitlist (ÚNETE)")
        unete_match = re.search(r'text="[Úú]NETE"[^/]*/?\s*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', block)
        if not unete_match:
            unete_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="[Úú]NETE"', block)
        if unete_match:
            x1, y1, x2, y2 = map(int, unete_match.groups())
            cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
            log.info(f"  Tapping ÚNETE at ({cx}, {cy})")
            tap_adb(cx, cy)
            return 'waitlist'
        el = device(textContains="NETE")
        if el.exists:
            el.click()
            log.info("  Clicked ÚNETE via uiautomator2")
            return 'waitlist'
        return 'full'

    # Buscar RESERVAR en el bloque — hacer click por coordenadas del elemento en el XML
    reservar_match = re.search(r'text="RESERVAR"[^/]*/?\s*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', block)
    if not reservar_match:
        # Intentar orden inverso bounds/text
        reservar_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="RESERVAR"', block)

    if reservar_match:
        x1, y1, x2, y2 = map(int, reservar_match.groups())
        cx, cy = (x1 + x2) // 2, (y1 + y2) // 2
        log.info(f"  Tapping RESERVAR at ({cx}, {cy})")
        tap_adb(cx, cy)
        return 'booked'

    # Fallback: buscar el elemento uiautomator2 directamente
    el = device(text="RESERVAR")
    if el.exists:
        el.click()
        log.info("  Clicked RESERVAR via uiautomator2")
        return 'booked'

    log.warning("  RESERVAR button not found in card block")
    return None


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

    time.sleep(3)
    screenshot(device, "day_selected")

    # Intentar hasta 3 veces (el botón puede aparecer con retraso)
    for attempt in range(3):
        dismiss_anr(device)
        result = find_card_and_book(device, nombre, hora)

        if result == 'already':
            log.info(f"Class {nombre} {hora} is already booked — nothing to do")
            screenshot(device, "already_booked")
            return True

        if result == 'waitlist':
            time.sleep(4)
            screenshot(device, "after_unete_tap")
            click_if_present(device, "CONFIRMAR", "Confirmar", "Confirm", "OK",
                             "ACEPTAR", "Aceptar", timeout=5)
            time.sleep(3)
            screenshot(device, "waitlist")
            log.info(f"WAITLIST: joined waitlist for {nombre} {hora}")
            return True

        if result == 'full':
            log.warning(f"Class {nombre} {hora} is full and could not join waitlist")
            screenshot(device, "class_full")
            return False

        if result == 'booked':
            time.sleep(4)
            screenshot(device, "after_reservar_tap")
            # Confirmar si aparece diálogo de confirmación
            click_if_present(device, "CONFIRMAR", "Confirmar", "Confirm", "OK",
                             "ACEPTAR", "Aceptar", timeout=5)
            time.sleep(3)
            screenshot(device, "booked")
            log.info(f"RESERVED: {nombre} {hora}")
            return True

        # No encontrado — esperar y reintentar
        log.info(f"  Attempt {attempt+1}: card not found, waiting...")
        time.sleep(3)

    log.warning(f"Could not find or book {nombre} {hora} after 3 attempts")
    screenshot(device, "book_failed")
    return False


def refresh_colectivas(device, dia_clase):
    """Fuerza un refresco de la pantalla COLECTIVAS: pull-to-refresh + re-selección de día."""
    try:
        # Pull-to-refresh: swipe hacia abajo desde el centro de la lista
        device.swipe(540, 600, 540, 1200, duration=0.4)
        time.sleep(2)
    except Exception:
        pass
    select_day(device, dia_clase)
    time.sleep(2)


def book_class_with_refresh(device, clase):
    """
    Intenta reservar durante hasta 3 minutos refrescando cada 5 segundos.
    Útil para el momento exacto de apertura (22:00): el botón RESERVAR puede
    tardar unos segundos en aparecer después del horario de apertura.
    """
    nombre = clase["nombre"]
    hora = clase["hora"]
    dia = clase["dia_clase"]

    log.info(f"--- BOOK WITH REFRESH: {nombre} {hora} (weekday {dia}) ---")

    if not select_day(device, dia):
        log.warning("Could not select day")
        screenshot(device, "day_not_found")
        return False

    time.sleep(3)
    screenshot(device, "day_selected")

    deadline = time.time() + 180  # 3 minutos máximo
    attempt = 0
    while time.time() < deadline:
        attempt += 1
        dismiss_anr(device)
        log.info(f"  Refresh attempt {attempt}...")
        result = find_card_and_book(device, nombre, hora)

        if result == 'already':
            log.info(f"Class {nombre} {hora} is already booked — nothing to do")
            screenshot(device, "already_booked")
            return True

        if result == 'waitlist':
            time.sleep(4)
            screenshot(device, "after_unete_tap")
            click_if_present(device, "CONFIRMAR", "Confirmar", "Confirm", "OK",
                             "ACEPTAR", "Aceptar", timeout=5)
            time.sleep(3)
            screenshot(device, "waitlist")
            log.info(f"WAITLIST: joined waitlist for {nombre} {hora}")
            return True

        if result == 'full':
            log.warning(f"Class {nombre} {hora} is full and could not join waitlist")
            screenshot(device, "class_full")
            return False

        if result == 'booked':
            time.sleep(4)
            screenshot(device, "after_reservar_tap")
            click_if_present(device, "CONFIRMAR", "Confirmar", "Confirm", "OK",
                             "ACEPTAR", "Aceptar", timeout=5)
            time.sleep(3)
            screenshot(device, "booked")
            log.info(f"RESERVED: {nombre} {hora}")
            return True

        # Tarjeta no encontrada o botón no disponible todavía — refrescar
        log.info(f"  Card/button not available yet — refreshing in 5s")
        time.sleep(5)
        refresh_colectivas(device, dia)

    log.warning(f"Could not book {nombre} {hora} after 3 minutes of retries")
    screenshot(device, "book_timeout")
    return False


# ============================================================
# ENTRY POINT
# ============================================================

def get_today_class():
    # FORCE_CLASS env var: "NOMBRE,HH:MM,dia_clase_weekday" — omite comprobación de día
    force = os.environ.get("FORCE_CLASS")
    if force:
        parts = force.split(",")
        nombre = parts[0].strip()
        hora = parts[1].strip() if len(parts) > 1 else "18:00"
        dia_clase = int(parts[2].strip()) if len(parts) > 2 else datetime.now().weekday()
        log.info(f"FORCE_CLASS override: {nombre} {hora} weekday {dia_clase}")
        return {"nombre": nombre, "hora": hora, "dia_clase": dia_clase, "dia_reserva": -1}

    today = datetime.now().weekday()
    for c in CLASES:
        if c["dia_reserva"] == today:
            return c
    return None


def main():
    log.info("=" * 50)
    log.info(f"GYM BOT — {datetime.now():%Y-%m-%d %H:%M}")

    now = datetime.now()
    force = os.environ.get("FORCE_CLASS")

    if not os.environ.get("CI") and not force and now.hour != 22:
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
        # uiautomator2 server puede tardar unos segundos en estar listo
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

        device.screen_on()
        time.sleep(2)

        # Esperar a que el sistema esté estable (descartar ANR del Launcher)
        # Requiere 3 ciclos consecutivos sin ANR antes de continuar
        log.info("Waiting for system to stabilize...")
        stable_count = 0
        for _ in range(30):
            xml = device.dump_hierarchy()
            if "isn't responding" in xml or "not responding" in xml.lower():
                log.info("System ANR during startup — tapping Wait")
                tap_adb(350, 1090)
                stable_count = 0
                time.sleep(4)
            else:
                stable_count += 1
                log.info(f"  System stable {stable_count}/3")
                if stable_count >= 3:
                    log.info("System stabilized")
                    break
                time.sleep(3)

        device.app_stop(APP_PACKAGE)
        time.sleep(3)
        device.app_start(APP_PACKAGE)
        log.info("App started — waiting 30s for initial load...")
        time.sleep(30)

        if not login(device):
            log.error("Login failed — aborting")
            return

        if not navigate_to_colectivas(device):
            log.error("Navigation failed — aborting")
            return

        # En CI sin forzado: esperar con la app ya abierta en COLECTIVAS
        # hasta las 22:00 exactas (20:00 UTC) antes de intentar la reserva
        if os.environ.get("CI") and not force:
            now = datetime.utcnow()
            target = now.replace(hour=20, minute=0, second=0, microsecond=0)
            wait = (target - now).total_seconds()
            if wait > 0:
                log.info(f"App ready. Waiting {wait:.0f}s until 22:00 Madrid (20:00 UTC)...")
                time.sleep(wait)
            log.info("22:00 reached — starting booking loop")

        book_class_with_refresh(device, clase)

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
