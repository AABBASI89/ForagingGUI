from PyQt5.QtCore import QThread
import queue

import config


class RecorderThread(QThread):

    def __init__(
        self,
        writer,
        max_queue=config.RECORDER_MAX_QUEUE
    ):

        super().__init__()

        self.writer = writer

        self.queue = queue.Queue(
            maxsize=max_queue
        )

        self.running = True

        self.dropped = 0

        self.written = 0

    def add_frame(self, frame):
        """
        Thread-safe. The caller must not modify `frame` afterwards.
        """

        try:

            self.queue.put_nowait(
                frame
            )

        except queue.Full:

            self.dropped += 1

    def run(self):

        #
        # Keep going until stopped AND the queue is drained
        #
        while self.running or not self.queue.empty():

            try:

                frame = self.queue.get(
                    timeout=0.1
                )

            except queue.Empty:

                continue

            self.writer.write(frame)

            self.written += 1

    def stop(self):

        self.running = False

        self.wait()

        self.writer.release()

        if self.dropped:

            print(
                f"Recorder dropped {self.dropped} frames "
                f"(wrote {self.written})"
            )
