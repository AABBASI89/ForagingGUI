from PyQt5.QtWidgets import (
    QGroupBox,
    QGridLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QComboBox
)

from PyQt5.QtCore import Qt, pyqtSignal


# key, label, kind, min, max, step, decimals, tooltip
#
# Keys match the names in config.py.
SETTINGS = [
    (
        "EXPOSURE_US", "Exposure (us)", "int", 10, 100000, 100, 0,
        "Camera exposure time. Limited by the frame rate."
    ),
    (
        "GAIN", "Gain (dB)", "float", 0, 48, 0.5, 1,
        "Camera gain."
    ),
    (
        "CAMERA_FPS", "Camera FPS", "int", 1, 500, 5, 0,
        "Acquisition frame rate. Locked while an experiment runs."
    ),
    (
        "THRESHOLD", "Threshold", "int", 1, 255, 1, 0,
        "Minimum brightness difference from the background."
    ),
    (
        "MIN_CONTOUR_AREA", "Min area (px)", "int", 0, 1000000, 50, 0,
        "Smaller blobs are ignored."
    ),
    (
        "MAX_CONTOUR_AREA", "Max area (px)", "int", 0, 4000000, 5000, 0,
        "Larger blobs are ignored (shadows, arms). 0 = no limit."
    ),
    (
        "MORPH_KERNEL_SIZE", "Morph kernel", "int", 1, 51, 2, 0,
        "Open/close kernel size (odd). Larger removes more noise."
    ),
    (
        "DETECTION_SCALE", "Detect scale", "float", 0.1, 1.0, 0.05, 2,
        "Detection runs on a scaled-down image. Lower = faster. "
        "Recording and coordinates stay full resolution."
    ),
    (
        "TRACK_POLARITY", "Polarity", "choice", ["dark", "bright", "both"],
        None, None, None,
        "dark: object darker than background. bright: lighter. "
        "both: either."
    ),
    (
        "BRIGHTNESS_COMP", "Brightness comp", "choice", ["on", "off"],
        None, None, None,
        "on: rescale frames to the background's overall brightness, so "
        "lighting drift is not detected as an object."
    ),
    (
        "TRACK_LOST_GRACE_S", "Lost grace (s)", "float", 0, 5, 0.05, 2,
        "How long the object may vanish before dwell/ROI state resets."
    ),
    (
        "DWELL_TIME_S", "Dwell (s)", "float", 0, 10, 0.1, 2,
        "Time the object must stay in ROI1 to earn a reward."
    ),
    (
        "REWARD_LOCKOUT_S", "Lockout (s)", "float", 0, 60, 0.1, 2,
        "Minimum time between rewards."
    ),
    (
        "VALVE_OPEN_MS", "Valve open (ms)", "int", 10, 5000, 10, 0,
        "How long the Bpod valve opens per reward (timed by the Bpod)."
    ),
    (
        "CALIBRATE_PULSES", "Calibrate pulses", "int", 1, 1000, 10, 0,
        "Number of valve openings done by Calibrate Valve."
    ),
    (
        "NUM_BACKGROUND_FRAMES", "Background frames", "int", 1, 500, 10, 0,
        "Frames averaged by Capture Background."
    ),
]

COLUMNS = 4

# Empty space between setting columns
COLUMN_GAP_PX = 30

# Fixed width of each setting's spin box / combo box
WIDGET_WIDTH_PX = 110


class SettingsPanel(QGroupBox):
    """
    Live-editable settings.

    changed(key, value) is emitted when the USER edits a control.
    Programmatic updates via set_value() do not emit.
    """

    changed = pyqtSignal(str, object)

    save_requested = pyqtSignal()

    def __init__(self, values):
        """
        values: dict key -> initial value (e.g. from config.py)
        """

        super().__init__("Live Settings")

        self.widgets = {}

        layout = QGridLayout()

        for i, spec in enumerate(SETTINGS):

            key, label, kind = spec[0], spec[1], spec[2]

            widget = self.make_widget(spec)

            widget.setToolTip(spec[7])

            self.set_value_on(widget, kind, values[key])

            self.connect_widget(widget, kind, key)

            self.widgets[key] = (widget, kind)

            row, col = divmod(i, COLUMNS)

            # Each group is label | widget | gap; the label is right-aligned
            # so it sits right next to its widget
            layout.addWidget(
                QLabel(label),
                row,
                col * 3,
                Qt.AlignRight | Qt.AlignVCenter
            )
            widget.setFixedWidth(WIDGET_WIDTH_PX)

            layout.addWidget(widget, row, col * 3 + 1)

        self.btnSaveDefaults = QPushButton(
            "Save as defaults (overwrites config.py)"
        )

        self.btnSaveDefaults.clicked.connect(
            self.save_requested.emit
        )

        for col in range(COLUMNS - 1):

            layout.setColumnMinimumWidth(col * 3 + 2, COLUMN_GAP_PX)

        layout.setHorizontalSpacing(6)

        # Spare width goes to the right of the columns, not into them
        layout.setColumnStretch(COLUMNS * 3 - 1, 1)

        layout.addWidget(
            self.btnSaveDefaults,
            len(SETTINGS) // COLUMNS + 1,
            0,
            1,
            COLUMNS * 3 - 1
        )

        self.setLayout(layout)

    # =====================================================
    # BUILD
    # =====================================================

    @staticmethod
    def make_widget(spec):

        kind = spec[2]

        if kind == "choice":

            widget = QComboBox()

            widget.addItems(spec[3])

            return widget

        _, _, _, lo, hi, step, decimals, _ = spec

        if kind == "int":

            widget = QSpinBox()

        else:

            widget = QDoubleSpinBox()

            widget.setDecimals(decimals)

        widget.setRange(lo, hi)

        widget.setSingleStep(step)

        #
        # Typed values apply on Enter; arrows / wheel apply instantly
        #
        widget.setKeyboardTracking(False)

        return widget

    def connect_widget(self, widget, kind, key):

        if kind == "choice":

            widget.currentTextChanged.connect(
                lambda value, k=key: self.changed.emit(k, value)
            )

        else:

            widget.valueChanged.connect(
                lambda value, k=key: self.changed.emit(k, value)
            )

    # =====================================================
    # PROGRAMMATIC ACCESS
    # =====================================================

    @staticmethod
    def set_value_on(widget, kind, value):

        widget.blockSignals(True)

        if kind == "choice":

            widget.setCurrentText(str(value))

        elif kind == "int":

            # e.g. the camera reports exposure as 1999.98
            widget.setValue(int(round(value)))

        else:

            widget.setValue(float(value))

        widget.blockSignals(False)

    def set_value(self, key, value):
        """
        Update a control without emitting changed().
        """

        widget, kind = self.widgets[key]

        self.set_value_on(widget, kind, value)

    def values(self):
        """
        Current value of every control, keyed by config.py name.
        """

        result = {}

        for key, (widget, kind) in self.widgets.items():

            if kind == "choice":

                result[key] = widget.currentText()

            else:

                result[key] = widget.value()

        return result

    def set_enabled(self, key, enabled):

        self.widgets[key][0].setEnabled(enabled)
