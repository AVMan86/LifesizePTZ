"""
Serial Protocol for VISCA-to-IR Bridge Communication

This file defines the simple byte-based protocol used between:
- Pico #1 (VISCA): Receives network commands, sends serial commands
- Pico #2 (IR): Receives serial commands, transmits IR signals

Protocol: Single-byte commands at 115200 baud, 8N1
"""

# UART Configuration
UART_BAUD = 115200
UART_TX_PIN = 0  # GP0
UART_RX_PIN = 1  # GP1

# =============================================================================
# Command Bytes (Pico #1 → Pico #2)
# =============================================================================

class Cmd:
    """Command bytes sent from VISCA Pico to IR Pico."""

    # Movement start commands (0x01-0x0F)
    START_UP = 0x01
    START_DOWN = 0x02
    START_LEFT = 0x03
    START_RIGHT = 0x04
    START_ZOOM_IN = 0x05
    START_ZOOM_OUT = 0x06

    # Diagonal movements (0x07-0x0A)
    START_UP_LEFT = 0x07
    START_UP_RIGHT = 0x08
    START_DOWN_LEFT = 0x09
    START_DOWN_RIGHT = 0x0A

    # Stop command (0x10)
    STOP = 0x10

    # Single-press commands (0x20-0x2F)
    PRESS_OK = 0x20

    # System commands (0x30-0x3F)
    POWER_ON = 0x30   # Turn on relay + send OK after delay
    POWER_OFF = 0x31  # Turn off relay

    # Diagnostic commands (0xF0-0xFF)
    PING = 0xFE       # Request status
    RESET = 0xFF      # Reset IR Pico state


# =============================================================================
# Response Bytes (Pico #2 → Pico #1)
# =============================================================================

class Resp:
    """Response bytes sent from IR Pico to VISCA Pico."""

    ACK = 0x06        # Command acknowledged
    PONG = 0xFE       # Response to PING
    ERROR = 0x15      # Error/invalid command


# =============================================================================
# IR Command Codes (LifeSize camera)
# =============================================================================

class IRCode:
    """LifeSize IR command codes (8-bit, combined with device code 0x98)."""

    UP = 0x15
    DOWN = 0x1A
    LEFT = 0x25
    RIGHT = 0x2A
    OK = 0x1C
    ZOOM_IN = 0x34   # Tele
    ZOOM_OUT = 0x3B  # Wide


# =============================================================================
# Timing Constants
# =============================================================================

# IR Protocol timing (microseconds)
IR_CARRIER_FREQ_HZ = 38000
IR_HEADER_MARK_US = 2550
IR_HEADER_SPACE_US = 2500
IR_BIT_MARK_US = 1200
IR_BIT_0_SPACE_US = 1050
IR_BIT_1_SPACE_US = 2825
IR_STOP_MARK_US = 1200

# Critical: Gap between IR packets for smooth camera movement
IR_PACKET_GAP_US = 57325  # 57.325ms

# LifeSize device code
LIFESIZE_DEVICE_CODE = 0x98
