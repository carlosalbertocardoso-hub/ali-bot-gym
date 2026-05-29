#!/bin/bash
# Capture Technogym HTTPS using mitmproxy + frida-gadget (no root needed).
set +e
exec > >(tee capture.log) 2>&1

SERIAL=$(adb devices | grep emulator | awk '{print $1}' | head -1)
echo "==== Emulator: $SERIAL ===="

# --- 1. Instalar mitmproxy CA como USER cert vía Settings ---
# Android 14 user-cert no es válido para apps por defecto, pero el frida-gadget
# que inyectamos hace SSL unpinning a nivel del runtime, así que basta con que
# mitmproxy reciba la conexión TLS — la app la valida contra el truststore parcheado.
adb -s "$SERIAL" push ~/.mitmproxy/mitm-ca.crt /sdcard/Download/mitm-ca.crt
echo "User cert pushed to /sdcard/Download/mitm-ca.crt"

# --- 2. Arrancar mitmdump ---
echo "==== Starting mitmdump ===="
mitmdump \
  --listen-port 8080 \
  --set confdir=~/.mitmproxy \
  --ssl-insecure \
  -w mitm_flows.dump \
  > mitm_stdout.log 2>&1 &
MITMPID=$!
sleep 5
echo "mitmdump PID: $MITMPID"

# --- 3. AdbKeyboard para meter credenciales ---
ADBKB_APK="ADBKeyboard.apk"
[ ! -f "$ADBKB_APK" ] && curl -fL -o "$ADBKB_APK" "https://github.com/senzhk/ADBKeyBoard/raw/master/ADBKeyboard.apk"
adb -s "$SERIAL" install -r "$ADBKB_APK"
adb -s "$SERIAL" shell settings put secure enabled_input_methods com.android.adbkeyboard/.AdbIME
adb -s "$SERIAL" shell settings put secure default_input_method com.android.adbkeyboard/.AdbIME

# --- 4. Instalar el APK parcheado con frida-gadget ---
# Solo el base APK; los splits los cogemos del original. La firma del base
# debe coincidir con la de los splits, por eso objection los re-firma todos
# con el mismo keystore por nosotros.
echo "==== Installing patched Technogym ===="
adb -s "$SERIAL" install -r patched-base.apk
if [ $? -ne 0 ]; then
  echo "Patched base install failed; trying install-multiple with original splits..."
  adb -s "$SERIAL" install-multiple -r \
    patched-base.apk \
    technogym-3.43.2-xapk/config.en.apk \
    technogym-3.43.2-xapk/config.xxhdpi.apk \
    technogym-3.43.2-xapk/config.arm64_v8a.apk || echo "install-multiple also failed"
fi

# --- 5. uiautomator2 init ---
python -m uiautomator2 init -s "$SERIAL"

# --- 6. Lanzar Technogym ---
adb -s "$SERIAL" shell monkey -p com.technogym.tgapp -c android.intent.category.LAUNCHER 1
echo "==== Technogym launched, waiting 20s for gadget to bind ===="
sleep 20

# --- 7. Conectar Frida y ejecutar SSL unpinning genérico ---
# El gadget escucha en localhost:27042 dentro del emulador; forwardeamos.
adb -s "$SERIAL" forward tcp:27042 tcp:27042
echo "==== Frida processes ===="
frida-ps -U | head -30 || echo "frida-ps failed"

cat > unpin.js <<'EOF'
// SSL unpinning genérico — desactiva pinning en Java + OkHttp + WebView + Conscrypt.
Java.perform(function () {
  console.log("[*] SSL unpinning starting");
  // TrustManager universal
  try {
    var X509TrustManager = Java.use('javax.net.ssl.X509TrustManager');
    var SSLContext = Java.use('javax.net.ssl.SSLContext');
    var TrustManager = Java.registerClass({
      name: 'com.bypass.TrustAll',
      implements: [X509TrustManager],
      methods: {
        checkClientTrusted: function () {},
        checkServerTrusted: function () {},
        getAcceptedIssuers: function () { return []; }
      }
    });
    var TrustManagers = [TrustManager.$new()];
    var SSLContext_init = SSLContext.init.overload(
      '[Ljavax.net.ssl.KeyManager;', '[Ljavax.net.ssl.TrustManager;', 'java.security.SecureRandom'
    );
    SSLContext_init.implementation = function (km, tm, sr) {
      SSLContext_init.call(this, km, TrustManagers, sr);
    };
    console.log("[+] TrustManager replaced");
  } catch (e) { console.log("[-] TrustManager hook failed: " + e); }

  // OkHttp 3 CertificatePinner
  try {
    var CertificatePinner = Java.use('okhttp3.CertificatePinner');
    CertificatePinner.check.overload('java.lang.String', 'java.util.List').implementation = function () {};
    console.log("[+] OkHttp3 CertificatePinner.check disabled");
  } catch (e) { console.log("[-] OkHttp3 hook failed: " + e); }
});
EOF

# Ejecutar el script Frida sobre Technogym (que ya está corriendo con gadget)
echo "==== Running Frida unpin script ===="
timeout 10 frida -U -n Gadget -l unpin.js --runtime=v8 &
sleep 5

# --- 8. Ejecutar el flujo de login ---
echo "==== Running capture-only login flow ===="
DEVICE_SERIAL="$SERIAL" CAPTURE_MODE=1 python capture_login.py || echo "capture_login exited with $?"

# --- 9. Esperar a que mitmproxy flush ---
sleep 30

# --- 10. Dump legible ---
echo "==== Dumping flows to text ===="
mitmdump -nr mitm_flows.dump --set flow_detail=4 -q > mitm_flows.txt 2>&1 || echo "text dump failed"

kill -INT $MITMPID 2>/dev/null
sleep 2
kill -9 $MITMPID 2>/dev/null

ls -la mitm_flows.* capture.log
echo "==== DONE ===="
