from PyQt5.QtWidgets import QLabel
from PyQt5.QtCore import Qt, QRect, pyqtSignal
from PyQt5.QtGui import QPainter, QPen, QColor

import config


class VideoWidget(QLabel):

    roi_created = pyqtSignal(object, str)

    def __init__(self):

        super().__init__()

        self.setMouseTracking(True)

        self.setAlignment(Qt.AlignCenter)

        #
        # Original image dimensions
        #
        self.image_width = 2048
        self.image_height = 2048

        #
        # Drawing state (widget coordinates)
        #
        self.drawing = False

        self.start_x = 0
        self.start_y = 0

        self.end_x = 0
        self.end_y = 0

        #
        # ROIs stored in IMAGE coordinates
        #
        self.roi1 = None
        self.roi2 = None

        self.current_mode = None

    # =====================================================
    # UPDATE IMAGE SIZE
    # =====================================================

    def set_image_size(
        self,
        width,
        height
    ):

        self.image_width = width
        self.image_height = height

    # =====================================================
    # ROI MODE
    # =====================================================

    def set_mode(self, mode):

        self.current_mode = mode

    # =====================================================
    # COORDINATE MAPPING
    #
    # The pixmap is centered in the widget and shown 1:1,
    # so widget <-> image mapping must use the pixmap's
    # offset and size, not the widget's.
    # =====================================================

    def pixmap_rect(self):
        """
        Rectangle (widget coordinates) occupied by the pixmap,
        or None if there is no image yet.
        """

        pm = self.pixmap()

        if pm is None or pm.isNull():
            return None

        return QRect(
            (self.width() - pm.width()) // 2,
            (self.height() - pm.height()) // 2,
            pm.width(),
            pm.height()
        )

    def clamp_to_pixmap(self, x, y, rect):

        return (
            min(max(x, rect.left()), rect.right()),
            min(max(y, rect.top()), rect.bottom())
        )

    # =====================================================
    # MOUSE PRESS
    # =====================================================

    def mousePressEvent(self, event):

        if self.current_mode is None:
            return

        rect = self.pixmap_rect()

        if rect is None:
            return

        x, y = self.clamp_to_pixmap(
            event.x(),
            event.y(),
            rect
        )

        self.drawing = True

        self.start_x = x
        self.start_y = y

        self.end_x = x
        self.end_y = y

        self.update()

    # =====================================================
    # MOUSE MOVE
    # =====================================================

    def mouseMoveEvent(self, event):

        if not self.drawing:
            return

        rect = self.pixmap_rect()

        if rect is None:
            return

        self.end_x, self.end_y = self.clamp_to_pixmap(
            event.x(),
            event.y(),
            rect
        )

        self.update()

    # =====================================================
    # MOUSE RELEASE
    # =====================================================

    def mouseReleaseEvent(self, event):

        if not self.drawing:
            return

        self.drawing = False

        rect = self.pixmap_rect()

        if rect is None:
            self.update()
            return

        self.end_x, self.end_y = self.clamp_to_pixmap(
            event.x(),
            event.y(),
            rect
        )

        #
        # Widget coordinates relative to the pixmap
        #
        x1 = min(self.start_x, self.end_x) - rect.left()
        y1 = min(self.start_y, self.end_y) - rect.top()

        w = abs(self.end_x - self.start_x)
        h = abs(self.end_y - self.start_y)

        #
        # A click without a drag is not an ROI
        #
        if w < 2 or h < 2:

            self.update()

            return

        #
        # Convert to IMAGE coordinates
        #
        scale_x = self.image_width / max(1, rect.width())
        scale_y = self.image_height / max(1, rect.height())

        roi = (
            int(x1 * scale_x),
            int(y1 * scale_y),
            int(w * scale_x),
            int(h * scale_y)
        )

        print(
            f"{self.current_mode}: {roi}"
        )

        if self.current_mode == "ROI1":

            self.roi1 = roi

            self.roi_created.emit(
                roi,
                "ROI1"
            )

        elif self.current_mode == "ROI2":

            self.roi2 = roi

            self.roi_created.emit(
                roi,
                "ROI2"
            )

        self.current_mode = None

        self.update()

    # =====================================================
    # PAINT
    # =====================================================

    def draw_saved_roi(self, painter, roi, rgb, rect):

        if not roi:
            return

        sx = rect.width() / max(1, self.image_width)
        sy = rect.height() / max(1, self.image_height)

        x, y, w, h = roi

        painter.setPen(
            QPen(QColor(*rgb), 2)
        )

        painter.drawRect(
            QRect(
                rect.left() + int(x * sx),
                rect.top() + int(y * sy),
                int(w * sx),
                int(h * sy)
            )
        )

    def paintEvent(self, event):

        #
        # Let QLabel draw the pixmap.
        #
        super().paintEvent(event)

        rect = self.pixmap_rect()

        if rect is None:
            return

        painter = QPainter(self)

        #
        # Saved ROIs (always visible, also without tracking)
        #
        self.draw_saved_roi(
            painter,
            self.roi1,
            config.ROI1_COLOR_RGB,
            rect
        )

        self.draw_saved_roi(
            painter,
            self.roi2,
            config.ROI2_COLOR_RGB,
            rect
        )

        #
        # Temporary ROI while the user is dragging
        #
        if self.drawing:

            painter.setPen(
                QPen(QColor(255, 255, 0), 2)
            )

            painter.drawRect(
                QRect(
                    self.start_x,
                    self.start_y,
                    self.end_x - self.start_x,
                    self.end_y - self.start_y
                )
            )

        painter.end()
