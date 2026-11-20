# tracking.py

from PyQt5.QtCore import QThread, pyqtSignal

import cv2
import numpy as np
import time

import config


class TrackingThread(QThread):

    frame_ready = pyqtSignal(np.ndarray)

    threshold_ready = pyqtSignal(np.ndarray)

    reward_signal = pyqtSignal()

    log_event = pyqtSignal(str, str)

    tracking_data = pyqtSignal(
        int,      # frame number
        float,    # timestamp
        bool,     # tracked (False = object lost, x = y = -1)
        int,      # x   (full-resolution image coordinates)
        int,      # y
        bool,     # armed
        bool,     # roi1
        bool,     # roi2
        str       # reward state
    )

    fps_ready = pyqtSignal(float)

    def __init__(
        self,
        camera,
        threshold=config.THRESHOLD,
        min_contour_area=config.MIN_CONTOUR_AREA,
        max_contour_area=config.MAX_CONTOUR_AREA,
        dwell_time=config.DWELL_TIME_S,
        lockout=config.REWARD_LOCKOUT_S,
        polarity=config.TRACK_POLARITY,
        kernel_size=config.MORPH_KERNEL_SIZE,
        lost_grace=config.TRACK_LOST_GRACE_S,
        detection_scale=config.DETECTION_SCALE,
        brightness_comp=config.BRIGHTNESS_COMP,
        display_interval=config.DISPLAY_INTERVAL_S
    ):

        super().__init__()

        self.camera = camera

        # Set by MainWindow before start()
        self.recorder = None

        self.running = False

        # Full-resolution background (uint8, same size as the frames)
        self.background = None

        self.roi1 = None

        self.roi2 = None

        self.threshold = threshold

        # In FULL-resolution pixels
        self.min_contour_area = min_contour_area

        # 0 = no upper limit
        self.max_contour_area = max_contour_area

        self.dwell_time = dwell_time    # seconds

        self.lockout = lockout          # seconds

        self.polarity = polarity

        self.lost_grace = lost_grace

        # "on" / "off": compensate global brightness drift
        self.brightness_comp = brightness_comp

        self.display_interval = display_interval

        # Detection runs on a downscaled copy for speed
        self.detection_scale = 1.0
        self.kernel_size = 1
        self.kernel = np.ones((1, 1), np.uint8)

        self.set_detection_scale(detection_scale)
        self.set_kernel_size(kernel_size)

        self.bg_small = None
        self.bg_small_key = None

        self.last_display_time = 0

        self.last_reward = 0

        self.frame_number = 0

        self.start_time = time.time()
        self.elapsed_total = 0.0

        self.prev_frame_time = None
        self.fps_ema = None

        self.reward_state = config.STATE_WAIT_GREEN

        self.green_entry_time = None

        self.last_seen_time = None

        self.was_in_roi1 = False

        self.was_in_roi2 = False

    def stop(self):
        self.running = False

    # =====================================================
    # LIVE SETTINGS (safe while running: values are swapped
    # atomically)
    # =====================================================

    def rebuild_kernel(self):
        """
        The kernel size is specified at full resolution and scaled
        to the detection image.
        """

        size = max(
            1,
            int(round(self.kernel_size * self.detection_scale))
        ) | 1

        self.kernel = np.ones(
            (size, size),
            np.uint8
        )

    def set_kernel_size(self, size):

        self.kernel_size = max(1, int(size)) | 1

        self.rebuild_kernel()

    def set_detection_scale(self, scale):

        self.detection_scale = min(
            1.0,
            max(0.1, float(scale))
        )

        self.rebuild_kernel()

    @property
    def measured_fps(self):
        """
        Frames actually processed per second since start.
        """

        if self.elapsed_total <= 0:
            return 0.0

        return self.frame_number / self.elapsed_total

    # =====================================================
    # MAIN LOOP
    # =====================================================

    def run(self):

        self.running = True

        self.start_time = time.time()

        while self.running:

            frame = self.camera.get_frame()

            #
            # Timeout / incomplete image. Not counted as a frame,
            # so frame_number matches the recorded video.
            #
            if frame is None:
                continue

            now = time.time()

            elapsed_time = now - self.start_time

            self.elapsed_total = elapsed_time

            self.frame_number += 1

            #
            # Frame rate = time between frames (true throughput)
            #
            if self.prev_frame_time is not None:

                instant = 1.0 / max(
                    1e-6,
                    now - self.prev_frame_time
                )

                self.fps_ema = (
                    instant
                    if self.fps_ema is None
                    else 0.95 * self.fps_ema + 0.05 * instant
                )

            self.prev_frame_time = now

            #
            # Save EVERY frame (raw, full resolution)
            #
            if self.recorder is not None:

                self.recorder.add_frame(frame)

            if frame.ndim == 2:

                gray = frame

            else:

                gray = cv2.cvtColor(
                    frame,
                    cv2.COLOR_BGR2GRAY
                )

            want_display = (
                now - self.last_display_time
                >= self.display_interval
            )

            #
            # Skip until background exists
            #
            if self.background is None:

                if want_display:

                    self.last_display_time = now

                    self.frame_ready.emit(
                        self.to_bgr(frame)
                    )

                continue

            #
            # Detection on a downscaled copy
            #
            small = self.downscale(gray)

            bg_small = self.small_background(small.shape)

            th, max_diff = self.segment(
                small,
                bg_small
            )

            #
            # Map back to full-resolution coordinates / areas
            #
            sx = gray.shape[1] / small.shape[1]
            sy = gray.shape[0] / small.shape[0]

            cx, cy, area = self.find_object(
                th,
                sx,
                sy
            )

            tracked = cx is not None

            inside_roi1, inside_roi2 = self.process_mouse(
                now,
                cx,
                cy
            )

            armed = (
                self.reward_state
                == config.STATE_WAIT_GREEN
            )

            self.tracking_data.emit(
                self.frame_number,
                elapsed_time,
                tracked,
                cx if tracked else -1,
                cy if tracked else -1,
                armed,
                inside_roi1,
                inside_roi2,
                self.reward_state
            )

            #
            # Refresh GUI at a reduced rate only
            #
            if want_display:

                self.last_display_time = now

                if self.fps_ema is not None:

                    self.fps_ready.emit(
                        self.fps_ema
                    )

                self.emit_display(
                    frame,
                    gray,
                    th,
                    cx,
                    cy,
                    area,
                    max_diff,
                    tracked,
                    inside_roi1,
                    inside_roi2,
                    elapsed_time
                )

    # =====================================================
    # DISPLAY
    # =====================================================

    def emit_display(
        self,
        frame,
        gray,
        th,
        cx,
        cy,
        area,
        max_diff,
        tracked,
        inside_roi1,
        inside_roi2,
        elapsed_time
    ):

        display = self.to_bgr(frame)

        #
        # The threshold view is shown at full size so ROI
        # coordinates match the camera view
        #
        if th.shape != gray.shape:

            th = cv2.resize(
                th,
                (gray.shape[1], gray.shape[0]),
                interpolation=cv2.INTER_NEAREST
            )

        threshold_display = cv2.cvtColor(
            th,
            cv2.COLOR_GRAY2BGR
        )

        cv2.putText(
            display,
            f"Frame: {self.frame_number}",
            (20, 40),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 0),
            2
        )

        cv2.putText(
            display,
            f"Time: {elapsed_time:.2f}s",
            (20, 80),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.8,
            (255, 255, 0),
            2
        )

        if tracked:

            for img in (display, threshold_display):

                cv2.circle(
                    img,
                    (cx, cy),
                    10,
                    (255, 0, 0),
                    -1
                )

        lines = (
            (f"ROI1: {inside_roi1}", (0, 255, 0)),
            (f"ROI2: {inside_roi2}", (0, 0, 255)),
            (f"State: {self.reward_state}", (255, 255, 0)),
            (
                f"Area: {int(area)} (min {self.min_contour_area}, "
                f"max {self.max_contour_area})",
                (255, 255, 0)
            ),
            # Largest difference from the background this frame:
            # an object only registers if this exceeds Threshold
            (
                f"Max diff: {max_diff} (threshold {self.threshold})",
                (255, 255, 0)
            )
        )

        for i, (text, color) in enumerate(lines):

            cv2.putText(
                threshold_display,
                text,
                (20, 40 + 40 * i),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.8,
                color,
                2
            )

        self.frame_ready.emit(
            display
        )

        self.threshold_ready.emit(
            threshold_display
        )

    # =====================================================
    # HELPERS
    # =====================================================

    @staticmethod
    def to_bgr(frame):
        """
        Returns a NEW 3-channel copy, safe to draw on.
        """

        if frame.ndim == 2:

            return cv2.cvtColor(
                frame,
                cv2.COLOR_GRAY2BGR
            )

        return frame.copy()

    def downscale(self, gray):

        scale = self.detection_scale

        if scale >= 1.0:
            return gray

        return cv2.resize(
            gray,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA
        )

    def small_background(self, shape):
        """
        Background resized to the detection image (cached).
        """

        bg = self.background

        if bg.shape == shape:
            return bg

        key = (id(bg), bg.shape, shape)

        if self.bg_small_key != key:

            self.bg_small = cv2.resize(
                bg,
                (shape[1], shape[0]),
                interpolation=cv2.INTER_AREA
            )

            self.bg_small_key = key

        return self.bg_small

    def segment(self, gray, background):
        """
        Background subtraction -> (cleaned binary mask, max difference).
        """

        #
        # Scale the frame so its overall brightness matches the
        # background. Without this a lamp / IR panel brightness change
        # makes the whole image look like one big object. Medians of a
        # subsample are used so a small object barely affects them.
        #
        if self.brightness_comp == "on":

            ref = float(np.median(background[::8, ::8]))

            cur = float(np.median(gray[::8, ::8]))

            if cur > 1 and ref > 1:

                gray = cv2.convertScaleAbs(
                    gray,
                    alpha=min(2.0, max(0.5, ref / cur))
                )

        if self.polarity == "dark":

            diff = cv2.subtract(
                background,
                gray
            )

        elif self.polarity == "bright":

            diff = cv2.subtract(
                gray,
                background
            )

        else:

            diff = cv2.absdiff(
                gray,
                background
            )

        max_diff = int(diff.max())

        _, th = cv2.threshold(
            diff,
            self.threshold,
            255,
            cv2.THRESH_BINARY
        )

        th = cv2.morphologyEx(
            th,
            cv2.MORPH_OPEN,
            self.kernel
        )

        th = cv2.morphologyEx(
            th,
            cv2.MORPH_CLOSE,
            self.kernel
        )

        return th, max_diff

    def find_object(self, th, sx=1.0, sy=1.0):
        """
        Returns (cx, cy, area) of the largest blob in FULL-resolution
        units (sx, sy = full / detection size), or (None, None, area)
        if nothing large enough was found.
        """

        contours, _ = cv2.findContours(
            th,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )

        if not contours:
            return None, None, 0

        #
        # Largest blob whose size is plausible for the object. Blobs
        # above max_contour_area (e.g. a shadow or arm across the
        # field) are skipped instead of hiding the real object.
        #
        largest = 0

        for c in sorted(
            contours,
            key=cv2.contourArea,
            reverse=True
        ):

            area = cv2.contourArea(c) * sx * sy

            largest = max(largest, area)

            if area <= self.min_contour_area:
                break

            if (
                self.max_contour_area
                and
                area > self.max_contour_area
            ):
                continue

            M = cv2.moments(c)

            if M["m00"] <= 0:
                continue

            return (
                int(M["m10"] / M["m00"] * sx),
                int(M["m01"] / M["m00"] * sy),
                area
            )

        return None, None, largest

    @staticmethod
    def inside(roi, x, y):

        if not roi:
            return False

        rx, ry, w, h = roi

        return (
            rx < x < rx + w
            and
            ry < y < ry + h
        )

    # =====================================================
    # REWARD STATE MACHINE
    # =====================================================

    def process_mouse(self, current_time, x, y):
        """
        x, y = None when the object is not detected.
        Returns (inside_roi1, inside_roi2).
        """

        #
        # Object lost: keep state during a short grace period,
        # then reset so a stale dwell timer cannot fire a reward.
        #
        if x is None:

            if (
                self.last_seen_time is None
                or
                current_time - self.last_seen_time
                > self.lost_grace
            ):

                self.green_entry_time = None
                self.was_in_roi1 = False
                self.was_in_roi2 = False

            return False, False

        self.last_seen_time = current_time

        inside_roi1 = self.inside(self.roi1, x, y)
        inside_roi2 = self.inside(self.roi2, x, y)

        roi2_entry = (
            inside_roi2
            and
            not self.was_in_roi2
        )

        # ============================
        # WAIT FOR GREEN
        # ============================

        if self.reward_state == config.STATE_WAIT_GREEN:

            if inside_roi1:

                if self.green_entry_time is None:

                    self.green_entry_time = current_time

                    self.log_event.emit(
                        "GreenEntry",
                        f"Frame={self.frame_number}"
                    )

                dwell = (
                    current_time
                    - self.green_entry_time
                )

                if (
                    dwell >= self.dwell_time
                    and
                    current_time - self.last_reward
                    > self.lockout
                ):

                    # MainWindow.reward() logs RewardDelivered
                    self.reward_signal.emit()

                    self.last_reward = current_time

                    self.reward_state = config.STATE_WAIT_RED

                    self.log_event.emit(
                        "RewardState",
                        (
                            f"{config.STATE_WAIT_RED}, "
                            f"Frame={self.frame_number}, "
                            f"Dwell={dwell:.3f}"
                        )
                    )

                    self.green_entry_time = None

            else:

                self.green_entry_time = None

        # ============================
        # WAIT FOR RED
        # ============================

        elif self.reward_state == config.STATE_WAIT_RED:

            if roi2_entry:

                self.log_event.emit(
                    "RedEntry",
                    f"Frame={self.frame_number}"
                )

                self.reward_state = config.STATE_WAIT_GREEN

                self.log_event.emit(
                    "RewardState",
                    (
                        f"{config.STATE_WAIT_GREEN}, "
                        f"Frame={self.frame_number}"
                    )
                )

                self.green_entry_time = None

        # ============================
        # SAVE OCCUPANCY STATE
        # ============================

        self.was_in_roi1 = inside_roi1
        self.was_in_roi2 = inside_roi2

        return inside_roi1, inside_roi2
