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
PIN_IR_LED = 15

# IR receiver for signal verification (optional)
PIN_IR_RECEIVER = 22

# Relay control for camera power
PIN_RELAY = 20

# W5500 SPI Configuration (SPI0)
PIN_SPI_SCK = 18   # SPI Clock
PIN_SPI_MOSI = 19  # SPI MOSI (Master Out Slave In)
PIN_SPI_MISO = 16  # SPI MISO (Master In Slave Out)
PIN_SPI_CS = 17    # SPI Chip Select
PIN_W5500_RST = 21 # W5500 Reset pin

# Status LED (onboard)
PIN_LED = "LED"  # Pico 2W onboard LED

# =============================================================================
# IR Protocol Timing (microseconds)
# =============================================================================
# LifeSize uses pulse-distance encoding at 38kHz carrier

# Carrier frequency
IR_CARRIER_FREQ_HZ = 38000
IR_CARRIER_PERIOD_US = 26  # ~26.3us for 38kHz
IR_CARRIER_DUTY_CYCLE = 0.33  # 33% duty cycle

# Leader pulse timing
IR_LEADER_MARK_US = 2600
IR_LEADER_SPACE_US = 1120

# Bit encoding timing
IR_BIT_MARK_US = 560      # Mark duration for all bits
IR_BIT_0_SPACE_US = 560   # Short space = 0
IR_BIT_1_SPACE_US = 1680  # Long space = 1

# Stop bit
IR_STOP_MARK_US = 560

# Frame timing
IR_FRAME_GAP_MS = 57      # Critical 57ms gap between frames
IR_FRAME_CYCLE_MS = 111   # Total cycle time (frame + gap)

# =============================================================================
# LifeSize Device Code
# =============================================================================
LIFESIZE_DEVICE_CODE = 0x98
LIFESIZE_DEVICE_CODE_INV = 0x67  # Inverted device code

# =============================================================================
# LifeSize Command Codes
# =============================================================================
class IRCommand:
    """IR command codes for LifeSize camera"""
    UP = 0x15
    DOWN = 0x1A
    LEFT = 0x25
    RIGHT = 0x2A
    OK = 0x1C       # OK/Select button
    ZOOM_IN = 0x37  # Zoom Tele
    ZOOM_OUT = 0x38 # Zoom Wide

    # Additional commands (if discovered)
    POWER = 0x00    # Placeholder - needs verification
    MENU = 0x00     # Placeholder - needs verification

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
