"""
IR Pico Test Script - Keyboard-controlled IR transmission

Based on Gemini's simpler approach with persistent PWM.

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
import machine
import micropython

# High-precision timing
micropython.alloc_emergency_exception_buf(100)

# =============================================================================
# Configuration
# =============================================================================

PIN_IR_LED = 15
PIN_LED = 25  # Onboard LED for visual feedback

# IR Protocol timing
FREQUENCY = 38000
DUTY_CYCLE = 32768  # 50% duty

HDR_MARK = 2550
HDR_SPACE = 2500
BIT_MARK = 1200
ONE_SPACE = 2825
ZERO_SPACE = 1050
PACKET_GAP_US = 57325

# LifeSize 16-bit codes (device 0x98 + command)
class Code:
    UP = 0x9815
    DOWN = 0x981A
    LEFT = 0x9825
    RIGHT = 0x982A
    OK = 0x981C
    ZOOM_IN = 0x9834
    ZOOM_OUT = 0x983B

# Key to code mapping
KEY_MAP = {
    'w': [Code.UP],
    '8': [Code.UP],
    's': [Code.DOWN],
    '2': [Code.DOWN],
    'a': [Code.LEFT],
    '4': [Code.LEFT],
    'd': [Code.RIGHT],
    '6': [Code.RIGHT],
    '7': [Code.UP, Code.LEFT],
    '9': [Code.UP, Code.RIGHT],
    '1': [Code.DOWN, Code.LEFT],
    '3': [Code.DOWN, Code.RIGHT],
    '+': [Code.ZOOM_IN],
    '=': [Code.ZOOM_IN],
    '-': [Code.ZOOM_OUT],
    '_': [Code.ZOOM_OUT],
}

OK_KEYS = ['o', '\r', '\n']

# =============================================================================
# IR Transmitter (Gemini-style simple approach)
# =============================================================================

class IRTransmitter:
    def __init__(self, pin_id):
        self.pwm = machine.PWM(machine.Pin(pin_id))
        self.pwm.freq(FREQUENCY)
        self.pwm.duty_u16(0)  # Start with carrier off

    def send_code(self, code):
        """Send a single 16-bit IR packet."""
        # Header
        self.pwm.duty_u16(DUTY_CYCLE)
        time.sleep_us(HDR_MARK)
        self.pwm.duty_u16(0)
        time.sleep_us(HDR_SPACE)

        # Data (16 bits, MSB first)
        for i in range(15, -1, -1):
            bit = (code >> i) & 1

            self.pwm.duty_u16(DUTY_CYCLE)
            time.sleep_us(BIT_MARK)
            self.pwm.duty_u16(0)

            if bit == 1:
                time.sleep_us(ONE_SPACE)
            else:
                time.sleep_us(ZERO_SPACE)

        # Stop bit
        self.pwm.duty_u16(DUTY_CYCLE)
        time.sleep_us(BIT_MARK)
        self.pwm.duty_u16(0)

    def send_with_gap(self, code):
        """Send code followed by the protocol gap."""
        self.send_code(code)
        time.sleep_us(PACKET_GAP_US)

    def deinit(self):
        """Clean up PWM."""
        self.pwm.deinit()

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
    led = machine.Pin(PIN_LED, machine.Pin.OUT)

    current_codes = None
    last_input_time = 0
    INPUT_TIMEOUT_MS = 150  # Stop after 150ms of no input

    frame_count = 0

    # Disable automatic garbage collection - we'll control it manually
    gc.disable()

    try:
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
                    for _ in range(3):
                        tx.send_with_gap(Code.OK)
                    led.value(0)
                    current_codes = None
                    continue

                # Movement keys
                if char_lower in KEY_MAP:
                    new_codes = KEY_MAP[char_lower]
                    if new_codes != current_codes:
                        # New movement direction
                        current_codes = new_codes
                        code_names = {
                            Code.UP: "UP", Code.DOWN: "DOWN",
                            Code.LEFT: "LEFT", Code.RIGHT: "RIGHT",
                            Code.ZOOM_IN: "ZOOM+", Code.ZOOM_OUT: "ZOOM-"
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
                    # Send all codes for this movement (each with gap)
                    led.value(1)
                    for code in current_codes:
                        tx.send_with_gap(code)
                    frame_count += 1
            else:
                led.value(0)
                gc.collect()  # Run GC only when idle
                time.sleep_ms(10)
    finally:
        tx.deinit()

if __name__ == "__main__":
    main()
