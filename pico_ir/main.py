"""
IR Pico - Dedicated IR Transmitter for LifeSize Camera

This Pico has ONE job: maintain perfect 57.3ms IR timing.
It receives simple commands over UART from the VISCA Pico.

No network code, no complex parsing - just IR timing perfection.

Power Design:
  The W5500's Link LED drives a BJT which controls a relay.
  When the PTZ controller connects via Ethernet, the link LED lights up,
  triggering the relay to power on the camera and both Picos.
  This provides hardware-level "wake on LAN" with zero standby power.

Wiring:
  - GP0 (TX) → Pico #1 GP1 (RX)
  - GP1 (RX) ← Pico #1 GP0 (TX)
  - GP15 → IR LED circuit
  - GND ↔ GND

Startup:
  On boot, waits for camera to initialize then sends OK to enable IR mode.
"""

import machine
import time
from machine import Pin, PWM, UART

from protocol import (
    Cmd, Resp, IRCode,
    UART_BAUD, UART_TX_PIN, UART_RX_PIN,
    IR_CARRIER_FREQ_HZ,
    IR_HEADER_MARK_US, IR_HEADER_SPACE_US,
    IR_BIT_MARK_US, IR_BIT_0_SPACE_US, IR_BIT_1_SPACE_US,
    IR_STOP_MARK_US, IR_PACKET_GAP_US,
    LIFESIZE_DEVICE_CODE,
)

# =============================================================================
# Pin Configuration
# =============================================================================

PIN_IR_LED = 15
PIN_LED = 25  # Onboard LED for status

# PWM duty cycle for IR carrier (50%)
IR_CARRIER_DUTY = 32768

# Startup delay before sending OK (camera boot time)
CAMERA_BOOT_DELAY_SEC = 8


# =============================================================================
# IR Transmitter
# =============================================================================

class IRTransmitter:
    """
    Hardware-level IR transmitter with precise timing.

    This is the core timing-critical code. No interruptions allowed
    during transmission - we have complete control of the CPU.
    """

    def __init__(self):
        self.pwm = PWM(Pin(PIN_IR_LED))
        self.pwm.freq(IR_CARRIER_FREQ_HZ)
        self.pwm.duty_u16(0)
        self.last_frame_end_us = 0

    def _carrier_on(self):
        self.pwm.duty_u16(IR_CARRIER_DUTY)

    def _carrier_off(self):
        self.pwm.duty_u16(0)

    def _wait_for_gap(self):
        """Wait for 57.3ms gap since last frame."""
        if self.last_frame_end_us == 0:
            return

        now = time.ticks_us()
        elapsed = time.ticks_diff(now, self.last_frame_end_us)

        if elapsed < IR_PACKET_GAP_US:
            time.sleep_us(IR_PACKET_GAP_US - elapsed)

    def send_frame(self, code: int):
        """
        Send a single IR frame with proper gap timing.

        Args:
            code: 16-bit code (device << 8 | command)
        """
        self._wait_for_gap()

        # Header
        self._carrier_on()
        time.sleep_us(IR_HEADER_MARK_US)
        self._carrier_off()
        time.sleep_us(IR_HEADER_SPACE_US)

        # Data bits (16 bits, MSB first)
        for i in range(15, -1, -1):
            bit = (code >> i) & 1
            self._carrier_on()
            time.sleep_us(IR_BIT_MARK_US)
            self._carrier_off()
            time.sleep_us(IR_BIT_1_SPACE_US if bit else IR_BIT_0_SPACE_US)

        # Stop bit
        self._carrier_on()
        time.sleep_us(IR_STOP_MARK_US)
        self._carrier_off()

        self.last_frame_end_us = time.ticks_us()

    def send_command(self, ir_code: int):
        """Send a single IR command."""
        code = (LIFESIZE_DEVICE_CODE << 8) | ir_code
        self.send_frame(code)

    def reset_timing(self):
        """Reset gap timing for immediate transmission."""
        self.last_frame_end_us = 0

    def stop(self):
        """Ensure carrier is off."""
        self._carrier_off()
        self.last_frame_end_us = 0


# =============================================================================
# Movement State Machine
# =============================================================================

class MovementController:
    """
    Manages continuous IR transmission for smooth camera movement.

    When movement is active, sends IR frames at precise 57.3ms intervals.
    No network interruptions - just pure timing.
    """

    def __init__(self, transmitter: IRTransmitter):
        self.tx = transmitter
        self.active = False
        self.commands = []  # List of IR codes to send (for diagonal)
        self.cmd_index = 0

    def start(self, ir_codes: list):
        """Start continuous movement with given IR code(s)."""
        if not ir_codes:
            return

        self.commands = ir_codes
        self.cmd_index = 0
        self.active = True
        self.tx.reset_timing()

        # Send first frame immediately
        self._send_next()

    def stop(self):
        """Stop all movement."""
        self.active = False
        self.commands = []
        self.tx.stop()

    def poll(self):
        """
        Poll for next transmission. Call this frequently!

        Returns True if a frame was sent.
        """
        if not self.active:
            return False

        # Check if it's time to send
        if self.tx.last_frame_end_us == 0:
            return False  # Already sent, waiting for gap

        now = time.ticks_us()
        elapsed = time.ticks_diff(now, self.tx.last_frame_end_us)

        if elapsed >= IR_PACKET_GAP_US:
            self._send_next()
            return True

        return False

    def _send_next(self):
        """Send the next IR frame."""
        if not self.commands:
            return

        # Get next command (alternate for diagonal movement)
        ir_code = self.commands[self.cmd_index]
        self.cmd_index = (self.cmd_index + 1) % len(self.commands)

        self.tx.send_command(ir_code)


# =============================================================================
# Command Handler
# =============================================================================

# Map serial commands to IR codes
CMD_TO_IR = {
    Cmd.START_UP: [IRCode.UP],
    Cmd.START_DOWN: [IRCode.DOWN],
    Cmd.START_LEFT: [IRCode.LEFT],
    Cmd.START_RIGHT: [IRCode.RIGHT],
    Cmd.START_ZOOM_IN: [IRCode.ZOOM_IN],
    Cmd.START_ZOOM_OUT: [IRCode.ZOOM_OUT],
    Cmd.START_UP_LEFT: [IRCode.UP, IRCode.LEFT],
    Cmd.START_UP_RIGHT: [IRCode.UP, IRCode.RIGHT],
    Cmd.START_DOWN_LEFT: [IRCode.DOWN, IRCode.LEFT],
    Cmd.START_DOWN_RIGHT: [IRCode.DOWN, IRCode.RIGHT],
}


def handle_command(cmd: int, movement: MovementController, uart: UART) -> int:
    """
    Handle a command byte from the VISCA Pico.

    Returns response byte to send back.
    """
    # Movement start commands
    if cmd in CMD_TO_IR:
        ir_codes = CMD_TO_IR[cmd]
        movement.start(ir_codes)
        return Resp.ACK

    # Stop
    if cmd == Cmd.STOP:
        movement.stop()
        return Resp.ACK

    # Single press OK
    if cmd == Cmd.PRESS_OK:
        movement.stop()
        movement.tx.reset_timing()
        for _ in range(3):  # Send 3 times for reliability
            movement.tx.send_command(IRCode.OK)
        return Resp.ACK

    # Ping
    if cmd == Cmd.PING:
        return Resp.PONG

    # Reset
    if cmd == Cmd.RESET:
        movement.stop()
        return Resp.ACK

    # Unknown command
    return Resp.ERROR


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 50)
    print("  IR Pico - LifeSize Camera Controller")
    print("  Dedicated IR Transmitter")
    print("=" * 50)

    # Initialize hardware
    led = Pin(PIN_LED, Pin.OUT)

    # Initialize UART for communication with VISCA Pico
    uart = UART(0, baudrate=UART_BAUD, tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN))
    uart.init(bits=8, parity=None, stop=1)

    print(f"UART initialized: {UART_BAUD} baud on GP{UART_TX_PIN}/GP{UART_RX_PIN}")

    # Initialize IR transmitter and movement controller
    transmitter = IRTransmitter()
    movement = MovementController(transmitter)

    print(f"IR transmitter ready on GP{PIN_IR_LED}")

    # Wait for camera to boot, then send OK to enable IR mode
    print(f"Waiting {CAMERA_BOOT_DELAY_SEC}s for camera to boot...")
    for i in range(CAMERA_BOOT_DELAY_SEC * 2):
        led.toggle()
        time.sleep_ms(500)

    print("Sending OK to enable IR mode...")
    transmitter.reset_timing()
    for _ in range(3):
        transmitter.send_command(IRCode.OK)

    print("Ready for commands!")
    led.value(1)

    # Main loop - keep it tight!
    last_blink = time.ticks_ms()

    while True:
        # Poll movement controller for IR timing
        # This is the most important thing - must happen frequently
        movement.poll()

        # Check for incoming commands (non-blocking)
        if uart.any():
            cmd = uart.read(1)
            if cmd:
                cmd_byte = cmd[0]
                response = handle_command(cmd_byte, movement, uart)
                uart.write(bytes([response]))

        # Blink LED slowly when idle, fast when moving
        now = time.ticks_ms()
        blink_interval = 200 if movement.active else 1000
        if time.ticks_diff(now, last_blink) > blink_interval:
            led.toggle()
            last_blink = now


if __name__ == "__main__":
    main()
