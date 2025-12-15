"""
PIO-based IR Transmitter for LifeSize Camera

Uses a PIO state machine to generate the complete IR waveform with precise timing.
All timing is hardware-controlled - Python just feeds data to the FIFO.

The PIO reads mark/space duration pairs from FIFO and generates:
- 38kHz carrier during mark periods
- Pin low during space periods
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
# PIO Program - IR Transmitter with 38kHz carrier
# =============================================================================

@asm_pio(set_init=PIO.OUT_LOW)
def ir_tx_pio():
    """
    Generate IR waveform with 38kHz carrier.

    Input format: 32-bit words with mark_cycles (lower 16) and space_cycles (upper 16)
    Each cycle unit = 1 carrier period (~26.3us at 38kHz)

    PIO runs at 38kHz * 19 = 722kHz (19 cycles per carrier period)
    - Total cycle: 19 PIO clocks
    - High time: 6 cycles (~32% duty)
    - Low time: 13 cycles

    For a 560us mark: 560us / 26.3us = ~21 carrier cycles
    For a 1680us space: 1680us / 26.3us = ~64 carrier cycles
    """
    # Main loop - get data and generate waveform
    wrap_target()

    # Explicitly pull next word from FIFO (blocks if empty)
    pull(block)

    # Get mark duration (lower 16 bits shifted out first) into X
    out(x, 16)

    # Get space duration (upper 16 bits) into Y
    out(y, 16)

    # Generate carrier burst for X cycles
    # Loop structure: 1 + 6 + 11 + 1 = 19 PIO cycles per carrier period
    label("mark_loop")
    jmp(not_x, "space_start")      # 1 cycle: If X=0, go to space
    set(pins, 1)            [5]    # 6 cycles: High
    set(pins, 0)            [10]   # 11 cycles: Low
    jmp(x_dec, "mark_loop")        # 1 cycle: Decrement X and loop

    # Space period - keep pin low for Y carrier-cycle-equivalents
    label("space_start")
    set(pins, 0)                   # Ensure pin is low
    label("space_loop")
    jmp(not_y, "next_word")        # 1 cycle: If Y=0, get next word
    nop()                   [16]   # 17 cycles: Delay
    jmp(y_dec, "space_loop")       # 1 cycle: Decrement Y, total 19

    label("next_word")
    # wrap() will jump back to wrap_target() for next word
    wrap()


# =============================================================================
# IR Transmitter Class
# =============================================================================

class IRTransmitter:
    """
    IR transmitter using PIO for precise timing.

    All timing is hardware-controlled. Python just packs timing data
    and feeds it to the PIO FIFO.
    """

    # Carrier period in microseconds
    CARRIER_PERIOD_US = 1_000_000 / IR_CARRIER_FREQ_HZ  # ~26.3us

    def __init__(self, pin_num=PIN_IR_LED, sm_num=0):
        self.pin = Pin(pin_num, Pin.OUT, value=0)
        self.pin_num = pin_num
        self.sm_num = sm_num
        self.sm = None

        self._init_pio()

        if DEBUG_IR:
            print(f"IR TX PIO: Initialized on GPIO {pin_num}")

    def _init_pio(self):
        """Initialize the PIO state machine."""
        # PIO frequency for 38kHz carrier with 19 cycles per period
        pio_freq = IR_CARRIER_FREQ_HZ * 19  # 722000 Hz

        self.sm = StateMachine(
            self.sm_num,
            ir_tx_pio,
            freq=pio_freq,
            set_base=self.pin,
        )

        if DEBUG_IR:
            print(f"IR TX PIO: SM{self.sm_num} at {pio_freq}Hz")
            actual_carrier = pio_freq / 19
            print(f"IR TX PIO: Carrier = {actual_carrier/1000:.2f}kHz")

    def _us_to_cycles(self, us: int) -> int:
        """Convert microseconds to carrier cycles."""
        cycles = int(us / self.CARRIER_PERIOD_US)
        return max(1, cycles)  # At least 1 cycle

    def _pack_timing(self, mark_us: int, space_us: int) -> int:
        """Pack mark/space timing into a 32-bit word.

        PIO OUT instruction shifts from LSB side, so:
        - Lower 16 bits go to X (mark cycles)
        - Upper 16 bits go to Y (space cycles)
        """
        mark_cycles = self._us_to_cycles(mark_us)
        space_cycles = self._us_to_cycles(space_us) if space_us > 0 else 0

        # Lower 16 bits = mark (shifted to X first), upper 16 bits = space (shifted to Y)
        return (space_cycles << 16) | (mark_cycles & 0xFFFF)

    def transmit_command(self, command_code: int):
        """Transmit a complete IR command."""
        if DEBUG_IR:
            print(f"IR TX: Sending 0x{command_code:02X}")

        start_time = time.ticks_us()

        # Get timing sequence from protocol encoder
        timings = protocol.encode_command(command_code)

        # Pack all timing data
        packed_data = []
        for mark_us, space_us in timings:
            packed_data.append(self._pack_timing(mark_us, space_us))

        if DEBUG_IR:
            print(f"IR TX: {len(packed_data)} words to send")

        # Ensure pin starts low and SM is stopped
        self.sm.active(0)
        self.pin.value(0)

        # Pre-fill FIFO with first words BEFORE activating (FIFO depth is 4)
        prefill_count = min(4, len(packed_data))
        for i in range(prefill_count):
            self.sm.put(packed_data[i])

        if DEBUG_IR:
            print(f"IR TX: Pre-filled {prefill_count} words, activating SM")

        # Now activate state machine - it will start processing immediately
        self.sm.active(1)

        try:
            # Feed remaining data as FIFO drains
            for i in range(prefill_count, len(packed_data)):
                self.sm.put(packed_data[i])

            # Wait for transmission to complete
            # Calculate expected duration
            total_us = sum(mark + space for mark, space in timings)
            time.sleep_us(total_us + 1000)  # Add 1ms margin

        finally:
            # Stop state machine and ensure pin is low
            self.sm.active(0)
            self.pin.value(0)

        if DEBUG_IR:
            elapsed = time.ticks_diff(time.ticks_us(), start_time)
            print(f"IR TX: Frame complete ({elapsed}us)")

    def test_carrier(self, duration_ms: int = 100):
        """Test carrier generation for specified duration."""
        print(f"IR TX: Testing carrier for {duration_ms}ms")

        # Pack a single long mark with no space
        cycles = int((duration_ms * 1000) / self.CARRIER_PERIOD_US)
        word = (cycles << 16) | 0  # All mark, no space

        self.sm.active(1)
        self.sm.put(word)
        time.sleep_ms(duration_ms + 10)
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
# Simple PIO Carrier + Software Timing (Alternative approach)
# =============================================================================

@asm_pio(set_init=PIO.OUT_LOW)
def ir_carrier_simple():
    """
    Generate continuous 38kHz carrier.
    Enabled/disabled by Python for mark/space timing.
    """
    wrap_target()
    set(pins, 1)    [6]     # 7 cycles high
    set(pins, 0)    [11]    # 12 cycles low
    wrap()


class IRTransmitterSimple:
    """
    Simpler IR transmitter: PIO generates carrier, Python controls timing.

    Uses interrupt disable for more consistent timing.
    """

    def __init__(self, pin_num=PIN_IR_LED, sm_num=0):
        self.pin = Pin(pin_num, Pin.OUT, value=0)
        self.pin_num = pin_num
        self.sm_num = sm_num

        pio_freq = IR_CARRIER_FREQ_HZ * 19
        self.sm = StateMachine(
            self.sm_num,
            ir_carrier_simple,
            freq=pio_freq,
            set_base=self.pin,
        )

        if DEBUG_IR:
            print(f"IR TX Simple: Initialized on GPIO {pin_num}")

    def _transmit_frame(self, timings):
        """Transmit frame with interrupts disabled for consistent timing."""
        import machine

        sm = self.sm
        pin = self.pin

        # Disable interrupts for consistent timing
        irq_state = machine.disable_irq()

        try:
            for mark_us, space_us in timings:
                # Mark: enable carrier
                sm.active(1)
                time.sleep_us(mark_us)
                sm.active(0)
                pin.value(0)

                # Space: keep low
                if space_us > 0:
                    time.sleep_us(space_us)
        finally:
            machine.enable_irq(irq_state)
            sm.active(0)
            pin.value(0)

    def transmit_command(self, command_code: int):
        """Transmit a complete IR command."""
        if DEBUG_IR:
            print(f"IR TX: Sending 0x{command_code:02X}")

        start_time = time.ticks_us()
        timings = protocol.encode_command(command_code)

        self._transmit_frame(timings)

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


def get_transmitter(mode: str = "pio"):
    """
    Get or create the default IR transmitter instance.

    Args:
        mode: "pio" for full PIO control (default, most precise)
              "simple" for PIO carrier + software timing
              "software" for pure software bit-banging
    """
    global _transmitter
    if _transmitter is None:
        if mode == "pio":
            try:
                _transmitter = IRTransmitter()
                print("IR TX: Using PIO-controlled transmitter")
            except Exception as e:
                print(f"PIO init failed: {e}")
                _transmitter = IRTransmitterSimple()
        elif mode == "simple":
            _transmitter = IRTransmitterSimple()
            print("IR TX: Using PIO carrier + software timing")
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
    tx = get_transmitter(mode="pio")

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
