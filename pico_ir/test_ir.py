"""
IR Pico Test Script - Keyboard-controlled IR transmission

Load this onto the IR Pico and open a serial terminal (like Thonny or PuTTY).
Hold keys to send continuous IR codes, release to stop.

Key mappings:
  W / 8     = UP
  S / 2     = DOWN
  A / 4     = LEFT
  D / 6     = RIGHT
  7         = UP-LEFT
  9         = UP-RIGHT
  1         = DOWN-LEFT
  3         = DOWN-RIGHT
  + / =     = ZOOM IN
  - / _     = ZOOM OUT
  Enter / O = OK (single press)
  Q         = Quit test

The camera should move smoothly while you hold the key!
"""

import time
import sys
import select
import gc
from machine import Pin, PWM

# =============================================================================
# Configuration
# =============================================================================

PIN_IR_LED = 15
PIN_LED = 25  # Onboard LED for visual feedback

# IR Protocol timing (microseconds)
CARRIER_FREQ = 38000
HEADER_MARK = 2550
HEADER_SPACE = 2500
BIT_MARK = 1200
BIT_0_SPACE = 1050
BIT_1_SPACE = 2825
STOP_MARK = 1200
PACKET_GAP_US = 57325  # Critical 57.325ms gap

# LifeSize device code
DEVICE_CODE = 0x98

# IR command codes
class IRCode:
    UP = 0x15
    DOWN = 0x1A
    LEFT = 0x25
    RIGHT = 0x2A
    OK = 0x1C
    ZOOM_IN = 0x34
    ZOOM_OUT = 0x3B

# Key to IR code mapping
KEY_MAP = {
    'w': [IRCode.UP],
    '8': [IRCode.UP],
    's': [IRCode.DOWN],
    '2': [IRCode.DOWN],
    'a': [IRCode.LEFT],
    '4': [IRCode.LEFT],
    'd': [IRCode.RIGHT],
    '6': [IRCode.RIGHT],
    '7': [IRCode.UP, IRCode.LEFT],
    '9': [IRCode.UP, IRCode.RIGHT],
    '1': [IRCode.DOWN, IRCode.LEFT],
    '3': [IRCode.DOWN, IRCode.RIGHT],
    '+': [IRCode.ZOOM_IN],
    '=': [IRCode.ZOOM_IN],
    '-': [IRCode.ZOOM_OUT],
    '_': [IRCode.ZOOM_OUT],
}

OK_KEYS = ['o', '\r', '\n']

# =============================================================================
# IR Transmitter
# =============================================================================

class IRTransmitter:
    def __init__(self, pin_num: int):
        self.pin = Pin(pin_num, Pin.OUT)
        self.pin.value(0)
        self.pwm = None
        self.last_frame_end = 0

    def _carrier_on(self):
        """Start 38kHz carrier."""
        self.pwm = PWM(self.pin)
        self.pwm.freq(CARRIER_FREQ)
        self.pwm.duty_u16(21845)  # 33% duty cycle

    def _carrier_off(self):
        """Stop carrier."""
        if self.pwm:
            self.pwm.deinit()
            self.pwm = None
        self.pin.init(Pin.OUT)
        self.pin.value(0)

    def _mark(self, duration_us: int):
        """Carrier on for duration."""
        self._carrier_on()
        time.sleep_us(duration_us)
        self._carrier_off()

    def _space(self, duration_us: int):
        """Carrier off for duration."""
        time.sleep_us(duration_us)

    def reset_timing(self):
        """Reset timing for fresh start."""
        self.last_frame_end = 0

    def send_command(self, cmd: int):
        """Send a complete IR frame with proper gap timing."""
        now = time.ticks_us()

        # Wait for gap if needed
        if self.last_frame_end > 0:
            elapsed = time.ticks_diff(now, self.last_frame_end)
            if elapsed < PACKET_GAP_US:
                time.sleep_us(PACKET_GAP_US - elapsed)

        # Build 16-bit data: device code + command
        data = (DEVICE_CODE << 8) | cmd

        # Send header
        self._mark(HEADER_MARK)
        self._space(HEADER_SPACE)

        # Send 16 bits MSB first
        for i in range(15, -1, -1):
            self._mark(BIT_MARK)
            if (data >> i) & 1:
                self._space(BIT_1_SPACE)
            else:
                self._space(BIT_0_SPACE)

        # Stop bit
        self._mark(STOP_MARK)

        self.last_frame_end = time.ticks_us()

# =============================================================================
# Input Handling
# =============================================================================

def char_available():
    """Check if a character is available on stdin."""
    return select.select([sys.stdin], [], [], 0)[0]

def read_char():
    """Read a single character if available."""
    if char_available():
        return sys.stdin.read(1)
    return None

# =============================================================================
# Main Test Loop
# =============================================================================

def main():
    print("\n" + "=" * 50)
    print("IR Pico Test - Keyboard Control")
    print("=" * 50)
    print("\nKey mappings:")
    print("  W/8=UP  S/2=DOWN  A/4=LEFT  D/6=RIGHT")
    print("  7=UP-LEFT  9=UP-RIGHT  1=DN-LEFT  3=DN-RIGHT")
    print("  +/= = ZOOM IN    -/_ = ZOOM OUT")
    print("  O/Enter = OK     Q = Quit")
    print("\nHold keys for continuous movement!")
    print("=" * 50 + "\n")

    tx = IRTransmitter(PIN_IR_LED)
    led = Pin(PIN_LED, Pin.OUT)

    current_codes = None
    last_input_time = 0
    INPUT_TIMEOUT_MS = 150  # Stop after 150ms of no input

    frame_count = 0

    # Disable automatic garbage collection - we'll control it manually
    gc.disable()

    while True:
        char = read_char()

        if char:
            char_lower = char.lower()
            last_input_time = time.ticks_ms()

            # Quit
            if char_lower == 'q':
                print("\nQuitting test. Goodbye!")
                led.value(0)
                return

            # OK button (single press, not continuous)
            if char_lower in OK_KEYS:
                print("OK pressed (3x)")
                led.value(1)
                tx.reset_timing()
                for _ in range(3):
                    tx.send_command(IRCode.OK)
                led.value(0)
                current_codes = None
                continue

            # Movement keys
            if char_lower in KEY_MAP:
                new_codes = KEY_MAP[char_lower]
                if new_codes != current_codes:
                    # New movement direction
                    current_codes = new_codes
                    tx.reset_timing()
                    code_names = {
                        IRCode.UP: "UP", IRCode.DOWN: "DOWN",
                        IRCode.LEFT: "LEFT", IRCode.RIGHT: "RIGHT",
                        IRCode.ZOOM_IN: "ZOOM+", IRCode.ZOOM_OUT: "ZOOM-"
                    }
                    names = [code_names.get(c, hex(c)) for c in current_codes]
                    print(f"Movement: {' + '.join(names)}", end="")
                    frame_count = 0

        # Send IR codes if movement is active
        if current_codes:
            # Check timeout
            if time.ticks_diff(time.ticks_ms(), last_input_time) > INPUT_TIMEOUT_MS:
                print(f" ({frame_count} frames)")
                current_codes = None
                led.value(0)
            else:
                # Send all codes for this movement
                led.value(1)
                for code in current_codes:
                    tx.send_command(code)
                frame_count += 1
        else:
            led.value(0)
            gc.collect()  # Run GC only when idle (not during IR transmission)
            time.sleep_ms(10)  # Small delay when idle

if __name__ == "__main__":
    main()
