import sys
import cv2
import numpy as np
import pandas as pd
import datetime
import os
import csv
import time

from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QWidget,
    QSizePolicy,
    QPushButton,
    QLabel,
    QVBoxLayout,
    QHBoxLayout,
    QMessageBox,
    QFileDialog,
    QLineEdit
)

from PyQt5.QtGui import (
    QImage,
    QPixmap
)

from PyQt5.QtCore import (
    Qt,
    QThread,
    pyqtSignal
)

import config

from camera import SpinnakerCamera
from tracking import TrackingThread
from bpod_valve import BpodValve
from roi_video_widget import VideoWidget
from recorder import RecorderThread
from settings_panel import SettingsPanel
from config_writer import update_config_file

# =====================================================
# PREVIEW THREAD
# =====================================================

class PreviewThread(QThread):

    frame_ready = pyqtSignal(np.ndarray)

    error = pyqtSignal(str)

    def __init__(
        self,
        camera,
        interval=config.DISPLAY_INTERVAL_S
    ):

        super().__init__()

        self.camera = camera

        self.interval = interval

        self.running = False

    def run(self):

        self.running = True

        last_emit = 0

        while self.running:

            try:

                frame = self.camera.get_frame()

            except Exception as e:

                self.error.emit(str(e))

                break

            if frame is None:
                continue

            #
            # Throttle: the GUI thread cannot keep up with full rate
            #
            now = time.time()

            if now - last_emit < self.interval:
                continue

            last_emit = now

            self.frame_ready.emit(frame)

    def stop(self):

        self.running = False

# =====================================================
# MAIN WINDOW
# =====================================================

class MainWindow(QMainWindow):

    # Emitted from the valve worker thread; delivered in the GUI thread
    valve_event = pyqtSignal(str, str)

    def __init__(self):

        super().__init__()

        # =====================================
        # Hardware
        # =====================================

        self.camera = None
        self.tracker = None
        self.valve = None

        # =====================================
        # Preview
        # =====================================

        self.preview_thread = None
        self.preview_running = False

        # =====================================
        # Tracking Data
        # =====================================

        self.background = None

        self.last_frame = None
        self.last_threshold = None

        self.roi1 = None
        self.roi2 = None

        self.rewards = 0

        # =====================================
        # Recording
        # =====================================

        self.video_writer = None
        self.recorder = None

        # =====================================
        # Session Files (None when no experiment is running)
        # =====================================

        self.session_folder = None

        self.events_file = None
        self.roi_file = None
        self.tracking_file = None

        self.tracking_fh = None
        self.tracking_writer = None
        self.tracking_rows = 0

        # =====================================
        # User Settings (defaults from config.py)
        # =====================================

        self.BPOD_PORT = config.BPOD_PORT
        self.BPOD_VALVE = config.BPOD_VALVE

        self.CAMERA_FPS = config.CAMERA_FPS
        self.EXPOSURE_US = config.EXPOSURE_US
        self.GAIN = config.GAIN

        self.THRESHOLD = config.THRESHOLD
        self.MIN_CONTOUR_AREA = config.MIN_CONTOUR_AREA
        self.MAX_CONTOUR_AREA = config.MAX_CONTOUR_AREA

        self.DETECTION_SCALE = config.DETECTION_SCALE
        self.BRIGHTNESS_COMP = config.BRIGHTNESS_COMP
        self.MORPH_KERNEL_SIZE = config.MORPH_KERNEL_SIZE
        self.TRACK_POLARITY = config.TRACK_POLARITY
        self.TRACK_LOST_GRACE_S = config.TRACK_LOST_GRACE_S

        self.DWELL_TIME = config.DWELL_TIME_S
        self.REWARD_LOCKOUT = config.REWARD_LOCKOUT_S

        self.VALVE_OPEN_MS = config.VALVE_OPEN_MS
        self.NUM_BACKGROUND_FRAMES = config.NUM_BACKGROUND_FRAMES

        # =====================================
        # Build GUI
        # =====================================

        self.setup_ui()

    # =====================================================
    # UI
    # =====================================================

    def setup_ui(self):

        self.setWindowTitle(
            "Mousetrack"
        )

        # =====================================
        # Video Widgets
        # =====================================

        self.videoWidget = VideoWidget()

        self.thresholdWidget = VideoWidget()

        for widget in (self.videoWidget, self.thresholdWidget):

            widget.setMinimumSize(
                *config.DISPLAY_MIN_SIZE
            )

            #
            # Ignore the pixmap's size hint, otherwise a large frame
            # forces the label (and window) to grow over the buttons
            #
            widget.setSizePolicy(
                QSizePolicy.Ignored,
                QSizePolicy.Ignored
            )

            widget.setScaledContents(
                False
            )

            widget.setAlignment(
                Qt.AlignCenter
            )

        # =====================================
        # Status Labels
        # =====================================

        self.statusLabel = QLabel(
            "System Not Initialized"
        )

        self.rewardLabel = QLabel(
            "Rewards: 0"
        )

        self.fpsLabel = QLabel(
            "FPS: 0"
        )

        # =====================================
        # Save Path
        # =====================================

        self.pathEdit = QLineEdit()

        self.pathEdit.setPlaceholderText(
            "Select save directory..."
        )

        if os.path.isdir(config.DEFAULT_SAVE_DIR):

            self.pathEdit.setText(
                config.DEFAULT_SAVE_DIR
            )

        # =====================================
        # Buttons
        # =====================================

        self.btnInit = QPushButton("Initialize")
        self.btnPreview = QPushButton("Preview")
        self.btnBackground = QPushButton("Capture Background")
        self.btnROI1 = QPushButton("Draw ROI1")
        self.btnROI2 = QPushButton("Draw ROI2")
        self.btnSaveROI = QPushButton("Save ROI")
        self.btnLoadROI = QPushButton("Load ROI")
        self.btnBrowse = QPushButton("Browse")
        self.btnTestReward = QPushButton("Test Reward")
        self.btnStart = QPushButton("Start Experiment")
        self.btnStop = QPushButton("Stop Experiment")

        # =====================================
        # Layouts
        # =====================================

        videoLayout = QHBoxLayout()
        videoLayout.addWidget(self.videoWidget, 1)
        videoLayout.addWidget(self.thresholdWidget, 1)

        statusLayout = QHBoxLayout()
        statusLayout.addWidget(self.statusLabel)
        statusLayout.addStretch()
        statusLayout.addWidget(self.fpsLabel)
        statusLayout.addSpacing(20)
        statusLayout.addWidget(self.rewardLabel)

        acquisitionLayout = QHBoxLayout()
        acquisitionLayout.addWidget(self.btnInit)
        acquisitionLayout.addWidget(self.btnPreview)
        acquisitionLayout.addWidget(self.btnBackground)
        acquisitionLayout.addStretch()

        roiLayout = QHBoxLayout()
        roiLayout.addWidget(self.btnROI1)
        roiLayout.addWidget(self.btnROI2)
        roiLayout.addWidget(self.btnSaveROI)
        roiLayout.addWidget(self.btnLoadROI)
        roiLayout.addWidget(self.btnTestReward)
        roiLayout.addStretch()

        experimentLayout = QHBoxLayout()
        experimentLayout.addWidget(self.btnStart)
        experimentLayout.addWidget(self.btnStop)
        experimentLayout.addStretch()

        saveLayout = QHBoxLayout()
        saveLayout.addWidget(QLabel("Save Directory:"))
        saveLayout.addWidget(self.pathEdit)
        saveLayout.addWidget(self.btnBrowse)

        mainLayout = QVBoxLayout()
        # Video takes all spare space; the controls keep their height
        mainLayout.addLayout(videoLayout, 1)
        mainLayout.addLayout(statusLayout)
        mainLayout.addLayout(acquisitionLayout)
        mainLayout.addLayout(roiLayout)
        mainLayout.addLayout(experimentLayout)

        self.settingsPanel = SettingsPanel({
            "EXPOSURE_US": self.EXPOSURE_US,
            "GAIN": self.GAIN,
            "CAMERA_FPS": self.CAMERA_FPS,
            "THRESHOLD": self.THRESHOLD,
            "MIN_CONTOUR_AREA": self.MIN_CONTOUR_AREA,
            "MAX_CONTOUR_AREA": self.MAX_CONTOUR_AREA,
            "DETECTION_SCALE": self.DETECTION_SCALE,
            "BRIGHTNESS_COMP": self.BRIGHTNESS_COMP,
            "MORPH_KERNEL_SIZE": self.MORPH_KERNEL_SIZE,
            "TRACK_POLARITY": self.TRACK_POLARITY,
            "TRACK_LOST_GRACE_S": self.TRACK_LOST_GRACE_S,
            "DWELL_TIME_S": self.DWELL_TIME,
            "REWARD_LOCKOUT_S": self.REWARD_LOCKOUT,
            "VALVE_OPEN_MS": self.VALVE_OPEN_MS,
            "NUM_BACKGROUND_FRAMES": self.NUM_BACKGROUND_FRAMES
        })

        self.settingsPanel.changed.connect(self.on_setting_changed)

        self.settingsPanel.save_requested.connect(self.save_defaults)

        mainLayout.addWidget(self.settingsPanel)

        mainLayout.addLayout(saveLayout)

        central = QWidget()

        central.setLayout(
            mainLayout
        )

        self.setCentralWidget(
            central
        )

        #
        # Fit the window to the screen
        #
        screen = QApplication.primaryScreen().availableGeometry()

        self.resize(
            int(screen.width() * config.WINDOW_SCREEN_FRACTION),
            int(screen.height() * config.WINDOW_SCREEN_FRACTION)
        )

        # =====================================
        # Connections
        # =====================================

        self.videoWidget.roi_created.connect(self.roi_created)
        self.thresholdWidget.roi_created.connect(self.roi_created)

        self.btnInit.clicked.connect(self.initialize)
        self.btnPreview.clicked.connect(self.preview)
        self.btnBackground.clicked.connect(self.capture_background)
        self.btnROI1.clicked.connect(self.draw_roi1)
        self.btnROI2.clicked.connect(self.draw_roi2)
        self.btnSaveROI.clicked.connect(self.save_rois)
        self.btnLoadROI.clicked.connect(self.load_rois)
        self.btnBrowse.clicked.connect(self.select_save_path)
        self.btnTestReward.clicked.connect(lambda: self.reward())

        self.valve_event.connect(self.on_valve_event)
        self.btnStart.clicked.connect(self.start_tracking)
        self.btnStop.clicked.connect(self.stop_tracking)

    # =====================================================
    # HELPERS
    # =====================================================

    def tracking_active(self):

        return self.tracker is not None

    def now_string(self):

        return datetime.datetime.now().strftime(
            config.LOG_TIMESTAMP_FORMAT
        )

    # =====================================================
    # LIVE SETTINGS
    #
    # Values are stored on the window (used for the next
    # Initialize / Start) and pushed to any live object.
    # =====================================================

    def on_setting_changed(self, key, value):

        applied = value

        try:

            if key == "EXPOSURE_US":

                if self.camera:
                    applied = self.camera.set_exposure(value)

                self.EXPOSURE_US = applied

            elif key == "GAIN":

                if self.camera:
                    applied = self.camera.set_gain(value)

                self.GAIN = applied

            elif key == "CAMERA_FPS":

                if self.camera:
                    self.camera.set_fps(value)

                self.CAMERA_FPS = value

            elif key == "THRESHOLD":

                self.THRESHOLD = value

                if self.tracker:
                    self.tracker.threshold = value

            elif key == "MIN_CONTOUR_AREA":

                self.MIN_CONTOUR_AREA = value

                if self.tracker:
                    self.tracker.min_contour_area = value

            elif key == "MAX_CONTOUR_AREA":

                self.MAX_CONTOUR_AREA = value

                if self.tracker:
                    self.tracker.max_contour_area = value

            elif key == "DETECTION_SCALE":

                self.DETECTION_SCALE = value

                if self.tracker:
                    self.tracker.set_detection_scale(value)

            elif key == "BRIGHTNESS_COMP":

                self.BRIGHTNESS_COMP = value

                if self.tracker:
                    self.tracker.brightness_comp = value

            elif key == "MORPH_KERNEL_SIZE":

                #
                # Kernels must be odd
                #
                applied = max(1, int(value)) | 1

                self.MORPH_KERNEL_SIZE = applied

                if self.tracker:
                    self.tracker.set_kernel_size(applied)

            elif key == "TRACK_POLARITY":

                self.TRACK_POLARITY = value

                if self.tracker:
                    self.tracker.polarity = value

            elif key == "TRACK_LOST_GRACE_S":

                self.TRACK_LOST_GRACE_S = value

                if self.tracker:
                    self.tracker.lost_grace = value

            elif key == "DWELL_TIME_S":

                self.DWELL_TIME = value

                if self.tracker:
                    self.tracker.dwell_time = value

            elif key == "REWARD_LOCKOUT_S":

                self.REWARD_LOCKOUT = value

                if self.tracker:
                    self.tracker.lockout = value

            elif key == "VALVE_OPEN_MS":

                self.VALVE_OPEN_MS = value

                if self.valve:
                    self.valve.open_ms = value

            elif key == "NUM_BACKGROUND_FRAMES":

                self.NUM_BACKGROUND_FRAMES = value

        except Exception as e:

            self.statusLabel.setText(
                f"Could not apply {key}: {e}"
            )

            return

        #
        # Show the value that was really applied (e.g. clamped)
        #
        if applied != value:

            self.settingsPanel.set_value(
                key,
                applied
            )

        self.log_event(
            "SettingChanged",
            f"{key}={applied}"
        )

    def save_defaults(self):

        config_path = os.path.join(
            config.PROJECT_DIR,
            "config.py"
        )

        answer = QMessageBox.question(
            self,
            "Save as defaults",
            f"Overwrite the live-settings values in:\n{config_path}\n\n"
            "This replaces the current defaults.",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if answer != QMessageBox.Yes:
            return

        try:

            update_config_file(
                config_path,
                self.settingsPanel.values()
            )

        except (OSError, KeyError) as e:

            QMessageBox.critical(
                self,
                "Save as defaults",
                f"Could not update config.py:\n{e}"
            )

            return

        self.statusLabel.setText(
            "Defaults saved to config.py"
        )

        self.log_event(
            "DefaultsSaved",
            str(self.settingsPanel.values())
        )

    # =====================================================
    # INITIALIZATION
    # =====================================================

    def initialize(self):

        if self.camera is not None or self.valve is not None:

            QMessageBox.information(
                self,
                "Initialize",
                "Hardware is already initialized."
            )

            return

        try:

            # Create camera object first
            self.camera = SpinnakerCamera()

            # Then initialize hardware
            self.camera.initialize(
                fps=self.CAMERA_FPS,
                exposure_us=self.EXPOSURE_US,
                gain=self.GAIN
            )

            self.valve = BpodValve(
                port=self.BPOD_PORT,
                valve=self.BPOD_VALVE,
                open_ms=self.VALVE_OPEN_MS,
                callback=self.valve_event.emit
            )

            print(
                self.valve.describe()
            )

            #
            # The camera may not reach the requested rate
            #
            if self.camera.fps:

                self.settingsPanel.set_value(
                    "CAMERA_FPS",
                    int(round(self.camera.fps))
                )

            self.statusLabel.setText(
                "Camera + Bpod Connected"
            )

        except Exception as e:

            #
            # Release whatever was opened so Initialize can be retried
            #
            if self.camera is not None:

                self.camera.close()

                self.camera = None

            self.valve = None

            QMessageBox.critical(
                self,
                "Initialization Error",
                str(e)
            )

    # =====================================================
    # PREVIEW
    # =====================================================

    def preview(self):

        if self.camera is None:

            QMessageBox.warning(
                self,
                "Warning",
                "Initialize Camera First"
            )

            return

        if self.tracking_active():

            QMessageBox.warning(
                self,
                "Warning",
                "Stop the experiment before using Preview."
            )

            return

        #
        # Toggle preview
        #

        if not self.preview_running:

            self.preview_thread = PreviewThread(
                self.camera
            )

            self.preview_thread.frame_ready.connect(
                self.show_frame
            )

            self.preview_thread.error.connect(
                self.preview_failed
            )

            self.preview_thread.start()

            self.preview_running = True

            self.btnPreview.setText(
                "Stop Preview"
            )

            self.statusLabel.setText(
                "Live Preview Running"
            )

        else:

            self.stop_preview()

    def preview_failed(self, message):

        self.stop_preview()

        QMessageBox.critical(
            self,
            "Preview Error",
            message
        )

    # =====================================================
    # STOP PREVIEW
    # =====================================================

    def stop_preview(self):

        if self.preview_thread:

            self.preview_thread.stop()

            self.preview_thread.wait()

            self.preview_thread = None

        self.preview_running = False

        self.btnPreview.setText(
            "Preview"
        )

        self.statusLabel.setText(
            "Preview Stopped"
        )

    # =====================================================
    # BACKGROUND
    # =====================================================

    def capture_background(self):

        if self.camera is None:

            QMessageBox.warning(
                self,
                "Warning",
                "Initialize camera first."
            )
            return

        if self.tracking_active():

            QMessageBox.warning(
                self,
                "Warning",
                "Stop the experiment before capturing a new background."
            )
            return

        #
        # If preview is running, stop it first
        #
        if self.preview_running:

            self.stop_preview()

        self.statusLabel.setText(
            "Capturing Background..."
        )

        QApplication.processEvents()

        try:

            num_frames = self.NUM_BACKGROUND_FRAMES

            frames = []

            attempts = 0

            #
            # get_frame() returns None on timeout / incomplete image
            #
            while (
                len(frames) < num_frames
                and
                attempts < num_frames * 5
            ):

                attempts += 1

                frame = self.camera.get_frame()

                if frame is None:
                    continue

                if frame.ndim == 3:

                    gray = cv2.cvtColor(
                        frame,
                        cv2.COLOR_BGR2GRAY
                    )

                else:

                    gray = frame

                frames.append(
                    gray.astype(np.float32)
                )

            if len(frames) < num_frames:

                raise RuntimeError(
                    f"Only {len(frames)} of {num_frames} "
                    "frames could be acquired."
                )

            #
            # Average frames
            #
            self.background = np.mean(
                frames,
                axis=0
            ).astype(
                np.uint8
            )

            self.statusLabel.setText(
                f"Background Captured ({num_frames} frames)"
            )

            QMessageBox.information(
                self,
                "Background",
                "Background captured successfully."
            )

        except Exception as e:

            self.statusLabel.setText(
                "Background capture failed"
            )

            QMessageBox.critical(
                self,
                "Background Capture Error",
                str(e)
            )

    # =====================================================
    # ROI DRAWING
    # =====================================================

    def draw_roi1(self):

        self.statusLabel.setText(
            "Draw ROI1"
        )

        self.videoWidget.set_mode("ROI1")
        self.thresholdWidget.set_mode("ROI1")

    def draw_roi2(self):

        self.statusLabel.setText(
            "Draw ROI2"
        )

        self.videoWidget.set_mode("ROI2")
        self.thresholdWidget.set_mode("ROI2")

    def apply_roi(self, roi_name, roi):
        """
        Single place where an ROI is pushed to every consumer.
        """

        if roi_name == "ROI1":

            self.roi1 = roi

            self.videoWidget.roi1 = roi
            self.thresholdWidget.roi1 = roi

            if self.tracker:

                self.tracker.roi1 = roi

        elif roi_name == "ROI2":

            self.roi2 = roi

            self.videoWidget.roi2 = roi
            self.thresholdWidget.roi2 = roi

            if self.tracker:

                self.tracker.roi2 = roi

        self.videoWidget.update()

        self.thresholdWidget.update()

    def roi_created(
        self,
        roi,
        roi_name
    ):

        self.apply_roi(
            roi_name,
            roi
        )

        self.log_roi_update(
            roi_name,
            roi
        )

        self.save_rois()

        frame_number = 0

        if self.tracker is not None:

            frame_number = (
                self.tracker.frame_number
            )

        self.log_event(
            f"{roi_name}_UPDATED",
            (
                f"Frame={frame_number}, "
                f"ROI={roi}"
            )
        )

    # =====================================================
    # TRACKING
    # =====================================================

    def write_csv_header(self, path, header):

        with open(
            path,
            "w",
            newline=""
        ) as f:

            csv.writer(f).writerow(
                header
            )

    def start_tracking(self):

        if self.tracking_active():

            QMessageBox.information(
                self,
                "Experiment",
                "Experiment is already running."
            )

            return

        if self.preview_running:
            self.stop_preview()

        if self.camera is None:

            QMessageBox.warning(
                self,
                "Warning",
                "Initialize first."
            )

            return

        if self.background is None:

            QMessageBox.warning(
                self,
                "Warning",
                "Capture background first."
            )

            return

        #
        # Save directory
        #
        save_root = self.pathEdit.text().strip()

        if not save_root:

            QMessageBox.warning(
                self,
                "Save Directory",
                "Please select a save directory."
            )

            return

        if not os.path.isdir(save_root):

            QMessageBox.warning(
                self,
                "Invalid Save Directory",
                f"Folder does not exist:\n{save_root}"
            )

            return

        #
        # Grab a frame to size the video (retry on timeouts)
        #
        frame = None

        for _ in range(50):

            frame = self.camera.get_frame()

            if frame is not None:
                break

        if frame is None:

            QMessageBox.critical(
                self,
                "Camera",
                "Could not acquire a frame from the camera."
            )

            return

        h, w = frame.shape[:2]

        #
        # Create session folder
        #
        timestamp = datetime.datetime.now().strftime(
            config.SESSION_TIMESTAMP_FORMAT
        )

        self.session_folder = os.path.join(
            save_root,
            timestamp
        )

        os.makedirs(
            self.session_folder,
            exist_ok=True
        )

        print(
            "Session Folder:",
            self.session_folder
        )

        cv2.imwrite(
            os.path.join(
                self.session_folder,
                config.BACKGROUND_FILENAME
            ),
            self.background
        )

        #
        # Video writer (use the real camera rate)
        #
        video_fps = self.camera.fps or self.CAMERA_FPS

        self.video_writer = cv2.VideoWriter(
            os.path.join(
                self.session_folder,
                config.VIDEO_FILENAME
            ),
            cv2.VideoWriter_fourcc(
                *config.VIDEO_FOURCC
            ),
            video_fps,
            (w, h),
            frame.ndim == 3
        )

        if not self.video_writer.isOpened():

            self.video_writer = None

            QMessageBox.critical(
                self,
                "Video",
                "Could not open the video file for writing "
                f"(codec {config.VIDEO_FOURCC})."
            )

            return

        #
        # Session files
        #
        self.events_file = os.path.join(
            self.session_folder,
            config.EVENTS_FILENAME
        )

        self.write_csv_header(
            self.events_file,
            ["Timestamp", "Event", "Details"]
        )

        self.roi_file = os.path.join(
            self.session_folder,
            config.ROI_HISTORY_FILENAME
        )

        self.write_csv_header(
            self.roi_file,
            [
                "Timestamp",
                "Frame",
                "ROI",
                "X",
                "Y",
                "Width",
                "Height",
                "RewardState"
            ]
        )

        self.tracking_file = os.path.join(
            self.session_folder,
            config.TRACKING_FILENAME
        )

        self.tracking_fh = open(
            self.tracking_file,
            "w",
            newline=""
        )

        self.tracking_writer = csv.writer(
            self.tracking_fh
        )

        self.tracking_writer.writerow(
            [
                "Frame",
                "Timestamp",
                "Tracked",
                "X",
                "Y",
                "RewardArmed",
                "InsideROI1",
                "InsideROI2",
                "RewardState"
            ]
        )

        self.tracking_rows = 0

        #
        # Recorder
        #
        self.recorder = RecorderThread(
            self.video_writer
        )

        self.recorder.start()

        #
        # Tracker
        #
        self.tracker = TrackingThread(
            self.camera,
            threshold=self.THRESHOLD,
            min_contour_area=self.MIN_CONTOUR_AREA,
            max_contour_area=self.MAX_CONTOUR_AREA,
            dwell_time=self.DWELL_TIME,
            lockout=self.REWARD_LOCKOUT,
            polarity=self.TRACK_POLARITY,
            kernel_size=self.MORPH_KERNEL_SIZE,
            lost_grace=self.TRACK_LOST_GRACE_S,
            detection_scale=self.DETECTION_SCALE,
            brightness_comp=self.BRIGHTNESS_COMP
        )

        self.tracker.recorder = self.recorder

        self.tracker.background = self.background

        self.tracker.roi1 = self.roi1

        self.tracker.roi2 = self.roi2

        self.tracker.frame_ready.connect(self.show_frame)

        self.tracker.threshold_ready.connect(self.show_threshold)

        self.tracker.reward_signal.connect(self.reward)

        self.tracker.tracking_data.connect(self.log_tracking)

        self.tracker.log_event.connect(self.log_event)

        self.tracker.fps_ready.connect(self.update_fps)

        #
        # Log experiment start, then start tracking
        #
        self.log_event(
            "ExperimentStart"
        )

        self.tracker.start()

        #
        # The video file is written at a fixed rate
        #
        self.settingsPanel.set_enabled(
            "CAMERA_FPS",
            False
        )

        self.settingsPanel.set_enabled(
            "NUM_BACKGROUND_FRAMES",
            False
        )

        self.statusLabel.setText(
            "Tracking Running"
        )

    def stop_tracking(self):

        if self.tracker is None:
            return

        self.tracker.stop()

        self.tracker.wait()

        #
        # Deliver signals still queued from the tracker thread
        # while the files are open
        #
        QApplication.processEvents()

        #
        # The video header says CAMERA fps; report what was really
        # achieved so a slow tracking loop is not silent
        #
        achieved = self.tracker.measured_fps

        nominal = (
            self.camera.fps or self.CAMERA_FPS
            if self.camera else self.CAMERA_FPS
        )

        dropped = self.recorder.dropped if self.recorder else 0

        slow = achieved < 0.95 * nominal

        self.log_event(
            "RecordingRate",
            f"achieved={achieved:.1f} fps, nominal={nominal:.1f} fps, "
            f"frames={self.tracker.frame_number}, "
            f"video_frames_dropped={dropped}"
        )

        self.log_event(
            "ExperimentStop"
        )

        self.tracker = None

        #
        # Drains the queue, then releases the video writer
        #
        if self.recorder:

            self.recorder.stop()

            self.recorder = None

        self.video_writer = None

        if self.tracking_fh is not None:

            self.tracking_fh.close()

            self.tracking_fh = None

            self.tracking_writer = None

        self.events_file = None
        self.roi_file = None
        self.tracking_file = None

        self.settingsPanel.set_enabled(
            "CAMERA_FPS",
            True
        )

        self.settingsPanel.set_enabled(
            "NUM_BACKGROUND_FRAMES",
            True
        )

        if slow:

            self.statusLabel.setText(
                f"Tracking Stopped - WARNING: only {achieved:.0f} fps "
                f"processed (camera {nominal:.0f}); video plays too fast. "
                "Lower Detect scale."
            )

        elif dropped:

            self.statusLabel.setText(
                f"Tracking Stopped - WARNING: {dropped} video frames "
                "were dropped (disk/encoder too slow); tracking.csv is complete."
            )

        else:

            self.statusLabel.setText(
                "Tracking Stopped"
            )

    # =====================================================
    # REWARD
    # =====================================================

    def reward(self):

        if self.valve is None:

            self.statusLabel.setText(
                "Reward not sent: Bpod not connected"
            )

            return

        if not self.valve.pulse():
            return

        self.rewards += 1

        self.log_event(
            "RewardDelivered",
            f"Reward #{self.rewards}"
        )

        self.rewardLabel.setText(
            f"Rewards: {self.rewards}"
        )

        print(
            f"Reward #{self.rewards}"
        )

    def on_valve_event(self, event, details):

        self.log_event(
            event,
            details
        )

        if event == "ValveError":

            self.statusLabel.setText(
                f"VALVE ERROR - reward may not have been delivered: "
                f"{details}"
            )

    # =====================================================
    # DISPLAY
    # =====================================================

    def to_pixmap(
        self,
        frame,
        interpolation,
        widget
    ):
        """
        BGR / gray numpy frame -> QPixmap fitted into `widget` with
        the aspect ratio preserved (so widget coordinates map
        linearly to image coordinates).
        """

        if frame.ndim == 2:

            rgb = cv2.cvtColor(
                frame,
                cv2.COLOR_GRAY2RGB
            )

        else:

            rgb = cv2.cvtColor(
                frame,
                cv2.COLOR_BGR2RGB
            )

        max_w, max_h = widget.width(), widget.height()

        if max_w < 50 or max_h < 50:

            max_w, max_h = config.DISPLAY_SIZE

        scale = min(
            max_w / rgb.shape[1],
            max_h / rgb.shape[0]
        )

        rgb = cv2.resize(
            rgb,
            (
                max(1, int(rgb.shape[1] * scale)),
                max(1, int(rgb.shape[0] * scale))
            ),
            interpolation=interpolation
        )

        h, w, ch = rgb.shape

        qimg = QImage(
            rgb.data,
            w,
            h,
            ch * w,
            QImage.Format_RGB888
        )

        # fromImage copies, so `rgb` may be freed afterwards
        return QPixmap.fromImage(qimg)

    def show_frame(self, frame):

        self.last_frame = frame

        self.videoWidget.set_image_size(
            frame.shape[1],
            frame.shape[0]
        )

        self.videoWidget.setPixmap(
            self.to_pixmap(
                frame,
                cv2.INTER_AREA,
                self.videoWidget
            )
        )

    def show_threshold(self, frame):

        self.last_threshold = frame

        self.thresholdWidget.set_image_size(
            frame.shape[1],
            frame.shape[0]
        )

        self.thresholdWidget.setPixmap(
            self.to_pixmap(
                frame,
                cv2.INTER_NEAREST,
                self.thresholdWidget
            )
        )

    def resizeEvent(self, event):

        super().resizeEvent(event)

        #
        # Re-fit the last images when idle (while streaming the
        # next frame does this anyway)
        #
        if self.last_frame is not None:
            self.show_frame(self.last_frame)

        if self.last_threshold is not None:
            self.show_threshold(self.last_threshold)

    # =====================================================
    # CLEANUP
    # =====================================================

    def closeEvent(
        self,
        event
    ):

        try:

            if self.preview_thread:

                self.stop_preview()

        except Exception as e:
            print(f"Preview close error: {e}")

        #
        # Finalizes the video file and CSVs
        #
        try:

            self.stop_tracking()

        except Exception as e:
            print(f"Tracking close error: {e}")

        try:

            if self.valve:

                self.valve.close()

                self.valve = None

        except Exception as e:
            print(f"Bpod close error: {e}")

        try:

            if self.camera:

                self.camera.close()

                self.camera = None

        except Exception as e:
            print(f"Camera close error: {e}")

        event.accept()

    # =====================================================
    # FOLDER SELECTION
    # =====================================================

    def select_save_path(self):

        folder = QFileDialog.getExistingDirectory(
            self,
            "Select Save Directory"
        )

        if folder:

            self.pathEdit.setText(
                folder
            )

    # =====================================================
    # SAVE ROIS
    # =====================================================

    def save_rois(self):

        folder = self.pathEdit.text().strip()

        if not folder or not os.path.isdir(folder):

            return

        roi_data = []

        for name, roi in (
            ("ROI1", self.roi1),
            ("ROI2", self.roi2)
        ):

            if roi:

                x, y, w, h = roi

                roi_data.append(
                    [name, x, y, w, h]
                )

        df = pd.DataFrame(
            roi_data,
            columns=[
                "ROI",
                "X",
                "Y",
                "Width",
                "Height"
            ]
        )

        df.to_csv(
            os.path.join(
                folder,
                config.ROI_FILENAME
            ),
            index=False
        )

        print("ROIs saved.")

    # =====================================================
    # LOAD ROIS
    # =====================================================

    def load_rois(self):

        folder = self.pathEdit.text().strip()

        roi_file = os.path.join(
            folder,
            config.ROI_FILENAME
        )

        if not folder or not os.path.isfile(roi_file):

            QMessageBox.warning(
                self,
                "Load ROI",
                f"No {config.ROI_FILENAME} found in:\n{folder}"
            )

            return

        try:

            df = pd.read_csv(
                roi_file
            )

            for _, row in df.iterrows():

                roi = (
                    int(row["X"]),
                    int(row["Y"]),
                    int(row["Width"]),
                    int(row["Height"])
                )

                if row["ROI"] in ("ROI1", "ROI2"):

                    self.apply_roi(
                        row["ROI"],
                        roi
                    )

        except (KeyError, ValueError) as e:

            QMessageBox.critical(
                self,
                "Load ROI",
                f"Invalid ROI file:\n{e}"
            )

    # =====================================================
    # LOG EVENTS
    # =====================================================

    def log_event(
        self,
        event_name,
        details=""
    ):

        #
        # No active experiment
        #
        if self.events_file is None:
            return

        with open(
            self.events_file,
            "a",
            newline=""
        ) as f:

            csv.writer(f).writerow(
                [
                    self.now_string(),
                    event_name,
                    details
                ]
            )

    def log_roi_update(
        self,
        roi_name,
        roi
    ):

        if self.roi_file is None:
            return

        frame_number = 0
        reward_state = ""

        if self.tracker is not None:

            frame_number = (
                self.tracker.frame_number
            )

            reward_state = (
                self.tracker.reward_state
            )

        with open(
            self.roi_file,
            "a",
            newline=""
        ) as f:

            csv.writer(f).writerow(
                [
                    self.now_string(),
                    frame_number,
                    roi_name,
                    roi[0],
                    roi[1],
                    roi[2],
                    roi[3],
                    reward_state
                ]
            )

    # =====================================================
    # LOG TRACKING DATA
    # =====================================================

    def log_tracking(
        self,
        frame,
        timestamp,
        tracked,
        x,
        y,
        armed,
        roi1,
        roi2,
        reward_state
    ):

        if self.tracking_writer is None:
            return

        self.tracking_writer.writerow([
            frame,
            timestamp,
            tracked,
            x,
            y,
            armed,
            roi1,
            roi2,
            reward_state
        ])

        self.tracking_rows += 1

        if self.tracking_rows % 30 == 0:

            self.tracking_fh.flush()

    # =====================================================
    # UPDATE FPS DISPLAY
    # =====================================================

    def update_fps(self, fps):

        self.fpsLabel.setText(
            f"FPS: {fps:.1f}"
        )


if __name__ == "__main__":

    app = QApplication(
        sys.argv
    )

    win = MainWindow()

    win.show()

    sys.exit(
        app.exec()
    )
