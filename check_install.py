# check_install.py
#
# Verifies the Mousetrack environment. Run by setup_mousetrack.bat, or by
# hand:  conda activate mousetrack  &&  python check_install.py
#
# Exit code 0 = everything required is installed, 1 = something is missing.

import importlib
import os
import sys

# Importing the project modules must not need a display
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

failed = []


def check(label, ok, detail=""):

    print(f"  [{'OK' if ok else 'FAIL'}] {label}" + (f"  {detail}" if detail else ""))

    if not ok:
        failed.append(label)


print(f"Python {sys.version.split()[0]} ({sys.executable})")

check(
    "Python 3.12",
    sys.version_info[:2] == (3, 12),
    "PySpin wheel is built for cp312"
)

# ---------------------------------------------------
# Third-party packages
# ---------------------------------------------------

print("\nPackages")

for module, label in (
    ("numpy", "numpy"),
    ("pandas", "pandas"),
    ("cv2", "opencv-python"),
    ("PyQt5.QtCore", "PyQt5"),
    ("serial", "pyserial"),
):

    try:

        mod = importlib.import_module(module)

        version = getattr(mod, "__version__", None) or getattr(
            mod, "PYQT_VERSION_STR", ""
        )

        check(label, True, str(version))

    except Exception as e:

        check(label, False, f"{type(e).__name__}: {e}")

# ---------------------------------------------------
# FLIR PySpin
# ---------------------------------------------------

print("\nFLIR PySpin")

try:

    import PySpin

    system = PySpin.System.GetInstance()

    version = system.GetLibraryVersion()

    cameras = system.GetCameras()

    n_cameras = cameras.GetSize()

    # Spinnaker needs every reference dropped before ReleaseInstance()
    cameras.Clear()

    del cameras

    system.ReleaseInstance()

    check(
        "PySpin",
        True,
        f"Spinnaker {version.major}.{version.minor}.{version.type}.{version.build}"
    )

    print(f"  [info] cameras detected: {n_cameras}"
          + ("" if n_cameras else "  (plug in the camera to use the app)"))

except Exception as e:

    check("PySpin", False, f"{type(e).__name__}: {e}")

# ---------------------------------------------------
# Bpod (informational: not required for the install)
# ---------------------------------------------------

print("\nBpod")

try:

    import serial.tools.list_ports

    ports = [
        p.device
        for p in serial.tools.list_ports.comports()
        if p.vid == 0x16C0
    ]

    print(
        "  [info] Teensy (Bpod) serial ports: "
        + (", ".join(ports) if ports else "none found (is the Bpod plugged in?)")
    )

except Exception as e:

    print(f"  [info] could not list serial ports: {e}")

# ---------------------------------------------------
# Project modules
# ---------------------------------------------------

print("\nProject modules")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

for module in (
    "config",
    "config_writer",
    "bpod_valve",
    "camera",
    "recorder",
    "roi_video_widget",
    "settings_panel",
    "tracking",
    "main",
):

    try:

        importlib.import_module(module)

        check(module, True)

    except Exception as e:

        check(module, False, f"{type(e).__name__}: {e}")

print()

if failed:

    print("INSTALL INCOMPLETE - failed: " + ", ".join(failed))

    sys.exit(1)

print("INSTALL OK")
