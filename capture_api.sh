#!/bin/bash
# Captura el tráfico HTTPS de Technogym usando mitmproxy.
# Espera env vars: MITM_CERT_HASH, MITM_CERT_PATH
set +e  # NO abortar a la primera; queremos llegar al upload aunque algo falle

exec > >(tee capture.log) 2>&1

SERIAL=$(adb devices | grep emulator | awk '{print $1}' | head -1)
echo "==== Emulator: $SERIAL ===="
echo "==== CA hash: $MITM_CERT_HASH ===="

# --- 1. Instalar CA de mitmproxy como system cert ---
# El emulador arrancó con -writable-system. Necesitamos root + remount + push.
adb -s "$SERIAL" root
sleep 3
adb -s "$SERIAL" wait-for-device
adb -s "$SERIAL" remount

CERT_NAME="${MITM_CERT_HASH}.0"
adb -s "$SERIAL" push "$MITM_CERT_PATH" "/system/etc/security/cacerts/$CERT_NAME"
adb -s "$SERIAL" shell chmod 644 "/system/etc/security/cacerts/$CERT_NAME"
adb -s "$SERIAL" shell ls -la /system/etc/security/cacerts/ | head -20

# Reboot para que el sistema cargue el nuevo CA
echo "==== Rebooting emulator with system CA installed ===="
adb -s "$SERIAL" reboot
sleep 30
adb -s "$SERIAL" wait-for-device
# Esperar a que boot_completed
for i in {1..60}; do
  if [ "$(adb -s "$SERIAL" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" = "1" ]; then
    echo "==== Reboot done ===="
    break
  fi
  sleep 2
done

# --- 2. Lanzar mitmdump en background, guardando flows ---
echo "==== Starting mitmdump ===="
mitmdump \
  --listen-port 8080 \
  --set confdir=~/.mitmproxy \
  -w mitm_flows.dump \
  --flow-detail 0 \
  > mitm_stdout.log 2>&1 &
MITMPID=$!
sleep 5
echo "mitmdump PID: $MITMPID"

# --- 3. Instalar AdbKeyboard (para meter el email/password) ---
ADBKB_APK="ADBKeyboard.apk"
if [ ! -f "$ADBKB_APK" ]; then
  curl -fL -o "$ADBKB_APK" \
    "https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk"
fi
adb -s "$SERIAL" install -r "$ADBKB_APK"
adb -s "$SERIAL" shell settings put secure enabled_input_methods com.android.adbkeyboard/.AdbIME
adb -s "$SERIAL" shell settings put secure default_input_method com.android.adbkeyboard/.AdbIME

# --- 4. Instalar Technogym ---
adb -s "$SERIAL" install-multiple -r \
  technogym-3.43.2-xapk/com.technogym.tgapp.apk \
  technogym-3.43.2-xapk/config.en.apk \
  technogym-3.43.2-xapk/config.xxhdpi.apk \
  technogym-3.43.2-xapk/config.arm64_v8a.apk

# --- 5. Inicializar uiautomator2 y ejecutar SOLO la fase de login ---
python -m uiautomator2 init -s "$SERIAL"

echo "==== Running capture-only login flow ===="
# CAPTURE_MODE=1 le dice al bot que haga solo login y salga (sin navegar a COLECTIVAS,
# que es lo que mata al emulador). Si CAPTURE_MODE no está implementado en gym_bot.py
# todavía, ejecutamos el script standalone debajo.
DEVICE_SERIAL="$SERIAL" CAPTURE_MODE=1 python capture_login.py || echo "capture_login.py exited with $?"

# --- 6. Dar tiempo a mitmproxy para flushear ---
echo "==== Waiting 30s for mitmproxy to flush ===="
sleep 30

# --- 7. Volcar a texto legible para que sea fácil de leer en el artefacto ---
echo "==== Dumping flows to text ===="
mitmdump -nr mitm_flows.dump \
  --set flow_detail=4 \
  -q > mitm_flows.txt 2>&1 || echo "text dump failed (dump file may still be valid)"

# Matar mitmdump limpiamente
kill -INT $MITMPID 2>/dev/null
sleep 2
kill -9 $MITMPID 2>/dev/null

ls -la mitm_flows.* capture.log
echo "==== DONE ===="
