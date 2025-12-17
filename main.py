"""
LifeSize PTZ Camera VISCA-to-IR Bridge
Main entry point

This bridge receives VISCA-over-IP commands via UDP and translates them
to IR signals for controlling a LifeSize 10x PTZ camera.

Hardware:
- Raspberry Pi Pico 2W (RP2350)
- W5500 Ethernet module (SPI)
- IR LED with driver transistor
- Optional relay for camera power control
"""

import time
import machine
from machine import Pin, SPI

from config import (
    BRIDGE_IP,
    BRIDGE_SUBNET,
    BRIDGE_GATEWAY,
    BRIDGE_DNS,
    VISCA_PORT,
    PIN_SPI_SCK,
    PIN_SPI_MOSI,
    PIN_SPI_MISO,
    PIN_SPI_CS,
    PIN_W5500_RST,
    PIN_RELAY,
    PIN_LED,
    PIN_IR_LED,
    DEBUG_VISCA,
    DEBUG_IR,
    IRCommand,
)
from visca_parser import VISCAParser, VISCAResponse, VISCACommandType
from command_scheduler import get_scheduler
from ir_transmitter import get_transmitter


class VISCABridge:
    """
    Main VISCA-to-IR bridge controller.

    Handles network initialization, VISCA command reception,
    and IR transmission scheduling.
    """

    def __init__(self):
        # Status LED
        self.led = Pin(PIN_LED, Pin.OUT)
        self.led_state = False

        # Relay for camera power
        self.relay = Pin(PIN_RELAY, Pin.OUT, value=0)

        # IR components
        self.parser = VISCAParser()
        self.scheduler = get_scheduler(use_timer=False)
        self.transmitter = get_transmitter()

        # Network
        self.nic = None
        self.socket = None

        # State
        self.running = False
        self.last_blink = 0

    def init_network(self) -> bool:
        """
        Initialize the W5500 Ethernet module.

        Returns True on success, False on failure.
        """
        print("Initializing W5500 Ethernet...")

        try:
            # Import network module
            import network

            # Reset W5500
            rst_pin = Pin(PIN_W5500_RST, Pin.OUT)
            rst_pin.value(0)
            time.sleep_ms(100)
            rst_pin.value(1)
            time.sleep_ms(500)  # Give W5500 more time to initialize

            # Configure SPI
            spi = SPI(
                0,
                baudrate=10_000_000,
                polarity=0,
                phase=0,
                sck=Pin(PIN_SPI_SCK),
                mosi=Pin(PIN_SPI_MOSI),
                miso=Pin(PIN_SPI_MISO),
            )
            cs_pin = Pin(PIN_SPI_CS, Pin.OUT, value=1)

            # Initialize W5500
            self.nic = network.WIZNET5K(spi, cs_pin, rst_pin)

            # Activate the network interface
            self.nic.active(True)
            print("W5500 activated")

            # Configure static IP
            self.nic.ifconfig((
                BRIDGE_IP,
                BRIDGE_SUBNET,
                BRIDGE_GATEWAY,
                BRIDGE_DNS
            ))

            # Check link status - try multiple methods
            print("Checking Ethernet link...")
            timeout = 50  # 5 seconds

            # Try to determine link status
            link_up = False
            while timeout > 0:
                try:
                    # Method 1: isconnected()
                    if self.nic.isconnected():
                        link_up = True
                        break
                except:
                    pass

                try:
                    # Method 2: Check if we can get valid ifconfig
                    config = self.nic.ifconfig()
                    if config[0] != '0.0.0.0':
                        link_up = True
                        break
                except:
                    pass

                time.sleep_ms(100)
                timeout -= 1

            # Print configuration regardless of link status
            try:
                config = self.nic.ifconfig()
                print(f"Network configured:")
                print(f"  IP Address: {config[0]}")
                print(f"  Subnet:     {config[1]}")
                print(f"  Gateway:    {config[2]}")
                print(f"  DNS:        {config[3]}")

                # If we have a valid IP, consider it working even if link check failed
                if config[0] == BRIDGE_IP:
                    print("Static IP configured successfully")
                    return True

            except Exception as e:
                print(f"Could not read ifconfig: {e}")

            if not link_up:
                print("WARNING: Link status unclear, proceeding anyway...")
                return True  # Try to proceed - the link light is on

            return True

        except ImportError:
            print("ERROR: network module not available")
            print("Make sure you're using MicroPython with W5500 support")
            return False
        except Exception as e:
            print(f"ERROR: Network initialization failed: {e}")
            import sys
            sys.print_exception(e)
            return False

    def init_socket(self) -> bool:
        """
        Initialize the UDP socket for VISCA commands.

        Returns True on success, False on failure.
        """
        print(f"Opening UDP socket on port {VISCA_PORT}...")

        try:
            import socket

            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Bind to specific IP - important for W5500 to work correctly
            # Using '' can cause issues on some embedded systems
            bind_addr = (BRIDGE_IP, VISCA_PORT)
            print(f"Binding socket to {bind_addr[0]}:{bind_addr[1]}...")
            self.socket.bind(bind_addr)
            self.socket.setblocking(False)

            print(f"Socket bound successfully!")
            print(f"Listening for VISCA commands on {BRIDGE_IP}:{VISCA_PORT} (UDP)")
            return True

        except Exception as e:
            print(f"ERROR: Socket initialization failed: {e}")
            import sys
            sys.print_exception(e)
            return False

    def process_visca(self, data: bytes, addr: tuple):
        """
        Process a received VISCA command.

        Args:
            data: Raw VISCA packet data
            addr: Source address (ip, port)
        """
        if DEBUG_VISCA:
            print(f"VISCA from {addr[0]}:{addr[1]}: {data.hex()}")

        # Parse the command
        cmd = self.parser.parse(data)

        if not cmd.valid:
            # Invalid command - send error
            self._send_response(VISCAResponse.error(0x02), addr)
            return

        # Handle special commands that need specific responses
        if cmd.needs_response:
            self._handle_special_command(cmd, addr)
            return

        # Send ACK immediately for regular commands
        self._send_response(VISCAResponse.ack(), addr)

        # Handle the command
        if cmd.is_stop():
            # Stop movement
            self.scheduler.stop_movement()
        else:
            # Get IR commands for this VISCA command
            ir_commands = cmd.get_ir_commands()

            if ir_commands:
                if cmd.command_type == VISCACommandType.ZOOM:
                    # Zoom commands use continuous movement
                    self.scheduler.start_movement(ir_commands)
                elif cmd.command_type == VISCACommandType.PAN_TILT:
                    # Pan/tilt uses continuous movement
                    self.scheduler.start_movement(ir_commands)
                else:
                    # Other commands use single press
                    self.scheduler.send_single_press(ir_commands[0])

        # Send completion
        self._send_response(VISCAResponse.completion(), addr)

    def _handle_special_command(self, cmd, addr: tuple):
        """Handle special commands that require specific responses."""
        if cmd.command_type == VISCACommandType.IF_CLEAR:
            # Interface clear - just acknowledge
            if DEBUG_VISCA:
                print("Responding to IF_Clear")
            self._send_response(VISCAResponse.if_clear(), addr)

        elif cmd.command_type == VISCACommandType.ADDRESS_SET:
            # Address set - respond with our address (1)
            if DEBUG_VISCA:
                print("Responding to AddressSet")
            self._send_response(VISCAResponse.address_set(), addr)

        elif cmd.command_type == VISCACommandType.VERSION_INQ:
            # Version inquiry
            if DEBUG_VISCA:
                print("Responding to VersionInq")
            self._send_response(VISCAResponse.version_inquiry(), addr)

        elif cmd.command_type == VISCACommandType.CAM_INQUIRY:
            # Handle other inquiries
            self._handle_inquiry(cmd, addr)

        else:
            # Unknown special command - send completion anyway
            self._send_response(VISCAResponse.completion(), addr)

    def _handle_inquiry(self, cmd, addr: tuple):
        """Handle inquiry commands."""
        inq_type = cmd.inquiry_type
        if inq_type is None:
            self._send_response(VISCAResponse.completion(), addr)
            return

        cat, item = inq_type

        # Power inquiry: 81 09 04 00 FF
        if cat == 0x04 and item == 0x00:
            if DEBUG_VISCA:
                print("Responding to PowerInq")
            self._send_response(VISCAResponse.power_inquiry(True), addr)

        # Block inquiry: 81 09 04 39 FF (connection test)
        elif cat == 0x04 and item == 0x39:
            if DEBUG_VISCA:
                print("Responding to BlockInquiry (connection test)")
            self._send_response(VISCAResponse.block_inquiry(), addr)

        # Zoom position inquiry: 81 09 04 47 FF
        elif cat == 0x04 and item == 0x47:
            if DEBUG_VISCA:
                print("Responding to ZoomPosInq")
            self._send_response(VISCAResponse.zoom_position(0x0000), addr)

        # Pan-Tilt position inquiry: 81 09 06 12 FF
        elif cat == 0x06 and item == 0x12:
            if DEBUG_VISCA:
                print("Responding to Pan-TiltPosInq")
            self._send_response(VISCAResponse.pan_tilt_position(0x0000, 0x0000), addr)

        else:
            # Unknown inquiry - send generic completion
            if DEBUG_VISCA:
                print(f"Unknown inquiry {cat:02X} {item:02X}, sending completion")
            self._send_response(VISCAResponse.completion(), addr)

    def _send_response(self, response: bytes, addr: tuple):
        """Send a VISCA response packet."""
        if self.socket is not None:
            try:
                print(f"<<< SENDING RESPONSE to {addr[0]}:{addr[1]}: {response.hex()}")
                bytes_sent = self.socket.sendto(response, addr)
                print(f"<<< Sent {bytes_sent} bytes")
            except Exception as e:
                print(f"Failed to send response: {e}")
                import sys
                sys.print_exception(e)

    def blink_led(self):
        """Blink the status LED to indicate activity."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_blink) > 500:
            self.led_state = not self.led_state
            self.led.value(self.led_state)
            self.last_blink = now

    def close_socket(self):
        """Close the UDP socket if open."""
        if self.socket is not None:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None

    def check_network(self) -> bool:
        """Check if network is still connected."""
        if self.nic is None:
            return False
        try:
            # Try to check connection status
            return self.nic.isconnected()
        except:
            return False

    def run(self):
        """Main event loop."""
        print("\n" + "=" * 50)
        print("LifeSize VISCA-IR Bridge Started")
        print("=" * 50 + "\n")

        self.running = True
        last_network_check = time.ticks_ms()
        network_check_interval = 5000  # Check every 5 seconds

        while self.running:
            try:
                # Blink LED
                self.blink_led()

                # Poll scheduler for IR timing
                self.scheduler.poll()

                # Periodically check network status
                now = time.ticks_ms()
                if time.ticks_diff(now, last_network_check) > network_check_interval:
                    last_network_check = now
                    if not self.check_network():
                        print("Network disconnected, attempting reconnect...")
                        self.close_socket()
                        if self.init_network() and self.init_socket():
                            print("Reconnected successfully!")
                        else:
                            print("Reconnect failed, will retry...")
                            time.sleep_ms(1000)
                            continue

                # Check for incoming VISCA commands
                if self.socket is not None:
                    try:
                        data, addr = self.socket.recvfrom(256)
                        if data and len(data) > 0:
                            print(f"\n>>> PACKET RECEIVED: {len(data)} bytes from {addr[0]}:{addr[1]}")
                            print(f">>> Raw data: {data.hex()}")
                            self.process_visca(data, addr)
                    except OSError as e:
                        # No data available (non-blocking) - error code 11 is EAGAIN
                        # Only print if it's not the expected "no data" error
                        if hasattr(e, 'errno') and e.errno != 11:
                            print(f"Socket OSError: {e}")
                        pass
                    except Exception as e:
                        print(f"Socket read error: {e}")

                # Small delay to prevent tight loop
                time.sleep_ms(1)

            except KeyboardInterrupt:
                print("\nShutdown requested...")
                self.running = False
            except Exception as e:
                print(f"Error in main loop: {e}")
                time.sleep_ms(100)

        # Cleanup
        self.shutdown()

    def shutdown(self):
        """Clean shutdown."""
        print("Shutting down...")

        self.scheduler.stop_movement()

        if self.socket is not None:
            self.socket.close()

        self.led.value(0)
        print("Goodbye!")

    def camera_power_on(self):
        """Turn on camera power via relay."""
        print("Powering on camera...")
        self.relay.value(1)
        time.sleep(1)

    def camera_power_off(self):
        """Turn off camera power via relay."""
        print("Powering off camera...")
        self.relay.value(0)


# =============================================================================
# Test Functions
# =============================================================================

def test_ir_commands():
    """Test IR transmission for all commands."""
    print("\n=== IR Command Test ===\n")

    tx = get_transmitter()

    commands = [
        ("UP", IRCommand.UP),
        ("DOWN", IRCommand.DOWN),
        ("LEFT", IRCommand.LEFT),
        ("RIGHT", IRCommand.RIGHT),
        ("ZOOM_IN", IRCommand.ZOOM_IN),
        ("ZOOM_OUT", IRCommand.ZOOM_OUT),
        ("OK", IRCommand.OK),
    ]

    for name, cmd in commands:
        print(f"Testing {name}...")
        tx.test_command(cmd, repeats=3)
        time.sleep(1)

    print("\nIR test complete\n")


def test_continuous_movement(direction: str = "right", duration_sec: int = 3):
    """Test continuous movement in a direction."""
    print(f"\n=== Continuous Movement Test: {direction} for {duration_sec}s ===\n")

    scheduler = get_scheduler()

    dir_map = {
        "up": IRCommand.UP,
        "down": IRCommand.DOWN,
        "left": IRCommand.LEFT,
        "right": IRCommand.RIGHT,
        "zoom_in": IRCommand.ZOOM_IN,
        "zoom_out": IRCommand.ZOOM_OUT,
    }

    if direction.lower() not in dir_map:
        print(f"Unknown direction: {direction}")
        return

    cmd = dir_map[direction.lower()]
    scheduler.start_movement([cmd])

    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < duration_sec * 1000:
        scheduler.poll()
        time.sleep_ms(5)

    scheduler.stop_movement()
    print("\nMovement test complete\n")


def test_diagonal(duration_sec: int = 2):
    """Test diagonal movement."""
    print(f"\n=== Diagonal Movement Test: UP-RIGHT for {duration_sec}s ===\n")

    scheduler = get_scheduler()
    scheduler.start_movement([IRCommand.UP, IRCommand.RIGHT])

    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < duration_sec * 1000:
        scheduler.poll()
        time.sleep_ms(5)

    scheduler.stop_movement()
    print("\nDiagonal test complete\n")


def echo_visca():
    """Echo received VISCA commands without IR output (for debugging)."""
    print("\n=== VISCA Echo Mode ===")
    print("Receiving VISCA commands and printing them")
    print("Press Ctrl+C to stop\n")

    bridge = VISCABridge()

    if not bridge.init_network():
        return

    if not bridge.init_socket():
        return

    parser = VISCAParser()

    try:
        while True:
            bridge.blink_led()

            try:
                data, addr = bridge.socket.recvfrom(256)
                if data and len(data) > 0:
                    print(f"\nFrom {addr[0]}:{addr[1]}:")
                    print(f"  Raw: {data.hex()}")

                    cmd = parser.parse(data)
                    print(f"  Valid: {cmd.valid}")
                    print(f"  Type: {cmd.command_type}")
                    print(f"  IR Commands: {[hex(c) for c in cmd.get_ir_commands()]}")

                    # Send ACK + completion
                    bridge.socket.sendto(VISCAResponse.ack(), addr)
                    bridge.socket.sendto(VISCAResponse.completion(), addr)

            except OSError:
                pass

            time.sleep_ms(10)

    except KeyboardInterrupt:
        print("\nStopped")

    bridge.socket.close()


# =============================================================================
# Main Entry Point
# =============================================================================

def main():
    """Main entry point."""
    print("\n")
    print("=" * 50)
    print("  LifeSize PTZ Camera VISCA-IR Bridge")
    print("  Raspberry Pi Pico 2W + W5500")
    print("=" * 50)
    print("\n")

    # Create and initialize bridge
    bridge = VISCABridge()

    # Continuously retry network initialization
    retry_count = 0
    while True:
        retry_count += 1
        print(f"Network initialization attempt {retry_count}...")

        # Initialize network
        if bridge.init_network():
            # Initialize socket
            if bridge.init_socket():
                print("Network ready!")
                break
            else:
                print("Socket initialization failed, retrying...")
                bridge.close_socket()
        else:
            print("Network initialization failed, retrying...")

        # Blink LED fast to indicate waiting for network
        for _ in range(10):
            bridge.led.toggle()
            time.sleep_ms(200)

        print(f"Waiting 3 seconds before retry...")
        time.sleep_ms(3000)

    # Run main loop
    bridge.run()


if __name__ == "__main__":
    main()
