# config.py
#
# Central settings for the Mousetrack / ForagingGUI project.
# Every value here is read by the code (main.py, tracking.py, camera.py,
# bpod_valve.py, recorder.py, roi_video_widget.py).
#
# The reward valve is driven directly from Python through the Bpod's USB
# serial port (bpod_valve.py). MATLAB and the Arduino are not used.

import os

# =====================================================
# PATHS
# =====================================================

PROJECT_DIR = os.path.dirname(os.path.abspath(__file__))

# Pre-filled in the "Save Directory" box if it exists
DEFAULT_SAVE_DIR = os.path.join(PROJECT_DIR, "Data")

# =====================================================
# CAMERA (FLIR / Spinnaker)
# =====================================================

EXPOSURE_US = 2000
GAIN = 5.4

CAMERA_FPS = 90

# How long GetNextImage waits before giving up (so threads can be stopped)
CAMERA_GRAB_TIMEOUT_MS = 1000

# =====================================================
# DISPLAY
# =====================================================

# Video panels scale with the window (aspect ratio is kept).
# MIN is the smallest a panel can shrink to; SIZE is only used before
# the first layout pass.
DISPLAY_MIN_SIZE = (320, 320)
DISPLAY_SIZE = (640, 640)

# Initial window size as a fraction of the available screen
WINDOW_SCREEN_FRACTION = 0.9

# GUI refresh period for preview and tracking (saving is every frame)
DISPLAY_INTERVAL_S = 0.1

# ROI colors, RGB
ROI1_COLOR_RGB = (0, 255, 0)
ROI2_COLOR_RGB = (255, 0, 0)

# =====================================================
# TRACKING
# =====================================================

NUM_BACKGROUND_FRAMES = 50

THRESHOLD = 15
MIN_CONTOUR_AREA = 1000

# Blobs larger than this are ignored (a shadow or arm across the field
# would otherwise be picked as "the object"). 0 = no limit.
MAX_CONTOUR_AREA = 100000

MORPH_KERNEL_SIZE = 7

# Detection runs on an image scaled by this factor (0.1 - 1.0) for speed.
# MIN_CONTOUR_AREA and MORPH_KERNEL_SIZE are still given in full-resolution
# pixels; recorded video and reported coordinates stay full resolution.
DETECTION_SCALE = 0.5

# "on": rescale each frame so its overall brightness matches the background
# before subtracting. Stops a lamp / IR panel brightness drift from making
# the whole image look like an object. "off" disables it.
BRIGHTNESS_COMP = "on"

# "both"  : |frame - background|
# "dark"  : object darker than background (silhouette on IR-lit plexiglass)
# "bright": object brighter than background
TRACK_POLARITY = "dark"

# If the object is lost for longer than this, dwell/ROI state is reset
TRACK_LOST_GRACE_S = 0.2

# =====================================================
# REWARD LOGIC
# =====================================================

DWELL_TIME_S = 0.5
REWARD_LOCKOUT_S = 2.0

STATE_WAIT_GREEN = "WAIT_FOR_GREEN"
STATE_WAIT_RED = "WAIT_FOR_RED"

# =====================================================
# BPOD VALVE (direct USB serial control, no MATLAB / Arduino)
# =====================================================

# "AUTO" finds the Bpod state machine, or give a port such as "COM5"
BPOD_PORT = "AUTO"

# Valve number on the Bpod (1-8)
BPOD_VALVE = 1

# How long the valve opens per reward. Timed by the Bpod itself.
VALVE_OPEN_MS = 500

# Calibrate Valve: number of openings (each VALVE_OPEN_MS long) and the
# closed time between them
CALIBRATE_PULSES = 50
CALIBRATE_GAP_MS = 200

# Safety limit for the manual Flush valve: the Bpod closes it after this
# even if the program dies
FLUSH_MAX_S = 600

# =====================================================
# RECORDING / SESSION OUTPUT
# =====================================================

VIDEO_FILENAME = "camera.avi"

# MJPG encodes ~130 fps at 1440x1440 on this PC (XVID only ~105, which
# dropped 8% of frames at 90 fps). Files are ~2x larger (about 100 MB/min).
VIDEO_FOURCC = "MJPG"

# Max frames buffered for the writer before frames are dropped (and counted)
RECORDER_MAX_QUEUE = 900

# Copy of the background used for the session (for later re-analysis)
BACKGROUND_FILENAME = "background.png"

EVENTS_FILENAME = "session_events.csv"
TRACKING_FILENAME = "tracking.csv"
ROI_HISTORY_FILENAME = "roi_history.csv"
ROI_FILENAME = "rois.csv"

SESSION_TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"
LOG_TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M:%S.%f"
