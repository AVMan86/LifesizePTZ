"""
VISCA Command Parser

Parses VISCA-over-IP commands and extracts camera control instructions.

VISCA packet structure:
- Byte 0: 0x81 (address byte - camera 1) or 0x88 (broadcast)
- Byte 1: 0x01 (command) or 0x09 (inquiry)
- Byte 2+: Command category and parameters
- Final byte: 0xFF (terminator)

Supported commands:
- Pan-Tilt drive: 81 01 06 01 VV WW PP TT FF
- Pan-Tilt stop:  81 01 06 01 VV WW 03 03 FF
- Zoom tele:      81 01 04 07 02 FF
- Zoom wide:      81 01 04 07 03 FF
- Zoom stop:      81 01 04 07 00 FF
- IF_Clear:       88 01 00 01 FF (broadcast)
- AddressSet:     88 30 01 FF (broadcast)
- CAM_VersionInq: 81 09 00 02 FF
"""

from config import IRCommand, VISCA_PANTILT_MAP, DEBUG_VISCA


# =============================================================================
# VISCA Command Types
# =============================================================================

class VISCACommandType:
    """Types of VISCA commands we recognize"""
    UNKNOWN = 0
    PAN_TILT = 1
    ZOOM = 2
    FOCUS = 3
    POWER = 4
    PRESET = 5
    INQUIRY = 6
    IF_CLEAR = 7
    ADDRESS_SET = 8
    VERSION_INQ = 9
    CAM_INQUIRY = 10


class VISCACommand:
    """Represents a parsed VISCA command"""

    def __init__(self):
        self.raw_data = None
        self.command_type = VISCACommandType.UNKNOWN
        self.valid = False
        self.needs_response = False  # True if this requires a special response
        self.inquiry_type = None     # For inquiry commands

        # Pan-tilt specific
        self.pan_speed = 0
        self.tilt_speed = 0
        self.pan_direction = 0x03  # 01=left, 02=right, 03=stop
        self.tilt_direction = 0x03  # 01=up, 02=down, 03=stop

        # Zoom specific
        self.zoom_direction = 0  # 02=tele(in), 03=wide(out), 00=stop
        self.zoom_speed = 0

        # IR command mapping
        self.ir_commands = []  # List of IR commands to execute

    def __repr__(self):
        if self.command_type == VISCACommandType.PAN_TILT:
            return f"VISCACommand(pan_tilt, pan={self.pan_direction}, tilt={self.tilt_direction})"
        elif self.command_type == VISCACommandType.ZOOM:
            return f"VISCACommand(zoom, dir={self.zoom_direction})"
        else:
            return f"VISCACommand(type={self.command_type})"

    def is_stop(self) -> bool:
        """Check if this is a stop command"""
        if self.command_type == VISCACommandType.PAN_TILT:
            return self.pan_direction == 0x03 and self.tilt_direction == 0x03
        elif self.command_type == VISCACommandType.ZOOM:
            return self.zoom_direction == 0x00
        return False

    def get_ir_commands(self) -> list:
        """Get the IR command(s) for this VISCA command"""
        return self.ir_commands


# =============================================================================
# VISCA Parser
# =============================================================================

class VISCAParser:
    """Parses VISCA command packets"""

    def __init__(self):
        self.last_command = None

    def parse(self, data: bytes) -> VISCACommand:
        """
        Parse a VISCA command packet.

        Args:
            data: Raw bytes of the VISCA packet

        Returns:
            VISCACommand object with parsed data
        """
        cmd = VISCACommand()
        cmd.raw_data = data

        if len(data) < 3:
            if DEBUG_VISCA:
                print(f"VISCA: Packet too short ({len(data)} bytes)")
            return cmd

        if data[-1] != 0xFF:
            if DEBUG_VISCA:
                print(f"VISCA: Missing terminator, last byte: 0x{data[-1]:02X}")
            return cmd

        # Check address byte
        addr = data[0]
        if addr == 0x88:
            # Broadcast command
            self._parse_broadcast(data, cmd)
        elif addr == 0x81:
            # Camera 1 command
            if len(data) >= 4:
                if data[1] == 0x01:  # Command
                    if data[2] == 0x06:  # Pan-Tilt category
                        self._parse_pan_tilt(data, cmd)
                    elif data[2] == 0x04:  # Camera category (zoom, focus)
                        self._parse_camera(data, cmd)
                    elif data[2] == 0x00:  # Interface/Power
                        self._parse_interface(data, cmd)
                elif data[1] == 0x09:  # Inquiry
                    self._parse_inquiry(data, cmd)
        else:
            if DEBUG_VISCA:
                print(f"VISCA: Unknown address byte: 0x{addr:02X}")

        if DEBUG_VISCA and cmd.valid:
            print(f"VISCA: Parsed {cmd}")

        self.last_command = cmd
        return cmd

    def _parse_broadcast(self, data: bytes, cmd: VISCACommand):
        """Parse broadcast commands (address 0x88)"""
        if len(data) < 4:
            return

        # IF_Clear: 88 01 00 01 FF
        if len(data) >= 5 and data[1] == 0x01 and data[2] == 0x00 and data[3] == 0x01:
            cmd.command_type = VISCACommandType.IF_CLEAR
            cmd.valid = True
            cmd.needs_response = True
            if DEBUG_VISCA:
                print("VISCA: IF_Clear (interface clear)")
            return

        # Address Set: 88 30 01 FF
        if len(data) >= 4 and data[1] == 0x30:
            cmd.command_type = VISCACommandType.ADDRESS_SET
            cmd.valid = True
            cmd.needs_response = True
            if DEBUG_VISCA:
                print("VISCA: AddressSet command")
            return

        if DEBUG_VISCA:
            print(f"VISCA: Unknown broadcast command: {data.hex()}")

    def _parse_inquiry(self, data: bytes, cmd: VISCACommand):
        """Parse inquiry commands (81 09 xx xx FF)"""
        if len(data) < 5:
            return

        cmd.command_type = VISCACommandType.CAM_INQUIRY
        cmd.valid = True
        cmd.needs_response = True
        cmd.inquiry_type = (data[2], data[3])

        # CAM_VersionInq: 81 09 00 02 FF
        if data[2] == 0x00 and data[3] == 0x02:
            cmd.command_type = VISCACommandType.VERSION_INQ
            if DEBUG_VISCA:
                print("VISCA: CAM_VersionInq")
        # CAM_PowerInq: 81 09 04 00 FF
        elif data[2] == 0x04 and data[3] == 0x00:
            if DEBUG_VISCA:
                print("VISCA: CAM_PowerInq")
        # CAM_ZoomPosInq: 81 09 04 47 FF
        elif data[2] == 0x04 and data[3] == 0x47:
            if DEBUG_VISCA:
                print("VISCA: CAM_ZoomPosInq")
        # Pan-Tilt Position Inq: 81 09 06 12 FF
        elif data[2] == 0x06 and data[3] == 0x12:
            if DEBUG_VISCA:
                print("VISCA: Pan-TiltPosInq")
        else:
            if DEBUG_VISCA:
                print(f"VISCA: Inquiry {data[2]:02X} {data[3]:02X}")

    def _parse_interface(self, data: bytes, cmd: VISCACommand):
        """Parse interface commands (81 01 00 xx FF)"""
        if len(data) < 5:
            return

        # IF_Clear for single camera: 81 01 00 01 FF
        if data[3] == 0x01:
            cmd.command_type = VISCACommandType.IF_CLEAR
            cmd.valid = True
            cmd.needs_response = True
            if DEBUG_VISCA:
                print("VISCA: IF_Clear (single)")
            return

        # Could be power command routed here incorrectly
        self._parse_power(data, cmd)

    def _parse_pan_tilt(self, data: bytes, cmd: VISCACommand):
        """Parse pan-tilt commands"""
        if len(data) < 9:
            return

        # Pan-Tilt Drive: 81 01 06 01 VV WW PP TT FF
        if data[3] == 0x01:
            cmd.command_type = VISCACommandType.PAN_TILT
            cmd.pan_speed = data[4]
            cmd.tilt_speed = data[5]
            cmd.pan_direction = data[6]
            cmd.tilt_direction = data[7]
            cmd.valid = True

            # Map to IR commands
            key = (cmd.pan_direction, cmd.tilt_direction)
            if key in VISCA_PANTILT_MAP:
                mapping = VISCA_PANTILT_MAP[key]
                if mapping is None:
                    # Stop command
                    cmd.ir_commands = []
                elif isinstance(mapping, tuple):
                    # Diagonal - two commands
                    cmd.ir_commands = list(mapping)
                else:
                    # Single command
                    cmd.ir_commands = [mapping]

            if DEBUG_VISCA:
                dirs = {0x01: "left/up", 0x02: "right/down", 0x03: "stop"}
                pan_str = dirs.get(cmd.pan_direction, "?")
                tilt_str = dirs.get(cmd.tilt_direction, "?")
                print(f"VISCA: Pan-Tilt pan={pan_str} tilt={tilt_str}")
                print(f"VISCA: IR commands: {[hex(c) for c in cmd.ir_commands]}")

        # Pan-Tilt Home: 81 01 06 04 FF
        elif data[3] == 0x04 and len(data) == 5:
            cmd.command_type = VISCACommandType.PAN_TILT
            cmd.valid = True
            # Home might be OK button? Need to test
            cmd.ir_commands = [IRCommand.OK]
            if DEBUG_VISCA:
                print("VISCA: Pan-Tilt Home command")

    def _parse_camera(self, data: bytes, cmd: VISCACommand):
        """Parse camera commands (zoom, focus, etc)"""
        if len(data) < 6:
            return

        # Zoom: 81 01 04 07 XX FF
        if data[3] == 0x07:
            cmd.command_type = VISCACommandType.ZOOM
            cmd.zoom_direction = data[4]
            cmd.valid = True

            # Map zoom direction to IR command
            if cmd.zoom_direction == 0x00:  # Stop
                cmd.ir_commands = []
            elif cmd.zoom_direction == 0x02:  # Tele (zoom in)
                cmd.ir_commands = [IRCommand.ZOOM_IN]
            elif cmd.zoom_direction == 0x03:  # Wide (zoom out)
                cmd.ir_commands = [IRCommand.ZOOM_OUT]
            elif (cmd.zoom_direction & 0xF0) == 0x20:  # Variable speed tele: 2p
                cmd.zoom_speed = cmd.zoom_direction & 0x0F
                cmd.zoom_direction = 0x02
                cmd.ir_commands = [IRCommand.ZOOM_IN]
            elif (cmd.zoom_direction & 0xF0) == 0x30:  # Variable speed wide: 3p
                cmd.zoom_speed = cmd.zoom_direction & 0x0F
                cmd.zoom_direction = 0x03
                cmd.ir_commands = [IRCommand.ZOOM_OUT]

            if DEBUG_VISCA:
                zoom_dirs = {0x00: "stop", 0x02: "tele", 0x03: "wide"}
                zd = zoom_dirs.get(cmd.zoom_direction, f"0x{cmd.zoom_direction:02X}")
                print(f"VISCA: Zoom {zd} speed={cmd.zoom_speed}")

    def _parse_power(self, data: bytes, cmd: VISCACommand):
        """Parse power commands"""
        if len(data) < 5:
            return

        # Power: 81 01 04 00 XX FF
        if len(data) >= 6 and data[2] == 0x04 and data[3] == 0x00:
            cmd.command_type = VISCACommandType.POWER
            cmd.valid = True
            power_state = data[4]  # 02=on, 03=off
            if DEBUG_VISCA:
                print(f"VISCA: Power {'on' if power_state == 0x02 else 'off'}")


# =============================================================================
# VISCA Response Generator
# =============================================================================

class VISCAResponse:
    """Generates VISCA response packets"""

    @staticmethod
    def ack(socket_num: int = 0) -> bytes:
        """Generate ACK response"""
        return bytes([0x90, 0x40 | socket_num, 0xFF])

    @staticmethod
    def completion(socket_num: int = 0) -> bytes:
        """Generate command completion response"""
        return bytes([0x90, 0x50 | socket_num, 0xFF])

    @staticmethod
    def error(error_code: int, socket_num: int = 0) -> bytes:
        """Generate error response"""
        return bytes([0x90, 0x60 | socket_num, error_code, 0xFF])

    @staticmethod
    def ack_completion(socket_num: int = 0) -> tuple:
        """Generate both ACK and completion responses"""
        return (
            VISCAResponse.ack(socket_num),
            VISCAResponse.completion(socket_num)
        )

    @staticmethod
    def address_set() -> bytes:
        """
        Response to AddressSet broadcast command.
        Returns network change response: 88 30 01 FF -> 90 30 01 FF
        (Camera at address 1)
        """
        return bytes([0x90, 0x30, 0x01, 0xFF])

    @staticmethod
    def if_clear() -> bytes:
        """
        Response to IF_Clear command.
        Just send completion.
        """
        return bytes([0x90, 0x50, 0xFF])

    @staticmethod
    def version_inquiry() -> bytes:
        """
        Response to CAM_VersionInq (81 09 00 02 FF)
        Returns: 90 50 VV VV VV VV RR RR SS SS FF
        - VVVV = Vendor ID (Sony = 0020)
        - RRRR = Model code
        - SSSS = ROM version
        We'll fake a generic PTZ camera response.
        """
        return bytes([
            0x90, 0x50,
            0x00, 0x20,  # Vendor ID (Sony-compatible)
            0x04, 0x00,  # Model code (generic PTZ)
            0x00, 0x01,  # ROM version 0.1
            0x00, 0x00,  # Socket number / max
            0xFF
        ])

    @staticmethod
    def power_inquiry(power_on: bool = True) -> bytes:
        """
        Response to CAM_PowerInq (81 09 04 00 FF)
        Returns: 90 50 02 FF (on) or 90 50 03 FF (off)
        """
        return bytes([0x90, 0x50, 0x02 if power_on else 0x03, 0xFF])

    @staticmethod
    def zoom_position(position: int = 0) -> bytes:
        """
        Response to CAM_ZoomPosInq (81 09 04 47 FF)
        Returns: 90 50 0p 0q 0r 0s FF where pqrs is position
        """
        p = (position >> 12) & 0x0F
        q = (position >> 8) & 0x0F
        r = (position >> 4) & 0x0F
        s = position & 0x0F
        return bytes([0x90, 0x50, p, q, r, s, 0xFF])

    @staticmethod
    def pan_tilt_position(pan: int = 0, tilt: int = 0) -> bytes:
        """
        Response to Pan-TiltPosInq (81 09 06 12 FF)
        Returns: 90 50 0w 0w 0w 0w 0z 0z 0z 0z FF
        """
        pw = [(pan >> 12) & 0x0F, (pan >> 8) & 0x0F, (pan >> 4) & 0x0F, pan & 0x0F]
        tz = [(tilt >> 12) & 0x0F, (tilt >> 8) & 0x0F, (tilt >> 4) & 0x0F, tilt & 0x0F]
        return bytes([0x90, 0x50] + pw + tz + [0xFF])


# Error codes
class VISCAError:
    SYNTAX = 0x02
    BUFFER_FULL = 0x03
    CANCELLED = 0x04
    NO_SOCKET = 0x05
    NOT_EXECUTABLE = 0x41


# =============================================================================
# Convenience functions
# =============================================================================

_parser = None


def get_parser() -> VISCAParser:
    """Get or create the default parser instance"""
    global _parser
    if _parser is None:
        _parser = VISCAParser()
    return _parser


def parse_visca(data: bytes) -> VISCACommand:
    """Convenience function to parse a VISCA packet"""
    return get_parser().parse(data)


# =============================================================================
# Test code
# =============================================================================

if __name__ == "__main__":
    print("VISCA Parser Test")
    print("=" * 50)

    parser = VISCAParser()

    # Test packets
    test_packets = [
        ("Pan Up", bytes([0x81, 0x01, 0x06, 0x01, 0x10, 0x10, 0x03, 0x01, 0xFF])),
        ("Pan Down", bytes([0x81, 0x01, 0x06, 0x01, 0x10, 0x10, 0x03, 0x02, 0xFF])),
        ("Pan Left", bytes([0x81, 0x01, 0x06, 0x01, 0x10, 0x10, 0x01, 0x03, 0xFF])),
        ("Pan Right", bytes([0x81, 0x01, 0x06, 0x01, 0x10, 0x10, 0x02, 0x03, 0xFF])),
        ("Pan Stop", bytes([0x81, 0x01, 0x06, 0x01, 0x10, 0x10, 0x03, 0x03, 0xFF])),
        ("Zoom In", bytes([0x81, 0x01, 0x04, 0x07, 0x02, 0xFF])),
        ("Zoom Out", bytes([0x81, 0x01, 0x04, 0x07, 0x03, 0xFF])),
        ("Zoom Stop", bytes([0x81, 0x01, 0x04, 0x07, 0x00, 0xFF])),
        ("Diagonal Up-Left", bytes([0x81, 0x01, 0x06, 0x01, 0x10, 0x10, 0x01, 0x01, 0xFF])),
    ]

    for name, packet in test_packets:
        print(f"\n{name}:")
        print(f"  Raw: {packet.hex()}")
        cmd = parser.parse(packet)
        print(f"  Valid: {cmd.valid}")
        print(f"  Type: {cmd.command_type}")
        print(f"  Is Stop: {cmd.is_stop()}")
        print(f"  IR Commands: {[hex(c) for c in cmd.get_ir_commands()]}")

    print("\n" + "=" * 50)
    print("VISCA Response Test")

    print(f"ACK: {VISCAResponse.ack().hex()}")
    print(f"Completion: {VISCAResponse.completion().hex()}")
    print(f"Error: {VISCAResponse.error(VISCAError.SYNTAX).hex()}")
