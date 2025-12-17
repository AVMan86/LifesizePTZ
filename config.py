"""
Configuration for LifeSize PTZ Camera VISCA-to-IR Bridge
Raspberry Pi Pico 2W with W5500 Ethernet module
"""

# =============================================================================
# Network Configuration
# =============================================================================
BRIDGE_IP = "192.168.5.177"
BRIDGE_SUBNET = "255.255.255.0"
BRIDGE_GATEWAY = "192.168.5.1"
BRIDGE_DNS = "192.168.5.1"

VISCA_PORT = 52381  # Standard VISCA over IP port
CONTROLLER_IP = "192.168.5.100"  # Expected controller address

# =============================================================================
# GPIO Pin Definitions
# =============================================================================
# IR LED output (active high, use NPN transistor driver)
PIN_IR_LED = 16

# IR receiver for signal verification (optional)
PIN_IR_RECEIVER = 21

# Relay control for camera power
PIN_RELAY = 20

# W5500 SPI Configuration (SPI0)
PIN_SPI_SCK = 2   # SPI Clock
PIN_SPI_MOSI = 3  # SPI MOSI (Master Out Slave In)
PIN_SPI_MISO = 4  # SPI MISO (Master In Slave Out)
PIN_SPI_CS = 5    # SPI Chip Select
PIN_W5500_RST = 6 # W5500 Reset pin

# Status LED (onboard)
PIN_LED = "LED"  # Pico 2W onboard LED

# =============================================================================
# IR Protocol Timing (microseconds) - Tuned from Gemini analysis
# =============================================================================
# LifeSize uses 16-bit pulse-distance encoding at 38kHz carrier
# Protocol: Header + 16 data bits (MSB first) + Stop bit
# Data format: Device code (0x98) << 8 | Command code

# Carrier frequency
IR_CARRIER_FREQ_HZ = 38000
IR_CARRIER_DUTY_U16 = 32768  # 50% duty cycle for PWM (0-65535 range)

# Header pulse timing (tuned for Pico overhead)
IR_HEADER_MARK_US = 2550   # ~2.55ms header mark
IR_HEADER_SPACE_US = 2500  # ~2.5ms header space

# Bit encoding timing (tuned for Pico overhead)
IR_BIT_MARK_US = 1200      # ~1.2ms mark for all bits
IR_BIT_0_SPACE_US = 1050   # ~1.05ms space = 0
IR_BIT_1_SPACE_US = 2825   # ~2.825ms space = 1

# Stop bit
IR_STOP_MARK_US = 1200     # Same as bit mark

# Frame timing
IR_PACKET_GAP_US = 57325   # Critical 57.325ms gap between packets

# =============================================================================
# LifeSize Device Code
# =============================================================================
LIFESIZE_DEVICE_CODE = 0x98
LIFESIZE_DEVICE_CODE_INV = 0x67  # Inverted device code

# =============================================================================
# LifeSize Command Codes (from Gemini analysis)
# =============================================================================
class IRCommand:
    """IR command codes for LifeSize camera"""
    UP = 0x15
    DOWN = 0x1A
    LEFT = 0x25
    RIGHT = 0x2A
    OK = 0x1C       # OK/Select button
    ZOOM_IN = 0x34  # Zoom Tele (corrected)
    ZOOM_OUT = 0x3B # Zoom Wide (corrected)

# =============================================================================
# VISCA Command Mapping
# =============================================================================
# Maps (pan_direction, tilt_direction) to IR commands
# Pan: 01=left, 02=right, 03=stop
# Tilt: 01=up, 02=down, 03=stop
VISCA_PANTILT_MAP = {
    (0x03, 0x01): IRCommand.UP,      # Tilt up
    (0x03, 0x02): IRCommand.DOWN,    # Tilt down
    (0x01, 0x03): IRCommand.LEFT,    # Pan left
    (0x02, 0x03): IRCommand.RIGHT,   # Pan right
    (0x03, 0x03): None,              # Stop (no IR, just cease transmission)
    # Diagonal movements - handled by alternating commands
    (0x01, 0x01): (IRCommand.LEFT, IRCommand.UP),     # Up-Left
    (0x02, 0x01): (IRCommand.RIGHT, IRCommand.UP),    # Up-Right
    (0x01, 0x02): (IRCommand.LEFT, IRCommand.DOWN),   # Down-Left
    (0x02, 0x02): (IRCommand.RIGHT, IRCommand.DOWN),  # Down-Right
}

# =============================================================================
# Movement State Machine
# =============================================================================
class MovementState:
    """States for the movement state machine"""
    IDLE = 0
    MOVING = 1
    STOPPING = 2

# =============================================================================
# Timing Configuration
# =============================================================================
# How many repeat frames to send for a single button press
SINGLE_PRESS_REPEATS = 3

# Minimum time between accepting new VISCA commands (ms)
COMMAND_DEBOUNCE_MS = 50

# Timeout for continuous movement if no stop received (ms)
MOVEMENT_TIMEOUT_MS = 30000  # 30 seconds safety timeout

# =============================================================================
# Debug Configuration
# =============================================================================
DEBUG_VISCA = True       # Print received VISCA commands
DEBUG_IR = True          # Print IR transmission details
DEBUG_TIMING = False     # Print detailed timing info
