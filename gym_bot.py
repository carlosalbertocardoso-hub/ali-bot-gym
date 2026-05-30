"""
Gym Bot — Reserva automática de clases en Technogym vía Geelark cloud phone
============================================================================
- Domingo 22:00  → Body Tono lunes 18:00
- Martes 22:00   → Body Tono miércoles 18:00
- Miércoles 22:00 → POWER jueves 19:00

Arquitectura:
    GitHub Actions (cron) → GeelarkClient (REST API) → ADB remoto → uiautomator2 → Technogym app
"""
import hashlib
import os
import re
import subprocess
import time
import uuid
import logging
import requests
import unicodedata
from datetime import datetime, timedelta

import uiautomator2 as u2

# ============================================================
# CONFIGURACIÓN
# ============================================================
EMAIL    = "aliciaramirezcaballero@gmail.com"
PASSWORD = "gimnasio"
APP_PACKAGE = "com.technogym.tgapp"

# Credenciales Geelark — se leen de variables de entorno / GitHub Secrets
GEELARK_APP_ID  = os.environ.get("GEELARK_APP_ID", "")
GEELARK_API_KEY = os.environ.get("GEELARK_API_KEY", "")
GEELARK_PHONE_ID = os.environ.get("GEELARK_PHONE_ID", "")

GEELARK_BASE_URL = "https://openapi.geelark.com"

BASE_DIR       = os.path.dirname(os.path.abspath(__file__))
LOG_FILE       = os.path.join(BASE_DIR, "gym_bot.log")
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

CLASES = [
    {"nombre": "BODYTONO", "hora": "18:00", "dia_clase": 0, "dia_reserva": 6},
    {"nombre": "BODYTONO", "hora": "18:00", "dia_clase": 2, "dia_reserva": 1},
    {"nombre": "POWER",    "hora": "19:00", "dia_clase": 3, "dia_reserva": 2},
]

HOME_INDICATORS = [
    "colectivas", "reserva una clase", "tus citas", "entrenador",
    "explorar", "movergy", "tus planes",
    "book a class", "your appointments", "reservar cita",
]
AUTHENTICATED_INDICATORS = [
    EMAIL.lower(), "daily moves", "movergy index", "coach", "results",
    "challenges", "precision program",
]
LOGIN_FORM_INDICATORS = [
    "loginpage.username.textfield", "loginpage.password.textfield",
    "loginpage.login.button", "loginpage.next.button",
]
DISMISS_RESOURCE_IDS = [
    "pushNotificationPermission.dismiss.button",
    "authHealthPage.skip.button",
]
DISMISS_TEXTS = [
    "MAYBE LATER", "Maybe Later", "Not now", "No thanks",
    "SKIP FOR NOW", "SKIP", "CONTINUE", "OK", "Allow",
    "While using the app", "Only this time",
    "START", "Empezar", "Siguiente", "ACEPTAR",
    "Permitir", "Mientras se usa la app", "Solo esta vez",
    "Seguir", "SEGUIR",
]


# ============================================================
# GEELARK API CLIENT
# ============================================================

class GeelarkClient:
    """Cliente mínimo para la API REST de Geelark."""

    def __init__(self, app_id: str, api_key: str):
        self.app_id  = app_id
        self.api_key = api_key

    def _headers(self) -> dict:
        ts       = str(int(time.time() * 1000))
        trace_id = uuid.uuid4().hex
        nonce    = trace_id[:6]
        raw      = f"{self.app_id}{trace_id}{ts}{nonce}{self.api_key}"
        sign     = hashlib.sha256(raw.encode()).hexdigest().upper()
        return {
            "Content-Type": "application/json",
            "appId":   self.app_id,
            "traceId": trace_id,
            "ts":      ts,
            "nonce":   nonce,
            "sign":    sign,
        }

    def post(self, path: str, body: dict) -> dict:
        url  = f"{GEELARK_BASE_URL}{path}"
        resp = requests.post(url, json=body, headers=self._headers(), timeout=30)
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") not in (0, 200, None):
            raise RuntimeError(f"Geelark API error on {path}: {data}")
        return data

    # ── Phone lifecycle ──────────────────────────────────────

    def first_phone_id(self) -> str:
        """Devuelve el id interno del primer teléfono de la cuenta."""
        data = self.post("/open/v1/phone/list", {"page": 1, "pageSize": 50})
        d = data.get("data", {})
        phones = d.get("items") or d.get("list", [])
        if phones:
            pid = phones[0].get("id", "")
            log.info(f"  First phone id: {pid}, serialName: {phones[0].get('serialName')}")
            return pid
        raise RuntimeError("No phones found in Geelark account")

    def start_phone(self, phone_id: str):
        log.info(f"Geelark: starting phone {phone_id}")
        self.post("/open/v1/phone/start", {"ids": [phone_id]})

    def stop_phone(self, phone_id: str):
        log.info(f"Geelark: stopping phone {phone_id}")
        self.post("/open/v1/phone/stop", {"ids": [phone_id]})

    def phone_status(self, phone_id: str) -> int:
        """Devuelve el status numérico del teléfono (0=parado, 1=corriendo, 2=arrancando)."""
        data = self.post("/open/v1/phone/list", {"page": 1, "pageSize": 50})
        d = data.get("data", {})
        phones = d.get("items") or d.get("list", [])
        for phone in phones:
            if phone.get("id") == phone_id:
                return int(phone.get("status", -1))
        log.warning(f"  Phone {phone_id} not found in list of {len(phones)} phones")
        return -1

    def wait_phone_running(self, phone_id: str, timeout: int = 120):
        log.info("Waiting for Geelark phone to be running...")
        deadline = time.time() + timeout
        while time.time() < deadline:
            status = self.phone_status(phone_id)
            log.info(f"  Phone status code: {status}")
            if status == 1:
                return
            time.sleep(5)
        raise TimeoutError(f"Phone {phone_id} did not reach running status in {timeout}s")

    def ensure_phone_running(self, phone_id: str, attempts: int = 2, timeout: int = 240):
        for attempt in range(1, attempts + 1):
            log.info(f"Geelark start attempt {attempt}/{attempts}")
            self.start_phone(phone_id)
            try:
                self.wait_phone_running(phone_id, timeout=timeout)
                return
            except TimeoutError:
                if attempt == attempts:
                    raise
                log.warning("Phone stuck while starting; stopping and retrying")
                try:
                    self.stop_phone(phone_id)
                    time.sleep(20)
                except Exception as exc:
                    log.warning(f"Could not stop stuck phone before retry: {exc}")

    # ── ADB ──────────────────────────────────────────────────

    def enable_adb(self, phone_id: str):
        log.info("Geelark: enabling ADB")
        self.post("/open/v1/adb/setStatus", {"ids": [phone_id], "open": True})
        time.sleep(5)  # async op — esperar antes de pedir datos

    def get_adb_info(self, phone_id: str) -> dict:
        """Devuelve dict con ip, port, pwd (contraseña ADB de Geelark)."""
        data = self.post("/open/v1/adb/getData", {"ids": [phone_id]})
        log.info(f"ADB raw response: {data}")
        # La API devuelve la info directamente en data, o en data.items
        d = data.get("data", data)
        if isinstance(d, list):
            return d[0]
        items = d.get("items") or d.get("list")
        if items:
            return items[0]
        # Estructura plana: {'ip': ..., 'port': ..., 'pwd': ...}
        if d.get("ip"):
            return d
        raise RuntimeError(f"No ADB info returned for phone {phone_id}: {data}")


# ============================================================
# ADB — conexión remota al cloud phone
# ============================================================

def _run_adb_cmd(*args, device: str = None, timeout: int = 20):
    cmd = ["adb"]
    if device:
        cmd += ["-s", device]
    cmd += list(args)
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(cmd, returncode=124, stdout="", stderr="timeout")


def connect_adb(ip: str, port: int, password: str) -> str:
    """
    Conecta ADB al cloud phone remoto de Geelark.
    Devuelve el serial 'ip:port' para usar con -s.
    """
    serial = f"{ip}:{port}"
    log.info(f"Connecting ADB to {serial}")
    r = _run_adb_cmd("connect", serial, timeout=15)
    log.info(f"  adb connect: {r.stdout.strip()}")

    # Autenticar con el código de Geelark
    if password:
        time.sleep(2)
        r2 = _run_adb_cmd("shell", "glogin", password, device=serial, timeout=15)
        log.info(f"  glogin: {r2.stdout.strip()}")

    return serial


def wait_adb_ready(serial: str, timeout: int = 60):
    log.info(f"Waiting for ADB device {serial} to be ready...")
    deadline = time.time() + timeout
    while time.time() < deadline:
        r = _run_adb_cmd("shell", "getprop", "sys.boot_completed", device=serial, timeout=10)
        if r.returncode == 0 and r.stdout.strip() == "1":
            log.info("ADB device ready")
            return
        time.sleep(5)
    raise TimeoutError(f"ADB device {serial} not ready after {timeout}s")


def run_adb(serial: str, *args, timeout: int = 20):
    return _run_adb_cmd(*args, device=serial, timeout=timeout)


# ============================================================
# DEVICE — uiautomator2
# ============================================================

def connect_u2(serial: str, max_wait: int = 60):
    deadline = time.time() + max_wait
    last_exc = None
    attempt  = 0
    while time.time() < deadline:
        attempt += 1
        try:
            device = u2.connect(serial)
            _ = device.info
            log.info(f"u2 connected (attempt {attempt}): {device.info.get('productName', '?')}")
            return device
        except Exception as exc:
            last_exc = exc
            log.info(f"  u2 not ready (attempt {attempt}): {exc}")
            time.sleep(4)
    raise RuntimeError(f"u2 server never ready after {max_wait}s: {last_exc}")


def safe_dump(device, retries: int = 3) -> str:
    for attempt in range(1, retries + 1):
        try:
            return device.dump_hierarchy()
        except Exception as exc:
            log.warning(f"dump_hierarchy failed (attempt {attempt}/{retries}): {exc}")
            if attempt == retries:
                raise
            time.sleep(3)
    return ""


# ============================================================
# UI HELPERS
# ============================================================

def screenshot(device, serial: str, name: str):
    path = os.path.join(SCREENSHOT_DIR, f"{name}_{datetime.now():%H%M%S}.png")
    try:
        device.screenshot(path)
    except Exception:
        try:
            result = _run_adb_cmd("exec-out", "screencap", "-p", device=serial, timeout=15)
            if result.returncode == 0 and result.stdout:
                with open(path, "wb") as f:
                    f.write(result.stdout.encode("latin1") if isinstance(result.stdout, str) else result.stdout)
        except Exception:
            pass
    return path


def save_hierarchy(device, name: str):
    try:
        xml = safe_dump(device)
        path = os.path.join(BASE_DIR, f"{name}.xml")
        with open(path, "w", encoding="utf-8") as f:
            f.write(xml)
        return xml
    except Exception as exc:
        log.warning(f"Could not save hierarchy {name}: {exc}")
        return ""


def xml_contains_any(xml: str, needles) -> bool:
    h = xml.lower()
    return any(n.lower() in h for n in needles)


def xml_visible_strings(xml: str):
    values = []
    for attr in ("text", "content-desc", "resource-id"):
        values.extend(v for v in re.findall(fr'{attr}="([^"]+)"', xml) if v.strip())
    return values


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    return "".join(ch for ch in text if not unicodedata.combining(ch)).upper()


def xml_nodes_with_bounds(xml: str):
    nodes = []
    for tag in re.findall(r"<node\b[^>]*>", xml):
        text_match = re.search(r'text="([^"]*)"', tag)
        desc_match = re.search(r'content-desc="([^"]*)"', tag)
        bounds_match = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', tag)
        if not bounds_match:
            continue
        text = (text_match.group(1) if text_match else "") or \
               (desc_match.group(1) if desc_match else "")
        if not text.strip():
            continue
        x1, y1, x2, y2 = map(int, bounds_match.groups())
        nodes.append({
            "text": text.strip(),
            "norm": normalize_text(text),
            "bounds": (x1, y1, x2, y2),
            "cx": (x1 + x2) // 2,
            "cy": (y1 + y2) // 2,
        })
    return nodes


def tap_adb(serial: str, x: int, y: int):
    run_adb(serial, "shell", "input", "tap", str(x), str(y), timeout=10)
    time.sleep(0.8)


def tap_by_bounds(serial: str, element):
    b  = element.info.get("bounds", {})
    cx = (b["left"] + b["right"]) // 2
    cy = (b["top"] + b["bottom"]) // 2
    tap_adb(serial, cx, cy)
    return cx, cy


def bring_app_foreground(serial: str):
    run_adb(serial, "shell", "monkey", "-p", APP_PACKAGE,
            "-c", "android.intent.category.LAUNCHER", "1", timeout=15)
    time.sleep(2)


def dismiss_anr(device, serial: str) -> bool:
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
                tap_by_bounds(serial, btn)
                time.sleep(3)
                return True
            except Exception:
                pass
    tap_adb(serial, 725, 1090)
    time.sleep(3)
    return True


def dismiss_any_overlay(device, serial: str) -> bool:
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


def wait_for_element(device, serial: str, resource_id: str, timeout: int = 15):
    deadline = time.time() + timeout
    while time.time() < deadline:
        dismiss_anr(device, serial)
        el = device(resourceId=resource_id)
        if el.exists:
            return el
        time.sleep(1)
    return None


def click_element(device, serial: str, resource_id=None, text=None,
                  fallback_xy=None, timeout: int = 10) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        dismiss_anr(device, serial)
        el = device(resourceId=resource_id) if resource_id else device(textContains=text)
        if el.exists:
            try:
                tap_by_bounds(serial, el)
                log.info(f"  Clicked: {resource_id or text}")
                return True
            except Exception:
                pass
        time.sleep(0.5)
    if fallback_xy:
        log.info(f"  Fallback tap at {fallback_xy} for {resource_id or text}")
        tap_adb(serial, *fallback_xy)
        return True
    log.info(f"  Not found: {resource_id or text}")
    return False


# ============================================================
# ENTRADA DE TEXTO
# ============================================================

def adb_type(serial: str, text: str):
    safe = text.replace("%", "%25").replace(" ", "%s")
    r = run_adb(serial, "shell", "input", "text", safe, timeout=30)
    if r.returncode not in (0, 124):
        log.warning(f"adb input text rc={r.returncode}: {r.stderr.strip()}")


def enter_text(device, serial: str, resource_id: str, text: str, fallback_xy=(540, 315)):
    el = device(resourceId=resource_id)
    if el.exists:
        try:
            tap_by_bounds(serial, el)
        except Exception:
            tap_adb(serial, *fallback_xy)
    else:
        tap_adb(serial, *fallback_xy)
    time.sleep(0.5)

    run_adb(serial, "shell", "input", "keyevent", "KEYCODE_SELECT_ALL", timeout=5)
    time.sleep(0.2)
    run_adb(serial, "shell", "input", "keyevent", "KEYCODE_DEL", timeout=5)
    time.sleep(0.3)

    if el.exists:
        try:
            tap_by_bounds(serial, el)
        except Exception:
            tap_adb(serial, *fallback_xy)
    else:
        tap_adb(serial, *fallback_xy)
    time.sleep(0.3)

    adb_type(serial, text)
    time.sleep(0.5)
    screenshot(device, serial, f"after_type_{resource_id.split('.')[-1]}")
    log.info(f"  Text entered in {resource_id}")


# ============================================================
# LOGIN
# ============================================================

def _tap_login_button(device, serial: str):
    btn = device(resourceId="onboarding.alreadySignedIn.button")
    if btn.exists:
        try:
            cx, cy = tap_by_bounds(serial, btn)
            log.info(f"  Tapped LOG IN at ({cx}, {cy})")
            return True
        except Exception:
            pass
    log.info("  LOG IN fallback tap (540, 1710)")
    tap_adb(serial, 540, 1710)
    return True


def login(device, serial: str) -> bool:
    log.info("--- LOGIN ---")
    screenshot(device, serial, "login_start")

    for attempt in range(25):
        dismiss_anr(device, serial)
        try:
            xml = safe_dump(device)
        except Exception:
            time.sleep(3)
            continue

        if xml_contains_any(xml, HOME_INDICATORS):
            log.info("Already at app home — skipping login")
            return True

        if "onboarding.alreadySignedin.button" in xml.lower() or \
           "already signed in" in xml.lower() or \
           "log in" in xml.lower():
            _tap_login_button(device, serial)
            time.sleep(6)
            break

        if "loginpage.username.textfield" in xml.lower():
            log.info("Login form already visible")
            break

        if dismiss_any_overlay(device, serial):
            continue

        if attempt in (5, 10, 15, 20):
            log.info(f"  Blind LOG IN tap (attempt {attempt})")
            screenshot(device, serial, f"blind_login_{attempt}")
            _tap_login_button(device, serial)
            time.sleep(6)

        time.sleep(3)

    time.sleep(3)
    screenshot(device, serial, "login_form")
    email_el = wait_for_element(device, serial, "loginPage.username.textfield", timeout=20)
    if not email_el:
        log.warning("Email field not found")
        save_hierarchy(device, "login_failed_hierarchy")
        screenshot(device, serial, "login_form_not_found")
        return False

    enter_text(device, serial, "loginPage.username.textfield", EMAIL, fallback_xy=(540, 315))
    log.info(f"Email entered: {EMAIL}")
    time.sleep(1)

    click_element(device, serial, resource_id="loginPage.next.button",
                  fallback_xy=(540, 1328), timeout=5)
    log.info("Tapped NEXT after email")
    time.sleep(3)

    pw_el = wait_for_element(device, serial, "loginPage.password.textfield", timeout=15)
    if not pw_el:
        log.warning("Password field not found")
        screenshot(device, serial, "login_pw_not_found")
        return False

    enter_text(device, serial, "loginPage.password.textfield", PASSWORD, fallback_xy=(540, 525))
    log.info("Password entered")
    time.sleep(1)

    if not click_element(device, serial, resource_id="loginPage.login.button", timeout=3):
        click_element(device, serial, resource_id="loginPage.next.button",
                      fallback_xy=(540, 1328), timeout=5)
    log.info("Login submitted")
    time.sleep(8)
    screenshot(device, serial, "after_login_submit")

    for i in range(40):
        dismiss_anr(device, serial)
        try:
            xml = safe_dump(device)
        except Exception:
            time.sleep(5)
            continue

        visible = xml_visible_strings(xml)
        log.info(f"  Post-login {i+1}/40: {visible[:12]}")

        if xml_contains_any(xml, HOME_INDICATORS):
            log.info("App home reached")
            screenshot(device, serial, "home_reached")
            return True

        if dismiss_any_overlay(device, serial):
            continue

        if xml_contains_any(xml, AUTHENTICATED_INDICATORS) and \
           not xml_contains_any(xml, LOGIN_FORM_INDICATORS):
            log.info("Authenticated home (main home not yet visible)")
            return True

        if i == 20 and "contentloading" in xml.lower():
            log.info("Still loading at iter 20 — restarting app")
            device.app_stop(APP_PACKAGE)
            time.sleep(3)
            device.app_start(APP_PACKAGE)
            time.sleep(15)

        time.sleep(5)

    log.warning("Login timeout — could not reach home")
    screenshot(device, serial, "login_failed")
    save_hierarchy(device, "login_failed_hierarchy")
    return False


# ============================================================
# NAVEGACIÓN
# ============================================================

def navigate_to_colectivas(device, serial: str) -> bool:
    log.info("--- NAVIGATE TO COLECTIVAS ---")

    # Marcadores reales de la pantalla Colectivas (ver capturas):
    #   pestañas superiores "Colectivas" / "Club"
    #   filtros "Hora de inicio" / "Entrenador"
    #   selector de dias LUN..DOM
    # NOTA: "SPORTS CENTER" / "CIRCULO MERCANTIL" es solo la cabecera del club,
    # nunca se usa como indicador ni como target de navegacion.
    DAY_ABBR = ("lun", "mar", "mié", "mie", "jue", "vie", "sáb", "sab", "dom")

    def is_colectivas_screen(xml: str) -> bool:
        lowered = xml.lower()
        # "Reserva una clase" es la card del HOME, no la lista de clases:
        # NO sirve para confirmar que ya estamos en Colectivas.
        # Confirmamos con marcadores que SOLO existen en la lista de clases:
        #   - filtro "Hora de inicio"
        #   - pestaña hermana "Club" (solo aparece junto a Colectivas)
        #   - selector de dias con >=3 abreviaturas visibles
        if "hora de inicio" in lowered:
            return True
        if "colectivas" in lowered and "club" in lowered:
            return True
        if sum(1 for d in DAY_ABBR if d in lowered) >= 3:
            return True
        return False

    def dump_stage(stage: str) -> str:
        try:
            xml = safe_dump(device)
            visible = xml_visible_strings(xml)
            useful = [
                v for v in visible
                if any(marker in normalize_text(v) for marker in (
                    "RESERVA", "COLECTIVAS", "HORA", "SEGUIR",
                    "RESERVAR", "OMNIA", "BODYTONO", "POWER",
                    "ENTRENADOR", "EXPLORAR", "RETOS", "RESULTADOS",
                ))
            ]
            log.info(f"  {stage} markers: {useful[:12]}")
            return xml
        except Exception as exc:
            log.warning(f"  Could not dump {stage}: {exc}")
            return ""

    def is_colectivas_visual(stage: str) -> bool:
        # 1) XML: dump_hierarchy puede devolver el arbol stale si se llama
        #    justo despues de un tap. Esperamos a que u2 vea la pantalla nueva.
        try:
            device.wait_activity(APP_PACKAGE, timeout=3)
        except Exception:
            pass
        try:
            xml = safe_dump(device)
            if is_colectivas_screen(xml):
                log.info("  Navigation confirmed by XML (Colectivas screen)")
                return True
            log.info(f"  XML strings sample: {xml_visible_strings(xml)[:8]}")
        except Exception as exc:
            log.warning(f"  XML confirm failed: {exc}")

        # 2) OCR como respaldo. Aceptamos marcadores estables de la pantalla
        #    de clases: pestañas, filtros y dias. Nunca la cabecera del club.
        safe_stage = re.sub(r"[^A-Za-z0-9_]+", "_", stage).strip("_").lower()
        words = ocr_screen_words(device, serial, f"ocr_nav_{safe_stage}")
        joined = "".join(compact_norm(word["text"]) for word in words)
        # Marcadores que existen SOLO en la pantalla de clases, nunca en home:
        #   HORADEINICIO / SEGUIR / RESERVAR / CLUB (pestana hermana)
        # CLUB es clave: el OCR lo lee fiablemente y no aparece en el home.
        markers = (
            "HORADEINICIO", "SEGUIR", "RESERVAR", "RESERVADA", "CANCELAR", "CLUB",
        )
        matched = next((marker for marker in markers if marker in joined), None)
        if matched:
            log.info(f"  Navigation confirmed by OCR marker: {matched}")
            return True
        # Selector de dias: si el OCR lee >=3 abreviaturas, estamos en la lista.
        day_tokens = ("LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM")
        day_hits = sum(1 for d in day_tokens if d in joined)
        if day_hits >= 3:
            log.info(f"  Navigation confirmed by OCR day selector ({day_hits} days)")
            return True
        log.info(f"  OCR joined (nav confirm): {joined[:120]}")
        return False

    def tap_nav_text_by_ocr(stage: str, targets, y_min: float = 0.0, y_max: float = 1.0) -> bool:
        safe_stage = re.sub(r"[^A-Za-z0-9_]+", "_", stage).strip("_").lower()
        words = ocr_screen_words(device, serial, f"ocr_nav_tap_{safe_stage}")
        if not words:
            return False
        try:
            _, height = device.window_size()
        except Exception:
            height = 9999

        lines = ocr_lines(words)
        target_norms = [compact_norm(target) for target in targets]
        candidates = []
        for line in lines:
            if not (height * y_min <= line["cy"] <= height * y_max):
                continue
            line_norm = compact_norm(line["text"])
            matched = next((target for target in target_norms if target and target in line_norm), None)
            if matched:
                candidates.append((line, matched))

        if not candidates:
            log.info(f"  OCR nav tap found no target for {targets} in {stage}")
            return False

        line, matched = candidates[0]
        log.info(f"  OCR nav tapping {matched} at ({line['cx']},{line['cy']}) from '{line['text']}'")
        tap_adb(serial, line["cx"], line["cy"])
        time.sleep(5)
        return True

    if is_colectivas_visual("initial screen"):
        log.info("  Already on Colectivas")
        return True

    def try_booking_entry(stage: str) -> bool:
        if tap_nav_text_by_ocr(stage, ("Reserva una clase", "Reservar cita", "Book a class"), y_min=0.45, y_max=0.82):
            xml = dump_stage(f"After OCR booking-entry tap from {stage}")
            screenshot(device, serial, "after_navigate_colectivas")
            save_hierarchy(device, "after_navigate_hierarchy")
            if is_colectivas_screen(xml) or is_colectivas_visual(f"After OCR booking-entry tap from {stage}"):
                log.info("  Navigation completed")
                return True

        for txt in ("Reserva una clase", "Reservar cita", "Book a class", "RESERVA UNA CLASE"):
            try:
                el = device(textContains=txt)
                if el.exists:
                    tap_by_bounds(serial, el)
                    log.info(f"  Tapped '{txt}'")
                    time.sleep(5)
                    xml = dump_stage(f"After '{txt}' tap")
                    screenshot(device, serial, "after_navigate_colectivas")
                    save_hierarchy(device, "after_navigate_hierarchy")
                    if is_colectivas_screen(xml):
                        log.info("  Navigation completed")
                        return True
                    if is_colectivas_visual(f"After {txt} tap"):
                        log.info("  Navigation completed")
                        return True
            except Exception as exc:
                log.warning(f"  Tap '{txt}' failed: {exc}")

        try:
            width, height = device.window_size()
            # Home screen card "Reserva una clase" (red-boxed in the reference
            # screenshot): left/middle of the card, above "Tus planes".
            for x_ratio, y_ratio in ((0.38, 0.64), (0.88, 0.64)):
                x, y = int(width * x_ratio), int(height * y_ratio)
                log.info(f"  Coordinate fallback tap booking entry from {stage} ({x},{y})")
                tap_adb(serial, x, y)
                time.sleep(5)
                xml = dump_stage(f"After booking-entry coordinate tap from {stage}")
                screenshot(device, serial, "after_navigate_colectivas")
                save_hierarchy(device, "after_navigate_hierarchy")
                if is_colectivas_screen(xml):
                    log.info("  Navigation completed")
                    return True
                if is_colectivas_visual(f"After booking-entry coordinate tap from {stage}"):
                    log.info("  Navigation completed")
                    return True
        except Exception as exc:
            log.warning(f"  Booking-entry coordinate fallback failed: {exc}")
        return False

    # Entrada principal desde Entrenador: card/boton "Reserva una clase".
    if try_booking_entry("initial screen"):
        return True

    # Fallback: pestana inferior COLECTIVAS.
    if tap_nav_text_by_ocr("bottom nav", ("COLECTIVAS",), y_min=0.82, y_max=1.0):
        xml2 = dump_stage("After OCR COLECTIVAS tab")
        screenshot(device, serial, "after_navigate_colectivas")
        save_hierarchy(device, "after_navigate_hierarchy")
        if is_colectivas_screen(xml2) or is_colectivas_visual("After OCR COLECTIVAS tab"):
            log.info("  Navigation completed")
            return True
        if try_booking_entry("OCR COLECTIVAS tab"):
            return True

    for txt in ("COLECTIVAS", "Colectivas"):
        try:
            el = device(textContains=txt)
            if el.exists:
                tap_by_bounds(serial, el)
                log.info(f"  Tapped bottom tab '{txt}'")
                time.sleep(5)
                xml2 = dump_stage(f"After '{txt}' tab")
                screenshot(device, serial, "after_navigate_colectivas")
                save_hierarchy(device, "after_navigate_hierarchy")
                if is_colectivas_screen(xml2):
                    log.info("  Navigation completed")
                    return True
                if is_colectivas_visual(f"After {txt} tab"):
                    log.info("  Navigation completed")
                    return True
                if try_booking_entry(f"{txt} tab"):
                    return True
        except Exception as exc:
            log.warning(f"  Tap bottom tab '{txt}' failed: {exc}")

    # Bottom nav "COLECTIVAS" (red-boxed in the reference screenshot).
    try:
        width, height = device.window_size()
        x, y = int(width * 0.30), int(height * 0.94)
        log.info(f"  Coordinate fallback tap Colectivas ({x},{y})")
        tap_adb(serial, x, y)
        time.sleep(5)
        xml3 = dump_stage("After coordinate Colectivas tap")
        save_hierarchy(device, "after_navigate_hierarchy")
        screenshot(device, serial, "after_navigate_colectivas")
        if is_colectivas_screen(xml3):
            log.info("  Navigation completed")
            return True
        if is_colectivas_visual("After coordinate Colectivas tap"):
            log.info("  Navigation completed")
            return True
        if try_booking_entry("coordinate tab"):
            return True
    except Exception as exc:
        log.warning(f"  Coordinate fallback failed: {exc}")

    # Si aparece una vista intermedia, tocar la subpestana superior Colectivas
    # antes de buscar filtros y tarjetas.
    try:
        width, height = device.window_size()
        x, y = int(width * 0.24), int(height * 0.20)
        log.info(f"  Coordinate fallback tap top Colectivas subtab ({x},{y})")
        tap_adb(serial, x, y)
        time.sleep(5)
        xml4 = dump_stage("After top Colectivas subtab tap")
        save_hierarchy(device, "after_navigate_hierarchy")
        screenshot(device, serial, "after_navigate_colectivas")
        if is_colectivas_screen(xml4):
            log.info("  Navigation completed")
            return True
        if is_colectivas_visual("After top Colectivas subtab tap"):
            log.info("  Navigation completed")
            return True
    except Exception as exc:
        log.warning(f"  Top Colectivas subtab fallback failed: {exc}")

    for txt in ("Hora de inicio", "SEGUIR", "RESERVAR"):
        try:
            el = device(textContains=txt)
            if el.exists:
                log.info(f"  Navigation completed by visible marker: {txt}")
                return True
        except Exception as exc:
            log.warning(f"  Marker check failed for '{txt}': {exc}")

    log.warning("  Could not confirm Colectivas screen")
    return False





# ============================================================
# RESERVA
# ============================================================

def select_day(device, serial: str, dia_clase: int) -> bool:
    DAY_LABELS = {
        0: ["LUN", "MON"], 1: ["MAR", "TUE"], 2: ["MIÉ", "MIE", "WED"],
        3: ["JUE", "THU"], 4: ["VIE", "FRI"], 5: ["SÁB", "SAB", "SAT"],
        6: ["DOM", "SUN"],
    }
    today      = datetime.now()
    days_ahead = (dia_clase - today.weekday()) % 7 or 7
    target     = today + timedelta(days=days_ahead)
    day_num    = str(target.day)
    log.info(f"  Looking for {target.strftime('%a %d')} (weekday {dia_clase})")

    try:
        xml = safe_dump(device)
    except Exception:
        xml = ""

    nodes = xml_nodes_with_bounds(xml)
    target_labels = {normalize_text(label) for label in DAY_LABELS[dia_clase]}
    label_nodes = [n for n in nodes if n["norm"] in target_labels]
    number_nodes = [n for n in nodes if n["text"] == day_num]

    best_pair = None
    best_score = None
    for label_node in label_nodes:
        for number_node in number_nodes:
            dx = abs(label_node["cx"] - number_node["cx"])
            dy = number_node["cy"] - label_node["cy"]
            if dx <= 90 and 0 <= dy <= 180:
                score = dx + dy
                if best_score is None or score < best_score:
                    best_pair = (label_node, number_node)
                    best_score = score
    if best_pair:
        label_node, number_node = best_pair
        log.info(f"  Selected day by date strip: {label_node['text']} {number_node['text']}")
        tap_adb(serial, number_node["cx"], number_node["cy"])
        time.sleep(2)
        return True

    try:
        width, height = device.window_size()
        candidates = [
            n for n in number_nodes
            if int(height * 0.22) <= n["cy"] <= int(height * 0.45)
        ]
        if len(candidates) == 1:
            n = candidates[0]
            log.info(f"  Selected day by visible number: {n['text']}")
            tap_adb(serial, n["cx"], n["cy"])
            time.sleep(2)
            return True
    except Exception:
        pass

    for label in DAY_LABELS[dia_clase]:
        pattern = rf'text="({re.escape(label)}\s*{re.escape(day_num)}|{re.escape(day_num)}\s*{re.escape(label)})"'
        m = re.search(pattern, xml, re.IGNORECASE)
        if m:
            el = device(text=m.group(1))
            if not el.exists:
                el = device(textContains=label)
            if el.exists:
                try:
                    tap_by_bounds(serial, el)
                    log.info(f"  Selected day: {m.group(1)}")
                    time.sleep(2)
                    return True
                except Exception:
                    pass

    for label in DAY_LABELS[dia_clase]:
        el = device(textContains=label)
        if el.exists:
            try:
                tap_by_bounds(serial, el)
                log.info(f"  Selected day (fallback): {label}")
                time.sleep(2)
                return True
            except Exception:
                pass

    # Fallback OCR: buscar el numero del dia en la franja del selector.
    # El XML de uiautomator no siempre expone los nodos del selector de dias.
    log.info(f"  XML day search failed, trying OCR for day {day_num}...")
    try:
        words = ocr_screen_words(device, serial, f"ocr_day_{day_num}")
        width, height = device.window_size()
        # El selector de dias ocupa aprox y=22%-42% de la pantalla.
        y_min = int(height * 0.22)
        y_max = int(height * 0.42)
        day_labels_norm = {normalize_text(l) for l in DAY_LABELS[dia_clase]}
        # Buscar el numero exacto en la franja del selector.
        number_words = [
            w for w in words
            if w["text"].strip() == day_num
            and y_min <= w["bounds"][1] <= y_max
        ]
        if number_words:
            w = number_words[0]
            cx = (w["bounds"][0] + w["bounds"][2]) // 2
            cy = (w["bounds"][1] + w["bounds"][3]) // 2
            log.info(f"  OCR: tapping day {day_num} at ({cx},{cy})")
            tap_adb(serial, cx, cy)
            time.sleep(2)
            return True
        # Buscar por abreviatura del dia si el numero no aparece.
        label_words = [
            w for w in words
            if normalize_text(w["text"]) in day_labels_norm
            and y_min <= w["bounds"][1] <= y_max
        ]
        if label_words:
            w = label_words[0]
            cx = (w["bounds"][0] + w["bounds"][2]) // 2
            cy = (w["bounds"][1] + w["bounds"][3]) // 2
            log.info(f"  OCR: tapping day label {w['text']} at ({cx},{cy})")
            tap_adb(serial, cx, cy)
            time.sleep(2)
            return True
    except Exception as exc:
        log.warning(f"  OCR day search failed: {exc}")

    log.warning(f"  Day not found: weekday {dia_clase} (date {day_num})")
    return False


def time_variants(hora: str):
    variants = {hora}
    m = re.match(r"^0?(\d{1,2}):(\d{2})$", hora.strip())
    if m:
        hour, minute = int(m.group(1)), m.group(2)
        variants.add(f"{hour}:{minute}")
        variants.add(f"{hour:02d}:{minute}")
    return sorted(variants, key=len)


def ocr_screen_words(device, serial: str, name: str = "ocr"):
    path = screenshot(device, serial, name)
    try:
        from PIL import Image, ImageOps
        import pytesseract
        from pytesseract import Output
    except Exception as exc:
        log.warning(f"  OCR unavailable: {exc}")
        return []

    words = []
    try:
        base = Image.open(path).convert("RGB")
        regions = [
            ("full", base, 0, 0),
            ("cards", base.crop((0, int(base.height * 0.34), base.width, int(base.height * 0.90))), 0, int(base.height * 0.34)),
        ]
        pass_no = 0
        for region_name, region, offset_x, offset_y in regions:
            gray = ImageOps.grayscale(region)
            prepared = [
                ("gray", ImageOps.autocontrast(gray)),
                ("invert", ImageOps.autocontrast(ImageOps.invert(gray))),
                ("threshold", ImageOps.autocontrast(ImageOps.invert(gray)).point(lambda p: 255 if p > 115 else 0)),
            ]
            for variant_name, img in prepared:
                scale = 2
                img = img.resize((img.width * scale, img.height * scale))
                try:
                    data = pytesseract.image_to_data(
                        img,
                        lang="eng",
                        config="--oem 3 --psm 11",
                        output_type=Output.DICT,
                    )
                except Exception as exc:
                    log.warning(f"  OCR pass failed ({region_name}/{variant_name}): {exc}")
                    continue
                pass_no += 1
                for i, text in enumerate(data.get("text", [])):
                    text = (text or "").strip()
                    if not text:
                        continue
                    try:
                        conf = float(data["conf"][i])
                    except Exception:
                        conf = -1
                    if conf < 20:
                        continue
                    left = int(data["left"][i] / scale) + offset_x
                    top = int(data["top"][i] / scale) + offset_y
                    width = int(data["width"][i] / scale)
                    height = int(data["height"][i] / scale)
                    line_key = (
                        pass_no,
                        data.get("block_num", [0])[i],
                        data.get("par_num", [0])[i],
                        data.get("line_num", [0])[i],
                    )
                    words.append({
                        "text": text,
                        "norm": normalize_text(text),
                        "conf": conf,
                        "bounds": (left, top, left + width, top + height),
                        "cx": left + width // 2,
                        "cy": top + height // 2,
                        "line_key": line_key,
                    })
    except Exception as exc:
        log.warning(f"  OCR failed: {exc}")
        return []

    deduped = []
    seen = set()
    for word in sorted(words, key=lambda w: (-w["conf"], w["bounds"][1], w["bounds"][0])):
        key = (word["norm"], round(word["cx"] / 12), round(word["cy"] / 12))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(word)

    words = sorted(deduped, key=lambda w: (w["bounds"][1], w["bounds"][0]))
    log.info(f"  OCR words ({len(words)}): {[w['text'] for w in words[:80]]}")
    return words


def ocr_lines(words):
    grouped = {}
    for word in words:
        grouped.setdefault(word["line_key"], []).append(word)

    lines = []
    for line_words in grouped.values():
        line_words = sorted(line_words, key=lambda w: w["bounds"][0])
        text = " ".join(w["text"] for w in line_words)
        x1 = min(w["bounds"][0] for w in line_words)
        y1 = min(w["bounds"][1] for w in line_words)
        x2 = max(w["bounds"][2] for w in line_words)
        y2 = max(w["bounds"][3] for w in line_words)
        lines.append({
            "text": text,
            "norm": normalize_text(text),
            "bounds": (x1, y1, x2, y2),
            "cx": (x1 + x2) // 2,
            "cy": (y1 + y2) // 2,
            "words": line_words,
        })
    return sorted(lines, key=lambda line: (line["bounds"][1], line["bounds"][0]))


def normalized_time_text(text: str) -> str:
    return re.sub(r"[^0-9:]", "", text.replace(".", ":"))


def compact_norm(text: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", normalize_text(text))


def find_and_tap_by_ocr(device, serial: str, nombre: str, hora: str):
    words = ocr_screen_words(device, serial, "ocr_booking")
    if not words:
        return None

    lines = ocr_lines(words)
    horas = set(time_variants(hora))
    target_name = compact_norm(nombre)
    time_lines = [
        line for line in lines
        if any(h in normalized_time_text(line["text"]) for h in horas)
    ]
    name_lines = [line for line in lines if target_name in compact_norm(line["text"])]
    action_words = [
        word for word in words
        if word["norm"] in ("RESERVAR", "SEGUIR", "UNETE", "CANCELAR")
    ]
    log.info(
        "  OCR matches: "
        f"time={[l['text'] for l in time_lines[:3]]}, "
        f"name={[l['text'] for l in name_lines[:3]]}, "
        f"actions={[w['text'] for w in action_words[:5]]}"
    )

    best = None
    best_score = None
    for time_line in time_lines:
        for name_line in name_lines:
            dy = abs(time_line["cy"] - name_line["cy"])
            if dy > 220:
                continue
            top = min(time_line["bounds"][1], name_line["bounds"][1]) - 90
            bottom = max(time_line["bounds"][3], name_line["bounds"][3]) + 220
            for action in action_words:
                if not (top <= action["cy"] <= bottom):
                    continue
                score = dy + abs(action["cy"] - name_line["cy"])
                if best_score is None or score < best_score:
                    best = action
                    best_score = score

    if not best:
        log.info("  OCR could not pair class/time with an action button")
        return None

    result = "followed" if best["norm"] == "SEGUIR" else "booked"
    if best["norm"] == "CANCELAR":
        result = "already"
    elif best["norm"] == "UNETE":
        result = "waitlist"
    log.info(f"  OCR tapping {best['text']} at ({best['cx']},{best['cy']})")
    tap_adb(serial, best["cx"], best["cy"])
    return result


def visual_follow_fallback(device, serial: str, nombre: str, hora: str):
    # Last resort for the one-off OMNIA SEGUIR test when the list text is not
    # exposed in the uiautomator hierarchy. Do not use this as generic booking
    # logic because button Y positions vary by time slot and scroll position.
    if not os.environ.get("FORCE_CLASS"):
        return None

    if normalize_text(nombre) != "OMNIA":
        return None

    normalized_hours = set(time_variants(hora))
    if "9:30" not in normalized_hours and "09:30" not in normalized_hours:
        return None

    log.info(
        f"  Visual fallback available for {nombre} {hora}, "
        "but not used because OCR/XML did not confirm the card"
    )
    return None


def find_and_tap_booking_button(device, serial: str, nombre: str, hora: str):
    result = find_and_tap_by_ocr(device, serial, nombre, hora)
    if result:
        return result

    try:
        xml = safe_dump(device)
    except Exception as exc:
        log.warning(f"  dump_hierarchy failed: {exc}")
        return None

    lines      = xml.split('\n')
    horas      = time_variants(hora)
    hora_idx   = [i for i, l in enumerate(lines) if any(h in l for h in horas)]
    nombre_idx = [i for i, l in enumerate(lines) if nombre.upper() in l.upper()]
    log.info(f"  '{hora}' variants {horas} at lines {hora_idx[:5]}, '{nombre}' at lines {nombre_idx[:5]}")

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
        return visual_follow_fallback(device, serial, nombre, hora)

    start = max(0, card_line - 50)
    end   = min(len(lines), card_line + 50)
    block = '\n'.join(lines[start:end])

    if 'CANCELAR' in block or 'Cancelar' in block:
        log.info("  Already booked (CANCELAR)")
        return 'already'

    if re.search(r'[ÚU]NETE', block, re.IGNORECASE):
        log.info("  Class full — trying waitlist")
        m = re.search(r'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="[ÚúUu]NETE"', block)
        if not m:
            m = re.search(r'text="[ÚúUu]NETE"[^>]*/?>?\s*<[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', block)
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            tap_adb(serial, (x1 + x2) // 2, (y1 + y2) // 2)
            return 'waitlist'
        el = device(textContains="NETE")
        if el.exists:
            el.click()
            return 'waitlist'
        return 'full'

    for action_text, result in (("RESERVAR", "booked"), ("SEGUIR", "followed")):
        m = re.search(rf'bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"[^>]*text="{action_text}"', block)
        if not m:
            m = re.search(rf'text="{action_text}"[^>]*/?>?\s*<[^>]*bounds="\[(\d+),(\d+)\]\[(\d+),(\d+)\]"', block)
        if m:
            x1, y1, x2, y2 = map(int, m.groups())
            tap_adb(serial, (x1 + x2) // 2, (y1 + y2) // 2)
            log.info(f"  Tapped {action_text} at ({(x1+x2)//2}, {(y1+y2)//2})")
            return result

        el = device(text=action_text)
        if el.exists:
            el.click()
            log.info(f"  Clicked {action_text} via u2")
            return result

    log.info("  RESERVAR/SEGUIR not found in card block")
    return None


def verify_action_result(device, serial: str, result: str) -> bool:
    markers = {
        "followed": ["DEJARDESEGUIR"],
        "booked": ["CANCELAR", "CANCEL", "RESERVADA", "BOOKED"],
        "waitlist": ["CANCELAR", "CANCEL", "LISTADEESPERA", "WAITLIST", "ENLISTA"],
    }.get(result, [])
    if not markers:
        log.warning(f"  No verification markers configured for result: {result}")
        return False

    label = {
        "followed": "SEGUIR",
        "booked": "RESERVAR",
        "waitlist": "LISTA DE ESPERA",
    }.get(result, result)

    for attempt in range(1, 4):
        try:
            xml = safe_dump(device)
        except Exception:
            xml = ""
        xml_norm = compact_norm(xml)
        matched = next((marker for marker in markers if marker in xml_norm), None)
        if matched:
            log.info(f"  {label} verified by XML: {matched} visible (attempt {attempt})")
            return True

        words = ocr_screen_words(device, serial, f"ocr_verify_{result}_{attempt}")
        ocr_norm = "".join(compact_norm(w["text"]) for w in words)
        matched = next((marker for marker in markers if marker in ocr_norm), None)
        if matched:
            log.info(f"  {label} verified by OCR: {matched} visible (attempt {attempt})")
            return True

        time.sleep(2)

    log.warning(f"  {label} not verified; success will not be reported")
    screenshot(device, serial, f"{result}_not_verified")
    save_hierarchy(device, f"{result}_not_verified")
    return False


def select_station(device, serial: str) -> bool:
    if not device(textContains="Elige tu estación").exists and \
       not device(textContains="Elige tu estacion").exists:
        return False
    log.info("  Station selection screen detected")
    screenshot(device, serial, "station_selection")
    for label in ("Disponible", "Available"):
        el = device(textContains=label)
        if el.exists:
            try:
                tap_by_bounds(serial, el)
                log.info(f"  Selected station: {label}")
                time.sleep(2)
                break
            except Exception as exc:
                log.warning(f"  Station tap failed: {exc}")
    for label in ("RESERVAR", "Reservar", "RESERVE"):
        el = device(textContains=label)
        if el.exists:
            try:
                tap_by_bounds(serial, el)
                log.info("  Tapped RESERVAR on station screen")
                time.sleep(3)
                return True
            except Exception as exc:
                log.warning(f"  RESERVAR tap failed on station screen: {exc}")
    log.warning("  Could not complete station selection")
    return False


def confirm_booking(device) -> bool:
    for text in ("AHORA NO", "Ahora no", "NOT NOW"):
        el = device(textContains=text)
        if el.exists:
            try:
                el.click()
                log.info(f"  Dismissed calendar dialog: {text}")
                time.sleep(2)
                return True
            except Exception:
                pass
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


def book_class_with_refresh(device, serial: str, clase: dict) -> bool:
    nombre   = clase["nombre"]
    hora     = clase["hora"]
    dia_clase = clase.get("dia_clase", datetime.now().weekday())
    log.info(f"--- BOOK: {nombre} {hora} ---")
    screenshot(device, serial, "colectivas_before_book")
    save_hierarchy(device, "colectivas_hierarchy")

    # Select the correct day tab before starting the booking loop
    select_day(device, serial, dia_clase)
    time.sleep(2)
    screenshot(device, serial, "after_day_select")
    save_hierarchy(device, "after_day_select_hierarchy")

    deadline = time.time() + 180
    attempt  = 0
    while time.time() < deadline:
        attempt += 1
        dismiss_anr(device, serial)
        log.info(f"  Booking attempt {attempt}...")

        result = find_and_tap_booking_button(device, serial, nombre, hora)

        if result == 'already':
            log.info(f"Already booked: {nombre} {hora}")
            screenshot(device, serial, "already_booked")
            return True

        if result in ('booked', 'waitlist', 'followed'):
            time.sleep(3)
            screenshot(device, serial, f"after_{result}_tap")
            if result != 'followed':
                select_station(device, serial)
                time.sleep(2)
                confirm_booking(device)
                time.sleep(2)
            if not verify_action_result(device, serial, result):
                return False
            screenshot(device, serial, result)
            result_label = {
                'booked': 'RESERVED',
                'waitlist': 'WAITLIST',
                'followed': 'SEGUIR',
            }[result]
            log.info(f"{result_label}: {nombre} {hora}")
            return True

        if result == 'full':
            log.warning(f"Class full, no waitlist: {nombre} {hora}")
            screenshot(device, serial, "class_full")
            return False

        log.info("  RESERVAR/SEGUIR not found yet — refreshing")
        time.sleep(5)
        try:
            device.swipe(540, 600, 540, 1200, duration=0.4)
            time.sleep(2)
        except Exception:
            pass

    log.warning(f"Booking timeout: {nombre} {hora}")
    screenshot(device, serial, "book_timeout")
    save_hierarchy(device, "book_timeout")
    return False


# ============================================================
# ENTRY POINT
# ============================================================

def get_today_class():
    force = os.environ.get("FORCE_CLASS")
    if force:
        parts  = force.split(",")
        nombre = parts[0].strip()
        hora   = parts[1].strip() if len(parts) > 1 else "18:00"
        dia    = int(parts[2].strip()) if len(parts) > 2 else datetime.now().weekday()
        log.info(f"FORCE_CLASS: {nombre} {hora} weekday {dia}")
        return {"nombre": nombre, "hora": hora, "dia_clase": dia, "dia_reserva": -1}

    today = datetime.now().weekday()
    for c in CLASES:
        if c["dia_reserva"] == today:
            return c
    return None


def main():
    log.info("=" * 50)
    log.info(f"GYM BOT (Geelark) — {datetime.now():%Y-%m-%d %H:%M}")

    force = os.environ.get("FORCE_CLASS")
    now   = datetime.now()

    if not os.environ.get("CI") and not force and now.hour != 22:
        log.info("Not reservation time (22:00). Exiting.")
        return

    clase = get_today_class()
    if not clase:
        log.info("No class scheduled today. Exiting.")
        return

    log.info(f"Target: {clase['nombre']} {clase['hora']} (weekday {clase['dia_clase']})")

    if not GEELARK_APP_ID or not GEELARK_API_KEY or not GEELARK_PHONE_ID:
        raise RuntimeError("Missing Geelark credentials: set GEELARK_APP_ID, GEELARK_API_KEY, GEELARK_PHONE_ID")

    gl       = GeelarkClient(GEELARK_APP_ID, GEELARK_API_KEY)
    phone_id = GEELARK_PHONE_ID
    serial   = None
    device   = None

    try:
        # 1. Resolver el ID real del teléfono (el secret puede ser el serialNo externo)
        phone_id = GEELARK_PHONE_ID
        if gl.phone_status(phone_id) == -1:
            log.info(f"Phone ID {phone_id} not found — using first phone in account")
            phone_id = gl.first_phone_id()

        # 2. Arrancar el cloud phone
        gl.ensure_phone_running(phone_id, attempts=2, timeout=240)

        # 3. Habilitar ADB y obtener conexión
        gl.enable_adb(phone_id)
        adb_info = gl.get_adb_info(phone_id)
        log.info(f"ADB info: {adb_info}")

        ip       = adb_info.get("ip") or adb_info.get("host")
        port     = int(adb_info.get("port", 0))
        password = adb_info.get("pwd") or adb_info.get("password") or adb_info.get("code", "")

        serial = connect_adb(ip, port, password)
        wait_adb_ready(serial, timeout=120)

        # 3. Conectar uiautomator2 (u2.connect arranca el servidor si hace falta)
        log.info("Connecting uiautomator2 on cloud phone...")
        device = connect_u2(serial, max_wait=60)
        device.screen_on()
        time.sleep(2)

        # 4. Abrir Technogym desde la pantalla principal de Android.
        # El cloud phone tiene la app instalada y logueada — solo hay que
        # abrirla. NUNCA app_stop antes: reinicia la app desde cero y
        # muestra pantalla de seleccion de club en vez del home de Alicia.
        log.info("Starting Technogym from home screen...")
        device.app_start(APP_PACKAGE)
        log.info("App started — waiting 15s...")
        time.sleep(15)

        # 5. Login
        if not login(device, serial):
            log.error("Login failed — aborting")
            return

        # 6. Navegar a COLECTIVAS
        if not navigate_to_colectivas(device, serial):
            log.error("Navigation failed — aborting")
            return

        # 7. En CI sin forzado: esperar hasta las 22:00 Madrid (20:00 UTC)
        if os.environ.get("CI") and not force:
            utc_now   = datetime.utcnow()
            target_t  = utc_now.replace(hour=20, minute=0, second=0, microsecond=0)
            wait_secs = (target_t - utc_now).total_seconds()
            if wait_secs > 0:
                log.info(f"Waiting {wait_secs:.0f}s until 22:00 Madrid...")
                time.sleep(wait_secs)
            log.info("22:00 — starting booking")

        # 8. Reservar
        book_class_with_refresh(device, serial, clase)

    except Exception as exc:
        log.error(f"Unhandled error: {exc}", exc_info=True)
        if device and serial:
            try:
                screenshot(device, serial, "crash")
                save_hierarchy(device, "crash_hierarchy")
            except Exception:
                pass

    finally:
        # Apagar el cloud phone siempre (para no consumir créditos)
        try:
            gl.stop_phone(phone_id)
            log.info("Geelark phone stopped")
        except Exception as exc:
            log.warning(f"Could not stop Geelark phone: {exc}")

    log.info("=" * 50)


if __name__ == "__main__":
    main()
