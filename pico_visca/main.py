"""
VISCA Pico - Network Handler for LifeSize Camera Bridge

This Pico handles all network complexity:
- W5500 Ethernet communication
- VISCA command parsing
- Sending simple commands to IR Pico via UART
- Relay control based on network link status

Power Design:
  VISCA Pico + W5500 are always powered (low standby power).
  The relay controls power to the camera and IR Pico.
  When network link is detected, relay enables and camera boots.
  When network link is lost, relay disables and camera powers off.

Wiring:
- GP0 (TX) → IR Pico GP1 (RX)
- GP1 (RX) ← IR Pico GP0 (TX)
- GP2-GP6 → W5500 SPI
- GP7 → Relay control (active high)
- GND ↔ GND
"""

import time
import machine
from machine import Pin, SPI, UART

from config import (
    BRIDGE_IP, BRIDGE_SUBNET, BRIDGE_GATEWAY, BRIDGE_DNS,
    VISCA_PORT,
    PIN_SPI_SCK, PIN_SPI_MOSI, PIN_SPI_MISO, PIN_SPI_CS, PIN_W5500_RST,
    PIN_LED,
    DEBUG_VISCA, DEBUG_UART,
)
from protocol import Cmd, Resp, UART_BAUD, UART_TX_PIN, UART_RX_PIN
from visca_parser import VISCAParser, VISCAResponse, VISCACommandType

# Relay control pin
PIN_RELAY = 7

# Time to wait after link up before enabling relay (let link stabilize)
LINK_STABLE_TIME_MS = 1000

# Time to wait after relay on before checking IR Pico (camera boot time)
IR_PICO_BOOT_TIME_MS = 2000


class IRPicoLink:
    """
    Communication link to the IR Pico via UART.

    Sends simple command bytes, receives ACK responses.
    """

    def __init__(self):
        self.uart = UART(0, baudrate=UART_BAUD,
                        tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN))
        self.uart.init(bits=8, parity=None, stop=1)
        self.connected = False
        print(f"UART link initialized: {UART_BAUD} baud")

    def send_command(self, cmd: int) -> bool:
        """
        Send a command to the IR Pico.

        Returns True if ACK received, False otherwise.
        """
        if not self.connected:
            return False

        if DEBUG_UART:
            print(f"UART TX: 0x{cmd:02X}")

        self.uart.write(bytes([cmd]))

        # Wait for response (with timeout)
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 100:
            if self.uart.any():
                resp = self.uart.read(1)
                if resp:
                    if DEBUG_UART:
                        print(f"UART RX: 0x{resp[0]:02X}")
                    return resp[0] == Resp.ACK
            time.sleep_ms(1)

        print("UART: No response from IR Pico")
        return False

    def start_movement(self, cmd: int):
        """Start a movement (sends command, doesn't wait for completion)."""
        self.send_command(cmd)

    def stop_movement(self):
        """Stop all movement."""
        self.send_command(Cmd.STOP)

    def press_ok(self):
        """Send OK button press."""
        self.send_command(Cmd.PRESS_OK)

    def ping(self) -> bool:
        """Check if IR Pico is responding."""
        # Clear any stale data
        while self.uart.any():
            self.uart.read()

        self.uart.write(bytes([Cmd.PING]))
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 100:
            if self.uart.any():
                resp = self.uart.read(1)
                if resp and resp[0] == Resp.PONG:
                    self.connected = True
                    return True
            time.sleep_ms(1)
        self.connected = False
        return False


class NetworkManager:
    """
    Manages W5500 Ethernet and link status monitoring.
    """

    def __init__(self, relay_pin: Pin):
        self.relay = relay_pin
        self.relay.value(0)  # Start with relay off
        self.nic = None
        self.spi = None
        self.cs_pin = None
        self.rst_pin = None
        self.link_up = False
        self.link_stable_since = 0
        self.network_configured = False
        self.last_phy_value = None  # Track last PHY register value for debug

    def init_hardware(self) -> bool:
        """Initialize W5500 hardware (SPI, reset)."""
        print("Initializing W5500 hardware...")

        try:
            import network

            # Reset W5500
            self.rst_pin = Pin(PIN_W5500_RST, Pin.OUT)
            self.rst_pin.value(0)
            time.sleep_ms(100)
            self.rst_pin.value(1)
            time.sleep_ms(500)

            # Configure SPI
            self.spi = SPI(0, baudrate=10_000_000, polarity=0, phase=0,
                          sck=Pin(PIN_SPI_SCK),
                          mosi=Pin(PIN_SPI_MOSI),
                          miso=Pin(PIN_SPI_MISO))
            self.cs_pin = Pin(PIN_SPI_CS, Pin.OUT, value=1)

            # Verify SPI communication by reading W5500 version register
            print("Testing SPI communication...")
            version = self.read_w5500_version()
            if version == 0x04:
                print(f"W5500 detected (version: 0x{version:02X})")
            elif version == 0x00 or version == 0xFF:
                print(f"WARNING: W5500 not responding (got 0x{version:02X})")
                print("Check SPI wiring: SCK=GP2, MOSI=GP3, MISO=GP4, CS=GP5, RST=GP6")
            else:
                print(f"WARNING: Unexpected chip version: 0x{version:02X}")

            # Initialize W5500 - don't activate yet
            self.nic = network.WIZNET5K(self.spi, self.cs_pin, self.rst_pin)

            print("W5500 hardware ready")
            return True

        except Exception as e:
            print(f"Hardware init error: {e}")
            return False

    def read_w5500_version(self) -> int:
        """Read W5500 version register (should return 0x04)."""
        if not self.spi or not self.cs_pin:
            return 0xFF

        try:
            # VERSIONR at address 0x0039 in common register space
            addr_hi = 0x00
            addr_lo = 0x39
            control = 0x00  # Common register, read mode

            self.cs_pin.value(0)
            self.spi.write(bytes([addr_hi, addr_lo, control]))
            result = self.spi.read(1)
            self.cs_pin.value(1)

            return result[0]
        except:
            return 0xFF

    def read_phy_link_raw(self) -> bool:
        """
        Read physical link status directly from W5500 PHY register.
        Only call when NIC is not active to avoid SPI conflicts.

        The PHYCFGR register (0x002E) bit 0 indicates link status:
        - 1 = Link up (cable connected)
        - 0 = Link down (no cable)
        """
        if not self.spi or not self.cs_pin:
            print("PHY read: SPI or CS not initialized")
            return False

        try:
            # W5500 SPI frame: 2 bytes address + 1 byte control + data
            addr_hi = 0x00
            addr_lo = 0x2E
            control = 0x00  # Common register, read mode

            self.cs_pin.value(0)
            self.spi.write(bytes([addr_hi, addr_lo, control]))
            result = self.spi.read(1)
            self.cs_pin.value(1)

            # Debug: Print only when value changes
            if result[0] != self.last_phy_value:
                print(f"PHYCFGR = 0x{result[0]:02X}, Link bit = {result[0] & 0x01}")
                self.last_phy_value = result[0]

            # Bit 0 = LNK (link status)
            return bool(result[0] & 0x01)

        except Exception as e:
            print(f"PHY read error: {e}")
            return False

    def configure_network(self) -> bool:
        """Configure static IP and activate NIC."""
        if not self.nic:
            return False

        try:
            self.nic.active(True)
            self.nic.ifconfig((BRIDGE_IP, BRIDGE_SUBNET, BRIDGE_GATEWAY, BRIDGE_DNS))
            config = self.nic.ifconfig()
            print(f"Network configured: {config[0]}")
            self.network_configured = True
            return True
        except Exception as e:
            print(f"Network config error: {e}")
            return False

    def deactivate_network(self):
        """Deactivate NIC to allow raw PHY reads."""
        if self.nic:
            try:
                self.nic.active(False)
            except:
                pass
        self.network_configured = False

    def check_link(self) -> bool:
        """Check if Ethernet link is up (physical cable connected)."""
        if not self.spi:
            return False

        # If network is configured, use isconnected()
        # If not configured, read PHY directly
        if self.network_configured:
            link = self.nic.isconnected()
        else:
            link = self.read_phy_link_raw()

        return link

    def update(self) -> str:
        """
        Update link status and manage relay.

        Returns: 'link_up', 'link_down', or 'no_change'
        """
        current_link = self.check_link()
        now = time.ticks_ms()

        if current_link and not self.link_up:
            # Link just came up - wait for stability
            if self.link_stable_since == 0:
                self.link_stable_since = now
                print("Link detected, waiting for stability...")
                return 'no_change'

            # Check if link has been stable long enough
            if time.ticks_diff(now, self.link_stable_since) >= LINK_STABLE_TIME_MS:
                self.link_up = True
                self.link_stable_since = 0
                print("Link stable - enabling relay")
                self.relay.value(1)
                return 'link_up'

        elif not current_link and self.link_up:
            # Link went down
            self.link_up = False
            self.link_stable_since = 0
            print("Link lost - disabling relay")
            self.relay.value(0)
            # Deactivate network so we can do raw PHY reads
            self.deactivate_network()
            return 'link_down'

        elif not current_link:
            # Link still down, reset stability timer
            self.link_stable_since = 0

        return 'no_change'


class VISCABridge:
    """
    VISCA-over-IP to Serial Bridge.

    Receives VISCA commands via UDP and translates them to
    simple serial commands for the IR Pico.
    """

    def __init__(self):
        self.led = Pin(PIN_LED, Pin.OUT)
        self.relay = Pin(PIN_RELAY, Pin.OUT)
        self.parser = VISCAParser()
        self.ir_link = IRPicoLink()
        self.network = NetworkManager(self.relay)
        self.socket = None
        self.running = False
        self.last_blink = 0
        self.network_ready = False

        # Track movement state to avoid redundant commands
        self.current_movement = None

    def init_socket(self) -> bool:
        """Initialize UDP socket."""
        try:
            import socket
            if self.socket:
                try:
                    self.socket.close()
                except:
                    pass
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind((BRIDGE_IP, VISCA_PORT))
            self.socket.setblocking(False)
            print(f"Listening on {BRIDGE_IP}:{VISCA_PORT} (UDP)")
            return True
        except Exception as e:
            print(f"Socket error: {e}")
            return False

    def on_link_up(self):
        """Handle network link coming up."""
        # Configure IP
        if not self.network.configure_network():
            print("Failed to configure network")
            return

        # Initialize socket
        if not self.init_socket():
            print("Failed to initialize socket")
            return

        self.network_ready = True

        # Wait for IR Pico to boot
        print(f"Waiting {IR_PICO_BOOT_TIME_MS}ms for IR Pico to boot...")
        time.sleep_ms(IR_PICO_BOOT_TIME_MS)

        # Check IR Pico connection
        print("Checking IR Pico connection...")
        for attempt in range(3):
            if self.ir_link.ping():
                print("IR Pico: Connected!")
                return
            time.sleep_ms(500)

        print("WARNING: IR Pico not responding (will retry)")

    def on_link_down(self):
        """Handle network link going down."""
        self.network_ready = False
        self.ir_link.connected = False
        self.current_movement = None

        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

        print("Network offline - waiting for link...")

    def process_visca(self, data: bytes, addr: tuple):
        """Process a VISCA command packet."""
        if DEBUG_VISCA:
            print(f"VISCA from {addr[0]}: {data.hex()}")

        cmd = self.parser.parse(data)

        if not cmd.valid:
            self._send_response(VISCAResponse.error(0x02), addr)
            return

        # Handle special commands (inquiries, etc)
        if cmd.needs_response:
            self._handle_special(cmd, addr)
            return

        # Send ACK
        self._send_response(VISCAResponse.ack(), addr)

        # Handle movement commands
        if cmd.is_stop():
            self.ir_link.stop_movement()
            self.current_movement = None
        elif cmd.serial_cmd is not None:
            # Only send if different from current movement
            if cmd.serial_cmd != self.current_movement:
                self.ir_link.start_movement(cmd.serial_cmd)
                self.current_movement = cmd.serial_cmd

        # Send completion
        self._send_response(VISCAResponse.completion(), addr)

    def _handle_special(self, cmd, addr: tuple):
        """Handle special VISCA commands (inquiries, etc)."""
        if cmd.command_type == VISCACommandType.IF_CLEAR:
            self._send_response(VISCAResponse.if_clear(), addr)

        elif cmd.command_type == VISCACommandType.ADDRESS_SET:
            self._send_response(VISCAResponse.address_set(), addr)

        elif cmd.command_type == VISCACommandType.VERSION_INQ:
            self._send_response(VISCAResponse.version_inquiry(), addr)

        elif cmd.command_type == VISCACommandType.CAM_INQUIRY:
            self._handle_inquiry(cmd, addr)

        else:
            self._send_response(VISCAResponse.completion(), addr)

    def _handle_inquiry(self, cmd, addr: tuple):
        """Handle inquiry commands."""
        if cmd.inquiry_type is None:
            self._send_response(VISCAResponse.completion(), addr)
            return

        cat, item = cmd.inquiry_type

        if cat == 0x04 and item == 0x00:  # Power
            self._send_response(VISCAResponse.power_inquiry(True), addr)
        elif cat == 0x04 and item == 0x39:  # Block inquiry
            self._send_response(VISCAResponse.block_inquiry(), addr)
        elif cat == 0x04 and item == 0x47:  # Zoom position
            self._send_response(VISCAResponse.zoom_position(0), addr)
        elif cat == 0x06 and item == 0x12:  # Pan-tilt position
            self._send_response(VISCAResponse.pan_tilt_position(0, 0), addr)
        else:
            self._send_response(VISCAResponse.completion(), addr)

    def _send_response(self, response: bytes, addr: tuple):
        """Send a VISCA response."""
        if self.socket:
            try:
                self.socket.sendto(response, addr)
            except Exception as e:
                print(f"Send error: {e}")

    def blink_led(self, fast: bool = False):
        """Blink status LED."""
        now = time.ticks_ms()
        interval = 200 if fast else 1000
        if time.ticks_diff(now, self.last_blink) > interval:
            self.led.toggle()
            self.last_blink = now

    def run(self):
        """Main event loop."""
        print("\n" + "=" * 50)
        print("VISCA Pico - Network Handler")
        print("=" * 50)

        # Initialize W5500 hardware
        if not self.network.init_hardware():
            print("FATAL: Cannot initialize W5500")
            while True:
                self.led.toggle()
                time.sleep_ms(100)

        print("Waiting for network link...")
        self.running = True

        while self.running:
            try:
                # Check link status and manage relay
                link_event = self.network.update()

                if link_event == 'link_up':
                    self.on_link_up()
                elif link_event == 'link_down':
                    self.on_link_down()

                # Process VISCA if network is ready
                if self.network_ready and self.socket:
                    try:
                        data, addr = self.socket.recvfrom(256)
                        if data:
                            # Re-check IR Pico connection if it was lost
                            if not self.ir_link.connected:
                                self.ir_link.ping()
                            self.process_visca(data, addr)
                    except OSError:
                        pass  # No data (non-blocking)

                # LED: fast blink when waiting for link, slow when ready
                self.blink_led(fast=not self.network_ready)

                time.sleep_ms(10)

            except KeyboardInterrupt:
                print("\nShutdown...")
                self.running = False

        self.ir_link.stop_movement()
        self.relay.value(0)
        if self.socket:
            self.socket.close()
        self.led.value(0)


def main():
    print("\n")
    print("=" * 50)
    print("  VISCA Pico - LifeSize Camera Bridge")
    print("  Network Handler with Link Monitoring")
    print("=" * 50)

    bridge = VISCABridge()
    bridge.run()


if __name__ == "__main__":
    main()
