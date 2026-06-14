#!/usr/bin/env python3
# ccstats — self-hosted Claude Code usage stats (badge firmware + server)
# Copyright (C) 2026 Zapador <zapador@zapador.net>
#
# This program is free software; you can redistribute it and/or modify it under
# the terms of version 2 of the GNU General Public License as published by the
# Free Software Foundation. See the LICENSE file for the full text.
#
# This program is distributed WITHOUT ANY WARRANTY; without even the implied
# warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.

"""Install the firmware as the ccstats launcher app (/system/apps/ccstats).

/system (FAT) is mounted read-only at runtime, and every mpremote invocation
soft-resets the board — which re-runs _boot_fat.py and remounts it read-only
again. So the install has to happen in ONE serial session: this script
generates a single installer that remounts /system read-write and writes all
app files, runs it via mpremote, then resets the badge back into the launcher
(which restores the read-only mount).

secrets.py is deliberately NOT app content — it lives at the device root
(/secrets.py, reachable via the app's sys.path entry for "/").

Usage: tools/install-app.py [path-to-mpremote]
"""

import base64
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FIRMWARE_DIR = os.path.join(REPO_ROOT, "firmware")
# The app file list is DERIVED from firmware/, never hand-maintained — a
# forgotten entry here once shipped an app missing a module (ImportError at
# launch). Everything except secrets and the host-side dev entry points goes.
EXCLUDED_FILES = {"secrets.py", "secrets.example.py", "dev_run.py", "dev_smoke.py"}


def collect_app_files():
    # every file in firmware/ plus every file one level down (fonts/,
    # splash_frames/, future asset directories) — never hand-maintained
    files = []
    for name in sorted(os.listdir(FIRMWARE_DIR)):
        if name in EXCLUDED_FILES or name.startswith(".") or name == "__pycache__":
            continue
        path = os.path.join(FIRMWARE_DIR, name)
        if os.path.isfile(path):
            files.append(name)
        elif os.path.isdir(path):
            for inner_name in sorted(os.listdir(path)):
                if not inner_name.startswith("."):
                    files.append(name + "/" + inner_name)
    return files

INSTALLER_HEADER = '''\
import binascii
import os
import rp2
import vfs

os.umount("/system")
user_flash_size = rp2.Flash().ioctl(4, 0) * rp2.Flash().ioctl(5, 0)
fat_block_device = rp2.Flash(start=0, len=user_flash_size - 1024 * 1024)
vfs.mount(vfs.VfsFat(fat_block_device), "/system")
'''

INSTALLER_WIFI_TEMPLATE = '''\
WIFI_TEMPLATE = """# ccstats wifi networks — edit this file in disk mode.
#
# Two lines per network: the SSID, then the password on the next line.
# The badge tries them top to bottom (visible networks first). Lines
# starting with # and blank lines are ignored. Example:
#
# my-home-wifi
# my-home-password
# my-phone-hotspot
# my-hotspot-password
#
# When this file lists no networks, the badge falls back to secrets.py.
"""
try:
    os.stat("/system/wifi.txt")
except OSError:
    with open("/system/wifi.txt", "w") as wifi_file:
        wifi_file.write(WIFI_TEMPLATE)
    print("seeded /system/wifi.txt template")
'''

INSTALLER_STALE_SWEEP = '''\
expected = set(APP_FILES)
expected_directories = set(name.split("/")[0] for name in APP_FILES if "/" in name)
for name in os.listdir("/system/apps/ccstats"):
    path = "/system/apps/ccstats/" + name
    if name in expected_directories:
        for inner_name in os.listdir(path):
            if (name + "/" + inner_name) not in expected:
                os.remove(path + "/" + inner_name)
                print("removed stale", name + "/" + inner_name)
        continue
    if name not in expected:
        try:
            os.remove(path)  # a stale file...
            print("removed stale", name)
        except OSError:
            try:
                for inner_name in os.listdir(path):  # ...or a whole stale directory
                    os.remove(path + "/" + inner_name)
                os.rmdir(path)
                print("removed stale directory", name)
            except OSError:
                pass

print("installed:", sorted(os.listdir("/system/apps/ccstats")))
'''

# /state is a separate filesystem (untouched by the /system remount above), so
# this runs after the app is written. The launcher menu patch (enable-autoboot)
# consumes this marker on the next boot to launch ccstats once regardless of
# reset cause — so a deploy lands in the app, not the menu — then deletes it.
INSTALLER_LAUNCH_MARKER = '''\
try:
    os.mkdir("/state")
except OSError:
    pass
with open("/state/ccstats-launch-once", "w") as marker_file:
    marker_file.write("1")
print("launch-once marker written")
'''

INSTALLER_FOOTER = '''\
}

for file_name, encoded in APP_FILES.items():
    content = binascii.a2b_base64(encoded)
    with open("/system/apps/ccstats/" + file_name, "wb") as file:
        file.write(content)
    print("wrote", file_name, len(content), "bytes")
'''


def main():
    mpremote_binary = sys.argv[1] if len(sys.argv) > 1 else "mpremote"

    app_files = collect_app_files()
    print("installing %d files:" % len(app_files), " ".join(app_files))
    app_directories = ["/system/apps/ccstats"] + sorted({
        "/system/apps/ccstats/" + file_name.split("/")[0]
        for file_name in app_files if "/" in file_name
    })
    chunks = [INSTALLER_HEADER]
    chunks.append("for directory in %r:\n" % (tuple(app_directories),))
    chunks.append("    try:\n        os.mkdir(directory)\n    except OSError:\n        pass\n\n")
    chunks.append("APP_FILES = {\n")
    for file_name in app_files:
        with open(os.path.join(FIRMWARE_DIR, file_name), "rb") as file:
            encoded = base64.b64encode(file.read()).decode()
        chunks.append("    %r: %r,\n" % (file_name, encoded))
    chunks.append(INSTALLER_FOOTER)
    chunks.append(INSTALLER_WIFI_TEMPLATE)
    chunks.append(INSTALLER_STALE_SWEEP)
    chunks.append(INSTALLER_LAUNCH_MARKER)

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False) as installer:
        installer.write("".join(chunks))
        installer_path = installer.name
    try:
        subprocess.run([mpremote_binary, "run", installer_path], check=True)
        subprocess.run([mpremote_binary, "reset"], check=True)
        print("badge reset — booting straight into ccstats (one-shot launch marker)")
    finally:
        os.unlink(installer_path)


if __name__ == "__main__":
    main()
