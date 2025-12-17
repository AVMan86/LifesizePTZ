"""
PWM-based IR Transmitter for LifeSize Camera

Uses hardware PWM for 38kHz carrier generation with simple duty cycle control.
Python handles timing via time.sleep_us() which is sufficient when tuned for overhead.

Protocol: 16-bit pulse-distance encoding (MSB first)
- Header: 2550us mark, 2500us space
- Data: 16 bits as (device_code << 8 | command)
- Stop: 1200us mark
- Gap: 57.325ms between packets
"""

import machine
import time

from config import (
    PIN_IR_LED,
    IR_CARRIER_FREQ_HZ,
    IR_CARRIER_DUTY_U16,
    IR_HEADER_MARK_US,
    IR_HEADER_SPACE_US,
    IR_BIT_MARK_US,
    IR_BIT_0_SPACE_US,
    IR_BIT_1_SPACE_US,
    IR_STOP_MARK_US,
    IR_PACKET_GAP_US,
    LIFESIZE_DEVICE_CODE,
    DEBUG_IR,
    IRCommand,
)


class IRTransmitter:
    """
    PWM-based IR transmitter for LifeSize camera control.

    Uses hardware PWM for carrier generation with duty cycle control
    for on/off timing. Simple and reliable approach.

    Enforces the critical 57.3ms gap between frames for smooth camera movement.
    Uses absolute timing to compensate for processing delays - if one gap is
    longer due to VISCA processing, the next gap will be shorter to catch up.
    """

    def __init__(self, pin_num=PIN_IR_LED):
        self.pin_num = pin_num
        self.pwm = None
        # Absolute timing: when the next frame should start
        # Using absolute time prevents delay accumulation
        self.next_frame_time_us = 0
        # Also track last frame end for scheduler's ready check
        self.last_frame_end_us = 0
        self._init_pwm()

        if DEBUG_IR:
            print(f"IR TX: Initialized on GPIO {pin_num}")
            print(f"IR TX: Carrier {IR_CARRIER_FREQ_HZ}Hz, gap {IR_PACKET_GAP_US}us")

    def _init_pwm(self):
        """Initialize PWM on the IR LED pin."""
        self.pwm = machine.PWM(machine.Pin(self.pin_num))
        self.pwm.freq(IR_CARRIER_FREQ_HZ)
        self.pwm.duty_u16(0)  # Start with carrier off

    def _carrier_on(self):
        """Turn on the 38kHz carrier."""
        self.pwm.duty_u16(IR_CARRIER_DUTY_U16)

    def _carrier_off(self):
        """Turn off the carrier (pin low)."""
        self.pwm.duty_u16(0)

    def _wait_for_gap(self):
        """
        Wait if needed to maintain the 57.3ms timing cadence.

        Uses ABSOLUTE timing rather than relative timing. This means if one
        gap ends up longer (due to VISCA processing), the next gap will be
        shorter to compensate, maintaining the average 57.3ms cadence.

        This is critical for smooth camera movement - the camera's acceleration
        expects consistent timing like the original remote provides.
        """
        if self.next_frame_time_us == 0:
            return  # First frame, no wait needed

        now = time.ticks_us()
        wait_time = time.ticks_diff(self.next_frame_time_us, now)

        if wait_time > 0:
            # Need to wait - we're early (good!)
            time.sleep_us(wait_time)
        # If wait_time <= 0, we're late - send immediately, next gap compensates

    def _send_packet(self, code: int):
        """
        Send a single IR packet with proper gap timing.

        Waits for the scheduled time if needed, then sends the packet.
        Uses absolute timing - next frame time is calculated from the
        previous scheduled time, not from when we actually sent.

        Args:
            code: 16-bit code (device << 8 | command)
        """
        # Wait for scheduled time if needed
        self._wait_for_gap()

        # Record frame start for absolute timing calculation
        frame_start = time.ticks_us()

        # 1. Header pulse
        self._carrier_on()
        time.sleep_us(IR_HEADER_MARK_US)
        self._carrier_off()
        time.sleep_us(IR_HEADER_SPACE_US)

        # 2. Data bits (16 bits, MSB first)
        for i in range(15, -1, -1):
            bit = (code >> i) & 1

            # Mark (carrier on)
            self._carrier_on()
            time.sleep_us(IR_BIT_MARK_US)
            self._carrier_off()

            # Space (carrier off) - duration depends on bit value
            if bit == 1:
                time.sleep_us(IR_BIT_1_SPACE_US)
            else:
                time.sleep_us(IR_BIT_0_SPACE_US)

        # 3. Stop bit (mark only)
        self._carrier_on()
        time.sleep_us(IR_STOP_MARK_US)
        self._carrier_off()

        # Record when this frame ended (for scheduler's ready check)
        self.last_frame_end_us = time.ticks_us()

        # Calculate next frame time using ABSOLUTE timing
        # If this was the first frame, base it on when we actually started
        # Otherwise, base it on when we SHOULD have started (maintains cadence)
        if self.next_frame_time_us == 0:
            # First frame - schedule next based on actual start
            self.next_frame_time_us = time.ticks_add(frame_start, IR_PACKET_GAP_US)
        else:
            # Subsequent frames - maintain absolute cadence
            # Schedule next frame 57.3ms after the SCHEDULED time, not actual
            self.next_frame_time_us = time.ticks_add(self.next_frame_time_us, IR_PACKET_GAP_US)

    def _build_code(self, command: int) -> int:
        """Build the 16-bit code from device code and command."""
        return (LIFESIZE_DEVICE_CODE << 8) | (command & 0xFF)

    def transmit_command(self, command_code: int, repeats: int = 1):
        """
        Transmit an IR command with optional repeats.

        The 57.3ms gap between frames is automatically enforced by _send_packet().

        Args:
            command_code: 8-bit command code (e.g., 0x15 for UP)
            repeats: Number of times to send the packet (default 1)
        """
        code = self._build_code(command_code)

        if DEBUG_IR:
            print(f"IR TX: Sending cmd 0x{command_code:02X} as 0x{code:04X} x{repeats}")

        start_time = time.ticks_us()

        for _ in range(repeats):
            self._send_packet(code)  # Gap is enforced automatically

        if DEBUG_IR:
            elapsed = time.ticks_diff(time.ticks_us(), start_time)
            print(f"IR TX: Complete ({elapsed}us)")

    def send_continuous(self, command_code: int):
        """
        Send a single packet for continuous movement.
        Called repeatedly by the movement controller.
        """
        code = self._build_code(command_code)
        self._send_packet(code)

    def stop(self):
        """Ensure carrier is off and reset frame timing."""
        self._carrier_off()
        self.last_frame_end_us = 0
        self.next_frame_time_us = 0  # Reset so next command starts immediately

    def reset_timing(self):
        """Reset frame timing so next frame starts without gap delay."""
        self.last_frame_end_us = 0
        self.next_frame_time_us = 0

    def deinit(self):
        """Clean up PWM resources."""
        if self.pwm:
            self.pwm.deinit()
            self.pwm = None

    def test_carrier(self, duration_ms: int = 100):
        """Test carrier generation for specified duration."""
        print(f"IR TX: Testing carrier for {duration_ms}ms")
        self._carrier_on()
        time.sleep_ms(duration_ms)
        self._carrier_off()
        print("IR TX: Carrier test complete")

    def test_command(self, command_code: int, repeats: int = 3):
        """Test transmitting a command with standard repeats and 57.3ms gap."""
        cmd_name = None
        for name in dir(IRCommand):
            if not name.startswith('_') and getattr(IRCommand, name) == command_code:
                cmd_name = name
                break

        print(f"IR TX: Testing {cmd_name or hex(command_code)} x{repeats}")

        code = self._build_code(command_code)

        for _ in range(repeats):
            self._send_packet(code)  # Gap is enforced automatically

        print("IR TX: Test complete")


# =============================================================================
# Module-level convenience functions
# =============================================================================

_transmitter = None


def get_transmitter() -> IRTransmitter:
    """Get or create the default IR transmitter instance."""
    global _transmitter
    if _transmitter is None:
        _transmitter = IRTransmitter()
    return _transmitter


def send_command(command_code: int, repeats: int = 1):
    """Convenience function to send a command."""
    tx = get_transmitter()
    tx.transmit_command(command_code, repeats)


# =============================================================================
# Test code
# =============================================================================

if __name__ == "__main__":
    print("IR Transmitter Test")
    print("=" * 50)

    tx = IRTransmitter()

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
        ("OK", IRCommand.OK),
    ]

    try:
        for name, cmd in commands:
            print(f"\nSending {name}...")
            tx.test_command(cmd, repeats=3)
            time.sleep(1)

    except KeyboardInterrupt:
        print("\nTest stopped")

    tx.deinit()
    print("\nTest complete")
