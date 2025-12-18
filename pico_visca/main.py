"""
VISCA Pico - Network Handler for LifeSize Camera Bridge

This Pico handles all network complexity:
- W5500 Ethernet communication
- VISCA command parsing
- Sending simple commands to IR Pico via UART

No timing-critical code here - the IR Pico handles all IR timing.

Wiring:
- GP0 (TX) → Pico #2 GP1 (RX)
- GP1 (RX) ← Pico #2 GP0 (TX)
- GP2-GP6 → W5500 SPI
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


class IRPicoLink:
    """
    Communication link to the IR Pico via UART.

    Sends simple command bytes, receives ACK responses.
    """

    def __init__(self):
        self.uart = UART(0, baudrate=UART_BAUD,
                        tx=Pin(UART_TX_PIN), rx=Pin(UART_RX_PIN))
        self.uart.init(bits=8, parity=None, stop=1)
        print(f"UART link initialized: {UART_BAUD} baud")

    def send_command(self, cmd: int) -> bool:
        """
        Send a command to the IR Pico.

        Returns True if ACK received, False otherwise.
        """
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

    def power_on(self):
        """Power on camera (relay + OK sequence)."""
        self.send_command(Cmd.POWER_ON)

    def power_off(self):
        """Power off camera."""
        self.send_command(Cmd.POWER_OFF)

    def ping(self) -> bool:
        """Check if IR Pico is responding."""
        self.uart.write(bytes([Cmd.PING]))
        start = time.ticks_ms()
        while time.ticks_diff(time.ticks_ms(), start) < 100:
            if self.uart.any():
                resp = self.uart.read(1)
                if resp and resp[0] == Resp.PONG:
                    return True
            time.sleep_ms(1)
        return False


class VISCABridge:
    """
    VISCA-over-IP to Serial Bridge.

    Receives VISCA commands via UDP and translates them to
    simple serial commands for the IR Pico.
    """

    def __init__(self):
        self.led = Pin(PIN_LED, Pin.OUT)
        self.parser = VISCAParser()
        self.ir_link = IRPicoLink()
        self.nic = None
        self.socket = None
        self.running = False
        self.last_blink = 0

        # Track movement state to avoid redundant commands
        self.current_movement = None

    def init_network(self) -> bool:
        """Initialize W5500 Ethernet."""
        print("Initializing W5500 Ethernet...")

        try:
            import network

            # Reset W5500
            rst_pin = Pin(PIN_W5500_RST, Pin.OUT)
            rst_pin.value(0)
            time.sleep_ms(100)
            rst_pin.value(1)
            time.sleep_ms(500)

            # Configure SPI
            spi = SPI(0, baudrate=10_000_000, polarity=0, phase=0,
                     sck=Pin(PIN_SPI_SCK),
                     mosi=Pin(PIN_SPI_MOSI),
                     miso=Pin(PIN_SPI_MISO))
            cs_pin = Pin(PIN_SPI_CS, Pin.OUT, value=1)

            # Initialize W5500
            self.nic = network.WIZNET5K(spi, cs_pin, rst_pin)
            self.nic.active(True)

            # Configure static IP
            self.nic.ifconfig((BRIDGE_IP, BRIDGE_SUBNET, BRIDGE_GATEWAY, BRIDGE_DNS))

            # Wait for link
            for _ in range(50):
                if self.nic.isconnected():
                    break
                time.sleep_ms(100)

            config = self.nic.ifconfig()
            print(f"Network ready: {config[0]}")
            return True

        except Exception as e:
            print(f"Network error: {e}")
            return False

    def init_socket(self) -> bool:
        """Initialize UDP socket."""
        try:
            import socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind((BRIDGE_IP, VISCA_PORT))
            self.socket.setblocking(False)
            print(f"Listening on {BRIDGE_IP}:{VISCA_PORT} (UDP)")
            return True
        except Exception as e:
            print(f"Socket error: {e}")
            return False

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

    def blink_led(self):
        """Blink status LED."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self.last_blink) > 500:
            self.led.toggle()
            self.last_blink = now

    def run(self):
        """Main event loop."""
        print("\n" + "=" * 50)
        print("VISCA Pico - Network Handler")
        print("=" * 50)

        # Check IR Pico connection
        print("Checking IR Pico connection...")
        if self.ir_link.ping():
            print("IR Pico: Connected!")
        else:
            print("WARNING: IR Pico not responding")

        self.running = True

        while self.running:
            try:
                self.blink_led()

                # Check for VISCA commands
                if self.socket:
                    try:
                        data, addr = self.socket.recvfrom(256)
                        if data:
                            self.process_visca(data, addr)
                    except OSError:
                        pass  # No data (non-blocking)

                time.sleep_ms(1)

            except KeyboardInterrupt:
                print("\nShutdown...")
                self.running = False

        self.ir_link.stop_movement()
        if self.socket:
            self.socket.close()
        self.led.value(0)


def main():
    print("\n")
    print("=" * 50)
    print("  VISCA Pico - LifeSize Camera Bridge")
    print("  Network Handler")
    print("=" * 50)

    bridge = VISCABridge()

    # Retry network initialization
    while True:
        if bridge.init_network() and bridge.init_socket():
            break
        print("Retrying in 3 seconds...")
        for _ in range(6):
            bridge.led.toggle()
            time.sleep_ms(500)

    bridge.run()


if __name__ == "__main__":
    main()
