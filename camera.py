# camera.py

import PySpin

import config


class SpinnakerCamera:

    def __init__(self):

        self.system = None
        self.cam = None
        self.cam_list = None

        self.fps = None

    def initialize(
        self,
        fps=config.CAMERA_FPS,
        exposure_us=config.EXPOSURE_US,
        gain=config.GAIN
    ):

        if self.cam is not None:
            raise RuntimeError(
                "Camera already initialized"
            )

        try:

            self.system = PySpin.System.GetInstance()

            self.cam_list = self.system.GetCameras()

            if self.cam_list.GetSize() == 0:

                raise RuntimeError(
                    "No FLIR camera detected"
                )

            self.cam = self.cam_list[0]

            self.cam.Init()

            #
            # Continuous acquisition, free running
            #

            self.cam.AcquisitionMode.SetValue(
                PySpin.AcquisitionMode_Continuous
            )

            if self.cam.TriggerMode.GetAccessMode() == PySpin.RW:

                self.cam.TriggerMode.SetValue(
                    PySpin.TriggerMode_Off
                )

            #
            # Disable auto settings
            #

            self.cam.ExposureAuto.SetValue(
                PySpin.ExposureAuto_Off
            )

            self.cam.GainAuto.SetValue(
                PySpin.GainAuto_Off
            )

            #
            # User settings
            #

            self.cam.ExposureTime.SetValue(
                exposure_us
            )

            self.cam.Gain.SetValue(
                gain
            )

            #
            # Frame rate
            #

            self.enable_manual_frame_rate()

            self.set_fps(fps)

            #
            # Start acquisition
            #

            self.cam.BeginAcquisition()

        except Exception:

            self.close()

            raise

        print(
            f"Camera initialized ({self.fps:.1f} FPS)"
        )

    # =====================================================
    # LIVE SETTINGS (safe while streaming)
    #
    # Each returns the value the camera actually accepted
    # (clamped to the camera's current limits).
    # =====================================================

    @staticmethod
    def set_node_value(node, value):

        value = min(
            max(value, node.GetMin()),
            node.GetMax()
        )

        node.SetValue(value)

        return node.GetValue()

    def set_exposure(self, exposure_us):

        return self.set_node_value(
            self.cam.ExposureTime,
            exposure_us
        )

    def set_gain(self, gain):

        return self.set_node_value(
            self.cam.Gain,
            gain
        )

    def enable_manual_frame_rate(self):
        """
        Make AcquisitionFrameRate writable.

        The node names differ by model:
          Blackfly S etc.: AcquisitionFrameRateEnable
          Grasshopper3   : AcquisitionFrameRateEnabled (+ FrameRateAuto)
        """

        nodemap = self.cam.GetNodeMap()

        for name in (
            "AcquisitionFrameRateEnable",
            "AcquisitionFrameRateEnabled"
        ):

            node = PySpin.CBooleanPtr(
                nodemap.GetNode(name)
            )

            if node.IsValid() and PySpin.IsWritable(node):

                node.SetValue(True)

                break

        auto = PySpin.CEnumerationPtr(
            nodemap.GetNode("AcquisitionFrameRateAuto")
        )

        if auto.IsValid() and PySpin.IsWritable(auto):

            auto.SetIntValue(
                auto.GetEntryByName("Off").GetValue()
            )

    def set_fps(self, fps):

        self.set_node_value(
            self.cam.AcquisitionFrameRate,
            fps
        )

        #
        # Not every model has AcquisitionResultingFrameRate
        #
        node = PySpin.CFloatPtr(
            self.cam.GetNodeMap().GetNode(
                "AcquisitionResultingFrameRate"
            )
        )

        if not node.IsValid():

            node = self.cam.AcquisitionFrameRate

        self.fps = node.GetValue()

        return self.fps

    def get_frame(self):
        """
        Returns an independent numpy array, or None on timeout /
        incomplete image.
        """

        try:

            image = self.cam.GetNextImage(
                config.CAMERA_GRAB_TIMEOUT_MS
            )

        except PySpin.SpinnakerException:

            return None

        try:

            if image.IsIncomplete():

                return None

            #
            # Copy: the buffer is reused after Release()
            #
            return image.GetNDArray().copy()

        finally:

            image.Release()

    def close(self):

        if self.cam is not None:

            try:

                if self.cam.IsStreaming():

                    self.cam.EndAcquisition()

                self.cam.DeInit()

            except Exception as e:

                print(f"Camera close error: {e}")

        #
        # Spinnaker requires every reference to be dropped
        # before ReleaseInstance()
        #
        self.cam = None

        if self.cam_list is not None:

            self.cam_list.Clear()

            self.cam_list = None

        if self.system is not None:

            self.system.ReleaseInstance()

            self.system = None
