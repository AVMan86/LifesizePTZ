"""
Configuration for VISCA Pico (Network Handler)

This Pico handles:
- W5500 Ethernet communication
- VISCA command parsing
- Sending simple commands to IR Pico via UART
"""

# =============================================================================
# Network Configuration
# =============================================================================

BRIDGE_IP = "192.168.5.177"
BRIDGE_SUBNET = "255.255.255.0"
BRIDGE_GATEWAY = "192.168.5.1"
BRIDGE_DNS = "8.8.8.8"
VISCA_PORT = 52381

# =============================================================================
# W5500 SPI Pins
# =============================================================================

PIN_SPI_SCK = 2
PIN_SPI_MOSI = 3
PIN_SPI_MISO = 4
PIN_SPI_CS = 5
PIN_W5500_RST = 6

# =============================================================================
# Other Pins
# =============================================================================

PIN_LED = 25  # Onboard LED

# =============================================================================
# Debug Flags
# =============================================================================

DEBUG_VISCA = True
DEBUG_UART = True  # Temporarily enabled for troubleshooting
