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
import gc
import micropython
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

# High-precision timing
micropython.alloc_emergency_exception_buf(100)

# Debug flag
DEBUG_UART = True  # Show all UART communication

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
# IR Transmitter (Gemini-style simple approach)
# =============================================================================

class IRTransmitter:
    """
    Hardware-level IR transmitter with simple, reliable timing.

    Uses the Gemini approach: persistent PWM, toggle duty cycle,
    unconditional gap sleep after each frame.
    """

    def __init__(self):
        self.pwm = PWM(Pin(PIN_IR_LED))
        self.pwm.freq(IR_CARRIER_FREQ_HZ)
        self.pwm.duty_u16(0)

    def send_frame(self, code: int):
        """Send a single 16-bit IR frame."""
        # Header
        self.pwm.duty_u16(IR_CARRIER_DUTY)
        time.sleep_us(IR_HEADER_MARK_US)
        self.pwm.duty_u16(0)
        time.sleep_us(IR_HEADER_SPACE_US)

        # Data bits (16 bits, MSB first)
        for i in range(15, -1, -1):
            bit = (code >> i) & 1
            self.pwm.duty_u16(IR_CARRIER_DUTY)
            time.sleep_us(IR_BIT_MARK_US)
            self.pwm.duty_u16(0)
            time.sleep_us(IR_BIT_1_SPACE_US if bit else IR_BIT_0_SPACE_US)

        # Stop bit
        self.pwm.duty_u16(IR_CARRIER_DUTY)
        time.sleep_us(IR_STOP_MARK_US)
        self.pwm.duty_u16(0)

    def send_command(self, ir_code: int):
        """Send IR command followed by protocol gap."""
        code = (LIFESIZE_DEVICE_CODE << 8) | ir_code
        self.send_frame(code)
        time.sleep_us(IR_PACKET_GAP_US)

    def stop(self):
        """Ensure carrier is off."""
        self.pwm.duty_u16(0)


# =============================================================================
# Movement State Machine
# =============================================================================

class MovementController:
    """
    Manages continuous IR transmission for smooth camera movement.

    When movement is active, continuously sends IR frames with proper gaps.
    For diagonal movement, alternates between the two direction codes.
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

    def stop(self):
        """Stop all movement."""
        self.active = False
        self.commands = []
        self.tx.stop()

    def poll(self):
        """
        Send next IR frame if movement is active.

        Call this in the main loop. Each call sends one frame
        (with built-in gap timing).
        """
        if not self.active or not self.commands:
            return False

        # Send current command
        ir_code = self.commands[self.cmd_index]
        self.tx.send_command(ir_code)

        # Move to next command (for diagonal alternation)
        self.cmd_index = (self.cmd_index + 1) % len(self.commands)
        return True


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

# Command names for debugging
CMD_NAMES = {
    Cmd.START_UP: "UP",
    Cmd.START_DOWN: "DOWN",
    Cmd.START_LEFT: "LEFT",
    Cmd.START_RIGHT: "RIGHT",
    Cmd.START_ZOOM_IN: "ZOOM_IN",
    Cmd.START_ZOOM_OUT: "ZOOM_OUT",
    Cmd.START_UP_LEFT: "UP_LEFT",
    Cmd.START_UP_RIGHT: "UP_RIGHT",
    Cmd.START_DOWN_LEFT: "DOWN_LEFT",
    Cmd.START_DOWN_RIGHT: "DOWN_RIGHT",
    Cmd.STOP: "STOP",
    Cmd.PRESS_OK: "OK",
    Cmd.PING: "PING",
    Cmd.RESET: "RESET",
}

# Response names for debugging
RESP_NAMES = {
    Resp.ACK: "ACK",
    Resp.PONG: "PONG",
    Resp.ERROR: "ERROR",
}


def handle_command(cmd: int, movement: MovementController) -> int:
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

    # Disable automatic GC during operation
    gc.disable()

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

    # Clear any stale UART data from power-on
    stale_count = 0
    while uart.any():
        uart.read()
        stale_count += 1
    if stale_count > 0:
        print(f"Cleared {stale_count} stale UART bytes from buffer")

    # Wait for camera to boot, then send OK to enable IR mode
    print(f"Waiting {CAMERA_BOOT_DELAY_SEC}s for camera to boot...")
    print("(IR Pico will respond to PING during this time)")
    for i in range(CAMERA_BOOT_DELAY_SEC * 2):
        led.toggle()
        time.sleep_ms(500)

        # Check for UART commands even during boot wait (respond to PING)
        if uart.any():
            cmd = uart.read(1)
            if cmd:
                response = handle_command(cmd[0], movement)
                uart.write(bytes([response]))
                if DEBUG_UART:
                    cmd_name = CMD_NAMES.get(cmd[0], f"0x{cmd[0]:02X}")
                    resp_name = RESP_NAMES.get(response, f"0x{response:02X}")
                    print(f"[BOOT] RX: {cmd_name} -> TX: {resp_name}")

    print("Sending OK to enable IR mode...")
    for _ in range(3):
        transmitter.send_command(IRCode.OK)

    print("Ready for commands!")
    print("=" * 50)
    led.value(1)

    # Main loop
    last_blink = time.ticks_ms()

    while True:
        # ALWAYS check for UART commands first (including STOP!)
        if uart.any():
            cmd = uart.read(1)
            if cmd:
                response = handle_command(cmd[0], movement)
                uart.write(bytes([response]))

                # Debug output
                if DEBUG_UART:
                    cmd_name = CMD_NAMES.get(cmd[0], f"0x{cmd[0]:02X}")
                    resp_name = RESP_NAMES.get(response, f"0x{response:02X}")
                    print(f"RX: {cmd_name} (0x{cmd[0]:02X}) -> TX: {resp_name} (0x{response:02X})")

        # Send IR frames if movement is active
        # This blocks for ~57ms per frame (includes gap)
        if movement.poll():
            # Frame was sent, LED on while moving
            led.value(1)
        else:
            # Not moving - do housekeeping
            gc.collect()

            # Blink LED slowly when idle
            now = time.ticks_ms()
            if time.ticks_diff(now, last_blink) > 1000:
                led.toggle()
                last_blink = now


if __name__ == "__main__":
    main()
