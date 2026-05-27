#!/bin/bash
set -e
SERIAL=$(adb devices | grep emulator | awk '{print $1}' | head -1)
echo "Emulator serial: $SERIAL"
adb -s "$SERIAL" install-multiple -r \
  technogym-3.43.2-xapk/com.technogym.tgapp.apk \
  technogym-3.43.2-xapk/config.en.apk \
  technogym-3.43.2-xapk/config.xxhdpi.apk \
  technogym-3.43.2-xapk/config.arm64_v8a.apk
python -m uiautomator2 init -s "$SERIAL"
DEVICE_SERIAL="$SERIAL" python gym_bot.py
