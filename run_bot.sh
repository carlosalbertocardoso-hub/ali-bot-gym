#!/bin/bash
set -e
SERIAL=$(adb devices | grep emulator | awk '{print $1}' | head -1)
echo "Emulator serial: $SERIAL"

# Instalar AdbKeyboard — IME que acepta `adb shell input text` sin composición
# asíncrona de LatinIME (que cuelga en Android 14)
ADBKB_APK="AdbKeyboard.apk"
if [ ! -f "$ADBKB_APK" ]; then
  echo "Downloading AdbKeyboard..."
  curl -fsSL -o "$ADBKB_APK" \
    "https://github.com/senzhk/ADBKeyBoard/raw/master/AdbKeyboard.apk"
fi
adb -s "$SERIAL" install -r "$ADBKB_APK"
adb -s "$SERIAL" shell ime enable com.android.adbkeyboard/.AdbIME
adb -s "$SERIAL" shell ime set com.android.adbkeyboard/.AdbIME
echo "AdbKeyboard installed and set as default IME"

adb -s "$SERIAL" install-multiple -r \
  technogym-3.43.2-xapk/com.technogym.tgapp.apk \
  technogym-3.43.2-xapk/config.en.apk \
  technogym-3.43.2-xapk/config.xxhdpi.apk \
  technogym-3.43.2-xapk/config.arm64_v8a.apk
python -m uiautomator2 init -s "$SERIAL"
DEVICE_SERIAL="$SERIAL" python gym_bot.py
