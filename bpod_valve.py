# bpod_valve.py
#
# Pure-Python (pyserial) control of the Bpod state machine valve.
# Replaces MATLAB + Arduino TTL: Python tells the Bpod to open a valve
# for N ms, and the BPOD ITSELF times the pulse (a one-state state
# machine: valve ON -> state timer -> exit), so the valve closes on time
# even if this program stalls or crashes.
#
# The wire protocol follows Bpod_Gen2 (BpodObject/Connect2BpodSM.m,
# SetupHardware.m, SendStateMachine.m, RunStateMachine.m), firmware v22+,
# state machine r0.7 / r2 / r2+.

import struct
import threading
import time

import serial
import serial.tools.list_ports

import config

TEENSY_VID = 0x16C0

# Trial / event protocol
EXIT_EVENT = 255


class BpodError(RuntimeError):
    pass


# =====================================================
# STATE MACHINE ENCODING (one state, valve on, Tup -> exit)
# =====================================================

def build_valve_state_machine(
    duration_s,
    valve_channel,
    machine_type,
    firmware,
    cycle_frequency,
    n_global_timers
):
    """
    Returns the bytes for the 'C' (load state machine) command.

    valve_channel: 0-based index of the valve in the hardware's output
    channel list. Mirrors SendStateMachine.m for nStates = 1 with no
    global timers, counters or conditions.
    """

    n_states = 1

    # Output matrix for the one state: [nDifferences, channel, value];
    # 16-bit entries on state machine r2+ (machine type 4)
    output = [1, valve_channel, 1]

    if machine_type == 4:
        output_bytes = struct.pack(f"<{len(output)}H", *output)
    else:
        output_bytes = bytes(output)

    eight_bit = bytes([
        n_states,   # nStates
        0,          # global timers used
        0,          # global counters used
        0,          # conditions used
        1,          # state timer matrix: Tup -> exit (= nStates)
        0,          # input matrix: no input transitions
    ])

    eight_bit += output_bytes

    eight_bit += bytes([
        0,          # global timer start matrix
        0,          # global timer end matrix
        0,          # global counter matrix
        0,          # condition matrix
        0,          # global counter resets
    ])

    if machine_type == 4:

        eight_bit += bytes([
            0,      # analog threshold enable
            0       # analog threshold disable
        ])

    # Virtual outputs (global timer trigger / cancel), per state, with
    # a width that depends on the number of global timers
    if n_global_timers > 16:
        width = 4
    elif n_global_timers > 8:
        width = 2
    else:
        width = 1

    global_timer_matrix = bytes(2 * n_states * width)

    # State timer, in state machine cycles
    thirty_two_bit = struct.pack(
        "<I",
        int(duration_s * cycle_frequency)
    )

    body = eight_bit + global_timer_matrix + thirty_two_bit

    if firmware > 22:

        body += bytes([0])      # final additional ops: none

    run_asap = 0
    use_255_back_signal = 0

    return (
        b"C"
        + bytes([run_asap, use_255_back_signal])
        + struct.pack("<H", len(body))
        + body
    )


# =====================================================
# DEVICE
# =====================================================

class BpodValve:

    def __init__(
        self,
        port=config.BPOD_PORT,
        valve=config.BPOD_VALVE,
        open_ms=config.VALVE_OPEN_MS,
        callback=None
    ):
        """
        callback(event_name, details), if given, is called FROM THE
        WORKER THREAD when a pulse finishes ("ValveOpened") or fails
        ("ValveError"). Use a Qt signal to hop to the GUI thread.
        """

        self.callback = callback

        self.ser = None

        self.open_ms = open_ms

        self.busy = False

        self.thread = None

        self.last_result = None

        self.io_lock = threading.Lock()

        # Set to abort the running state machine (Stop Flush)
        self.abort_event = threading.Event()

        self.flushing = False

        self.connect(port)

        self.read_hardware()

        self.set_valve(valve)

    # -------------------------------------------------
    # CONNECTION
    # -------------------------------------------------

    @staticmethod
    def candidate_ports(port):

        if port and port != "AUTO":

            return [port]

        # Bpod state machines are Teensy boards (r1: Arduino Due)
        ports = [
            p.device
            for p in serial.tools.list_ports.comports()
            if p.vid == TEENSY_VID
        ]

        return ports

    @staticmethod
    def handshake(ser):
        """
        Same sequence as Connect2BpodSM.m (known-port path).
        """

        ser.write(b"XZ6")

        time.sleep(0.5)

        ser.reset_input_buffer()

        ser.write(b"6")

        return ser.read(1) == b"5"

    def connect(self, port):

        candidates = self.candidate_ports(port)

        if not candidates:

            raise BpodError(
                "No Bpod found (no Teensy USB serial port). "
                "Is it plugged in and powered?"
            )

        errors = []

        for name in candidates:

            try:

                ser = serial.Serial(
                    name,
                    12000000,
                    timeout=1,
                    write_timeout=2
                )

            except serial.SerialException as e:

                errors.append(f"{name}: {e}")

                continue

            if self.handshake(ser):

                self.ser = ser

                self.port = name

                return

            ser.close()

            errors.append(f"{name}: no Bpod handshake")

        raise BpodError(
            "Could not connect to the Bpod state machine.\n"
            + "\n".join(errors)
            + "\nIf MATLAB / Bpod console is open it holds the port; "
            "close it first."
        )

    def read_exact(self, n, timeout=2.0):

        deadline = time.time() + timeout

        data = b""

        while len(data) < n:

            chunk = self.ser.read(n - len(data))

            data += chunk

            if not chunk and time.time() > deadline:

                raise BpodError(
                    f"Bpod timeout: wanted {n} bytes, got {len(data)}"
                )

        return data

    def read_hardware(self):
        """
        Firmware / model / channel layout (SetupHardware.m).
        """

        self.ser.write(b"F")

        self.firmware, self.machine_type = struct.unpack(
            "<HH",
            self.read_exact(4)
        )

        if self.firmware < 22 or self.machine_type not in (2, 3, 4):

            raise BpodError(
                f"Unsupported Bpod (firmware v{self.firmware}, "
                f"machine type {self.machine_type}); need firmware v22+ "
                "on state machine r0.7 / r2 / r2+."
            )

        self.ser.write(b"H")

        self.max_states, cycle_period = struct.unpack(
            "<HH",
            self.read_exact(4)
        )

        self.cycle_period_us = cycle_period

        self.cycle_frequency = 1000000.0 / cycle_period

        self.read_exact(1)                      # max serial events

        if self.firmware > 22:

            self.read_exact(1)                  # max bytes per serial msg

        (
            self.n_global_timers,
            n_global_counters,
            n_conditions,
            n_inputs
        ) = self.read_exact(4)

        self.inputs = self.read_exact(n_inputs).decode("latin-1")

        n_outputs = self.read_exact(1)[0]

        self.outputs = self.read_exact(n_outputs).decode("latin-1")

        # Event stream: with live timestamps each event message carries
        # a 4-byte timestamp
        self.ser.write(b"G")

        self.live_timestamps = self.read_exact(1)[0]

    def set_valve(self, valve):

        valves = [
            i for i, c in enumerate(self.outputs) if c == "V"
        ]

        if not (1 <= valve <= len(valves)):

            raise BpodError(
                f"Valve {valve} does not exist; this Bpod has "
                f"{len(valves)} valves."
            )

        self.valve = valve

        self.valve_channel = valves[valve - 1]

    def describe(self):

        names = {2: "r0.7-1.0", 3: "r2", 4: "r2+"}

        return (
            f"Bpod {names[self.machine_type]} on {self.port}, "
            f"firmware v{self.firmware}, {self.outputs.count('V')} valves, "
            f"cycle {self.cycle_period_us} us"
        )

    # -------------------------------------------------
    # REWARD
    # -------------------------------------------------

    def run_pulse(self, duration_s):
        """
        Blocking: load the one-state machine, run it, and read the
        events until the exit. Returns the Bpod-measured duration (s).
        """

        packet = build_valve_state_machine(
            duration_s,
            self.valve_channel,
            self.machine_type,
            self.firmware,
            self.cycle_frequency,
            self.n_global_timers
        )

        with self.io_lock:

            self.ser.reset_input_buffer()

            self.ser.write(packet)

            self.ser.write(b"R")

            if self.read_exact(1)[0] != 1:

                raise BpodError(
                    "Bpod did not acknowledge the state machine"
                )

            start_us = struct.unpack("<Q", self.read_exact(8))[0]

            deadline = time.time() + duration_s + 3

            done = False

            while not done:

                if self.abort_event.is_set():

                    # Abort ends the state machine, which closes the valve
                    self.ser.write(b"X")

                    time.sleep(0.2)

                    self.ser.reset_input_buffer()

                    return None

                if time.time() > deadline:

                    # Abort the trial rather than leave it running
                    self.ser.write(b"X")

                    raise BpodError(
                        "Bpod trial did not finish (aborted)"
                    )

                if self.ser.in_waiting < 2:

                    time.sleep(0.001)

                    continue

                op, count = self.read_exact(2)

                if op == 1:

                    size = count + (4 if self.live_timestamps else 0)

                    events = self.read_exact(size)[:count]

                    done = EXIT_EVENT in events

                elif op == 2:

                    pass        # soft code, nothing to read

                else:

                    raise BpodError(f"Unexpected Bpod op code {op}")

            trailer = self.read_exact(12)

            end_us = struct.unpack("<Q", trailer[4:12])[0]

        return (end_us - start_us) / 1e6

    def notify(self, event, details):

        if self.callback is not None:

            try:

                self.callback(event, details)

            except Exception as e:

                print(f"Valve callback error: {e}")

    def worker(self, duration_s):

        try:

            actual = self.run_pulse(duration_s)

            self.last_result = {
                "requested_s": duration_s,
                "actual_s": actual
            }

            print(
                f"Valve {self.valve} opened {actual * 1000:.1f} ms "
                f"(requested {duration_s * 1000:.0f} ms)"
            )

            self.notify(
                "ValveOpened",
                f"valve={self.valve}, "
                f"requested_ms={duration_s * 1000:.0f}, "
                f"actual_ms={actual * 1000:.1f}"
            )

        except Exception as e:

            self.last_result = {"error": str(e)}

            print(f"Valve pulse failed: {e}")

            self.notify(
                "ValveError",
                str(e)
            )

        finally:

            self.busy = False

    def pulse(self, duration_ms=None):
        """
        Non-blocking. Ignored (returns False) while a pulse is running.
        """

        if self.busy:

            print("Valve pulse ignored (previous pulse still running)")

            return False

        if duration_ms is None:

            duration_ms = self.open_ms

        self.busy = True

        self.abort_event.clear()

        self.thread = threading.Thread(
            target=self.worker,
            args=(duration_ms / 1000.0,),
            daemon=True
        )

        self.thread.start()

        return True

    # -------------------------------------------------
    # CALIBRATION / FLUSH
    # -------------------------------------------------

    def calibrate_worker(self, n_pulses, duration_s, gap_s):

        try:

            for i in range(n_pulses):

                if self.abort_event.is_set():

                    break

                self.run_pulse(duration_s)

                if i < n_pulses - 1:

                    time.sleep(gap_s)

            print(
                f"Valve {self.valve} calibration done: {n_pulses} x "
                f"{duration_s * 1000:.0f} ms"
            )

            self.notify(
                "ValveCalibrated",
                f"valve={self.valve}, pulses={n_pulses}, "
                f"open_ms={duration_s * 1000:.0f}"
            )

        except Exception as e:

            print(f"Valve calibration failed: {e}")

            self.notify("ValveError", str(e))

        finally:

            self.busy = False

    def calibrate(
        self,
        n_pulses=config.CALIBRATE_PULSES,
        duration_ms=None,
        gap_ms=config.CALIBRATE_GAP_MS
    ):
        """
        Non-blocking: open the valve n_pulses times. Returns False if
        the valve is busy.
        """

        if self.busy:

            return False

        if duration_ms is None:

            duration_ms = self.open_ms

        self.busy = True

        self.abort_event.clear()

        self.thread = threading.Thread(
            target=self.calibrate_worker,
            args=(n_pulses, duration_ms / 1000.0, gap_ms / 1000.0),
            daemon=True
        )

        self.thread.start()

        return True

    def flush_worker(self):

        try:

            self.run_pulse(config.FLUSH_MAX_S)

            self.notify("ValveFlushEnded", f"valve={self.valve}")

        except Exception as e:

            print(f"Valve flush failed: {e}")

            self.notify("ValveError", str(e))

        finally:

            self.flushing = False

            self.busy = False

    def start_flush(self):
        """
        Non-blocking: hold the valve open until stop_flush() (or
        FLUSH_MAX_S, timed by the Bpod). Returns False if busy.
        """

        if self.busy:

            return False

        self.busy = True

        self.flushing = True

        self.abort_event.clear()

        self.thread = threading.Thread(
            target=self.flush_worker,
            daemon=True
        )

        self.thread.start()

        return True

    def stop_flush(self):

        self.abort_event.set()

    def close(self):

        self.abort_event.set()

        try:

            if self.thread is not None:

                self.thread.join(timeout=5)

            if self.ser is not None:

                self.ser.write(b"Z")

                self.ser.close()

                self.ser = None

                print("Bpod closed")

        except Exception as e:

            print(f"Bpod close error: {e}")
