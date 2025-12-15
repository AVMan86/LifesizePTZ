"""
PIO-based IR Transmitter for LifeSize Camera

Uses a PIO state machine to generate precise 38kHz carrier.
The carrier runs continuously when the state machine is active,
and mark/space timing is controlled by enabling/disabling the SM.

This approach avoids FIFO blocking issues by not feeding data to the PIO.
"""

import rp2
from rp2 import PIO, StateMachine, asm_pio
from machine import Pin
import time
import micropython

from config import (
    PIN_IR_LED,
    IR_CARRIER_FREQ_HZ,
    DEBUG_IR,
    DEBUG_TIMING,
    IRCommand,
)
from ir_protocol import protocol


# =============================================================================
# PIO Program - Simple 38kHz carrier generator
# =============================================================================

@asm_pio(set_init=PIO.OUT_LOW)
def ir_carrier():
    """
    Generate continuous 38kHz carrier with ~33% duty cycle.

    At 38kHz, period = 26.3us
    With 33% duty: high = 8.7us, low = 17.5us

    PIO cycle calculation:
    - Carrier cycle in PIO = 19 cycles (7 high + 12 low)
    - PIO freq = 38000 Hz * 19 cycles = 722000 Hz
    - Duty cycle = 7/19 = 36.8% (close enough to 33%)
    """
    wrap_target()
    set(pins, 1)    [6]     # 7 cycles high (including instruction)
    set(pins, 0)    [11]    # 12 cycles low (including instruction)
    wrap()                   # Total: 19 cycles per carrier period


# =============================================================================
# PIO-based IR Transmitter
# =============================================================================

class IRTransmitter:
    """
    IR transmitter using PIO for precise 38kHz carrier generation.

    The PIO generates the carrier continuously when active.
    Mark/space timing is controlled by activating/deactivating the SM.
    """

    def __init__(self, pin_num=PIN_IR_LED, sm_num=0):
        self.pin = Pin(pin_num, Pin.OUT, value=0)
        self.pin_num = pin_num
        self.sm_num = sm_num
        self.sm = None

        self._init_pio()

        if DEBUG_IR:
            print(f"IR TX PIO: Initialized on GPIO {pin_num}")

    def _init_pio(self):
        """Initialize the PIO state machine for 38kHz carrier."""
        # Calculate PIO frequency for accurate 38kHz
        # Carrier cycle in PIO program = 19 cycles (7 high + 12 low)
        # PIO freq = 38000 Hz * 19 cycles = 722000 Hz
        pio_freq = IR_CARRIER_FREQ_HZ * 19

        self.sm = StateMachine(
            self.sm_num,
            ir_carrier,
            freq=pio_freq,
            set_base=self.pin,
        )

        if DEBUG_IR:
            print(f"IR TX PIO: SM{self.sm_num} at {pio_freq}Hz")
            actual_carrier = pio_freq / 19
            print(f"IR TX PIO: Carrier = {actual_carrier/1000:.2f}kHz")

    def _mark(self, duration_us: int):
        """Generate carrier burst (mark) for specified duration."""
        # Compensate for sleep_us overhead (~100us)
        adjusted = max(100, duration_us - 100)
        self.sm.active(1)
        time.sleep_us(adjusted)
        self.sm.active(0)
        self.pin.value(0)  # Ensure pin is low after stopping

    def _space(self, duration_us: int):
        """Wait with output low (space)."""
        # Compensate for sleep_us overhead (~100us)
        adjusted = max(100, duration_us - 100)
        self.pin.value(0)
        time.sleep_us(adjusted)

    def transmit_command(self, command_code: int):
        """Transmit a complete IR command."""
        if DEBUG_IR:
            print(f"IR TX: Sending 0x{command_code:02X}")

        start_time = time.ticks_us()

        # Get timing sequence from protocol encoder
        timings = protocol.encode_command(command_code)

        # Transmit each mark/space pair
        for mark_us, space_us in timings:
            self._mark(mark_us)
            if space_us > 0:
                self._space(space_us)

        self.pin.value(0)

        if DEBUG_IR:
            elapsed = time.ticks_diff(time.ticks_us(), start_time)
            print(f"IR TX: Frame complete ({elapsed}us)")

    def test_carrier(self, duration_ms: int = 100):
        """Test carrier generation for specified duration."""
        print(f"IR TX: Testing carrier for {duration_ms}ms")
        self.sm.active(1)
        time.sleep_ms(duration_ms)
        self.sm.active(0)
        self.pin.value(0)
        print("IR TX: Carrier test complete")

    def test_command(self, command_code: int, repeats: int = 1, gap_ms: int = 57):
        """Test transmitting a command with repeats."""
        cmd_name = None
        for name in dir(IRCommand):
            if not name.startswith('_') and getattr(IRCommand, name) == command_code:
                cmd_name = name
                break

        print(f"IR TX: Testing {cmd_name or hex(command_code)} x{repeats}")

        for i in range(repeats):
            self.transmit_command(command_code)
            if i < repeats - 1:
                time.sleep_ms(gap_ms)

        print("IR TX: Test complete")


# =============================================================================
# Software-based IR Transmitter (Fallback)
# =============================================================================

class IRTransmitterSoftware:
    """
    Software-based IR transmitter using bit-banging.
    Fallback if PIO doesn't work.
    """

    def __init__(self, pin_num=PIN_IR_LED):
        self.pin = Pin(pin_num, Pin.OUT, value=0)
        self.pin_num = pin_num
        if DEBUG_IR:
            print(f"IR TX Software: Initialized on GPIO {pin_num}")

    @micropython.native
    def _carrier_burst(self, duration_us: int):
        """Generate carrier burst using ticks_us timing."""
        import machine
        pin = self.pin

        irq_state = machine.disable_irq()
        try:
            end_time = time.ticks_us() + duration_us
            while time.ticks_diff(end_time, time.ticks_us()) > 0:
                pin.value(1)
                t = time.ticks_us()
                while time.ticks_diff(time.ticks_us(), t) < 8:
                    pass
                pin.value(0)
                t = time.ticks_us()
                while time.ticks_diff(time.ticks_us(), t) < 16:
                    pass
        finally:
            machine.enable_irq(irq_state)

    def _space(self, duration_us: int):
        """Wait with IR LED off."""
        self.pin.value(0)
        time.sleep_us(duration_us)

    def transmit_command(self, command_code: int):
        """Transmit a command using software timing."""
        if DEBUG_IR:
            print(f"IR TX: Sending 0x{command_code:02X}")

        start_time = time.ticks_us()
        timings = protocol.encode_command(command_code)

        for mark_us, space_us in timings:
            self._carrier_burst(mark_us)
            if space_us > 0:
                self._space(space_us)

        self.pin.value(0)

        if DEBUG_IR:
            elapsed = time.ticks_diff(time.ticks_us(), start_time)
            print(f"IR TX: Frame complete ({elapsed}us)")

    def test_command(self, command_code: int, repeats: int = 1, gap_ms: int = 57):
        """Test transmitting a command with repeats."""
        cmd_name = None
        for name in dir(IRCommand):
            if not name.startswith('_') and getattr(IRCommand, name) == command_code:
                cmd_name = name
                break

        print(f"IR TX: Testing {cmd_name or hex(command_code)} x{repeats}")

        for i in range(repeats):
            self.transmit_command(command_code)
            if i < repeats - 1:
                time.sleep_ms(gap_ms)

        print("IR TX: Test complete")


# =============================================================================
# Module-level transmitter instance
# =============================================================================

_transmitter = None


def get_transmitter(use_pio: bool = True):
    """
    Get or create the default IR transmitter instance.

    Args:
        use_pio: If True (default), use PIO-based transmitter for precise timing.
                 If False, use software bit-banging fallback.
    """
    global _transmitter
    if _transmitter is None:
        if use_pio:
            try:
                _transmitter = IRTransmitter()
                print("IR TX: Using PIO-based transmitter")
            except Exception as e:
                print(f"PIO init failed, using software: {e}")
                _transmitter = IRTransmitterSoftware()
        else:
            print("IR TX: Using software bit-bang transmitter")
            _transmitter = IRTransmitterSoftware()
    return _transmitter


def send_command(command_code: int):
    """Convenience function to send a single command."""
    tx = get_transmitter()
    tx.transmit_command(command_code)


# =============================================================================
# Test code
# =============================================================================

if __name__ == "__main__":
    print("IR Transmitter Test")
    print("=" * 50)

    # Create transmitter (will use PIO by default)
    tx = get_transmitter(use_pio=True)

    print("\nPress Ctrl+C to stop\n")

    # Test carrier first
    print("Testing carrier generation...")
    tx.test_carrier(duration_ms=50)
    time.sleep(1)

    # Test each command
    commands = [
        ("UP", IRCommand.UP),
        ("DOWN", IRCommand.DOWN),
        ("LEFT", IRCommand.LEFT),
        ("RIGHT", IRCommand.RIGHT),
        ("ZOOM_IN", IRCommand.ZOOM_IN),
        ("ZOOM_OUT", IRCommand.ZOOM_OUT),
    ]

    try:
        for name, cmd in commands:
            print(f"\nSending {name}...")
            tx.test_command(cmd, repeats=3, gap_ms=57)
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nTest stopped")

    print("\nTest complete")
