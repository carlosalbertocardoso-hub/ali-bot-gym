"""
Test de login — ejecutar con el emulador GymBotPlayAVD ya arrancado.

    python test_login.py

Resultado esperado: log con "Club home reached" y captura after_login_*.png
"""
import sys, re, time
sys.path.insert(0, r"C:\Users\ccard\Proyectos\gym-bot-alicia")
sys.stdout.reconfigure(encoding="utf-8")

import uiautomator2 as u2
from gym_bot import login, navigate_to_colectivas, screenshot, APP_PACKAGE, get_texts

d = u2.connect("emulator-5554")
d.screen_on()
time.sleep(1)

print("Stopping app...")
d.app_stop(APP_PACKAGE)
time.sleep(2)

print("Starting app...")
d.app_start(APP_PACKAGE)
time.sleep(10)

ok = login(d)
print(f"\nLogin result: {'OK' if ok else 'FAILED'}")

texts = get_texts(d)
print(f"\nScreen texts after login ({len(texts)}):")
for t in texts[:20]:
    print(f"  {t}")

if ok:
    print("\nNavigating to COLECTIVAS...")
    nav_ok = navigate_to_colectivas(d)
    print(f"Navigation result: {'OK' if nav_ok else 'FAILED'}")

screenshot(d, "test_login_final")
print("\nDone — check screenshots/")
