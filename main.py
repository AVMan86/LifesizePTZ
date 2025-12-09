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
            time.sleep_ms(100)

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

            # Configure static IP
            self.nic.ifconfig((
                BRIDGE_IP,
                BRIDGE_SUBNET,
                BRIDGE_GATEWAY,
                BRIDGE_DNS
            ))

            # Wait for link
            print("Waiting for Ethernet link...")
            timeout = 50  # 5 seconds
            while not self.nic.isconnected() and timeout > 0:
                time.sleep_ms(100)
                timeout -= 1

            if not self.nic.isconnected():
                print("ERROR: Ethernet link not detected")
                return False

            # Print configuration
            config = self.nic.ifconfig()
            print(f"Network initialized:")
            print(f"  IP Address: {config[0]}")
            print(f"  Subnet:     {config[1]}")
            print(f"  Gateway:    {config[2]}")
            print(f"  DNS:        {config[3]}")

            return True

        except ImportError:
            print("ERROR: network module not available")
            print("Make sure you're using MicroPython with W5500 support")
            return False
        except Exception as e:
            print(f"ERROR: Network initialization failed: {e}")
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
            self.socket.bind(('', VISCA_PORT))
            self.socket.setblocking(False)

            print(f"Listening for VISCA commands on {BRIDGE_IP}:{VISCA_PORT}")
            return True

        except Exception as e:
            print(f"ERROR: Socket initialization failed: {e}")
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

        # Send ACK immediately
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

    def _send_response(self, response: bytes, addr: tuple):
        """Send a VISCA response packet."""
        if self.socket is not None:
            try:
                self.socket.sendto(response, addr)
                if DEBUG_VISCA:
                    print(f"VISCA response: {response.hex()}")
            except Exception as e:
                print(f"Failed to send response: {e}")

    def blink_led(self):
        """Blink the status LED to indicate activity."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_blink) > 500:
            self.led_state = not self.led_state
            self.led.value(self.led_state)
            self.last_blink = now

    def run(self):
        """Main event loop."""
        print("\n" + "=" * 50)
        print("LifeSize VISCA-IR Bridge Started")
        print("=" * 50 + "\n")

        self.running = True
        recv_buffer = bytearray(256)

        while self.running:
            try:
                # Blink LED
                self.blink_led()

                # Poll scheduler for IR timing
                self.scheduler.poll()

                # Check for incoming VISCA commands
                if self.socket is not None:
                    try:
                        nbytes, addr = self.socket.recvfrom_into(recv_buffer)
                        if nbytes > 0:
                            self.process_visca(bytes(recv_buffer[:nbytes]), addr)
                    except OSError:
                        # No data available (non-blocking)
                        pass

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
        tx.test_command(cmd, repeats=3, gap_ms=57)
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
    recv_buffer = bytearray(256)

    try:
        while True:
            bridge.blink_led()

            try:
                nbytes, addr = bridge.socket.recvfrom_into(recv_buffer)
                if nbytes > 0:
                    data = bytes(recv_buffer[:nbytes])
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

    # Initialize network
    if not bridge.init_network():
        print("\nNetwork initialization failed!")
        print("Check W5500 connections and try again.")
        return

    # Initialize socket
    if not bridge.init_socket():
        print("\nSocket initialization failed!")
        return

    # Run main loop
    bridge.run()


if __name__ == "__main__":
    main()
