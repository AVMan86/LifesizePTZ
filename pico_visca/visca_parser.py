"""
VISCA Command Parser for VISCA Pico

Parses VISCA-over-IP commands and maps them to serial commands for the IR Pico.
"""

from protocol import Cmd, IRCode

# Debug flag
DEBUG_VISCA = True


# Pan-Tilt direction mapping to serial commands
# Key: (pan_direction, tilt_direction) from VISCA
# Value: Cmd.START_* constant or None for stop
#
# NOTE: Left/Right are REVERSED for "audience perspective"
# (viewer sees image move in the direction they press)
VISCA_PANTILT_MAP = {
    (0x03, 0x01): Cmd.START_UP,         # Tilt up
    (0x03, 0x02): Cmd.START_DOWN,       # Tilt down
    (0x01, 0x03): Cmd.START_RIGHT,      # Pan left (VISCA) → move RIGHT (reversed)
    (0x02, 0x03): Cmd.START_LEFT,       # Pan right (VISCA) → move LEFT (reversed)
    (0x01, 0x01): Cmd.START_UP_RIGHT,   # Up-left (VISCA) → UP-RIGHT (reversed)
    (0x02, 0x01): Cmd.START_UP_LEFT,    # Up-right (VISCA) → UP-LEFT (reversed)
    (0x01, 0x02): Cmd.START_DOWN_RIGHT, # Down-left (VISCA) → DOWN-RIGHT (reversed)
    (0x02, 0x02): Cmd.START_DOWN_LEFT,  # Down-right (VISCA) → DOWN-LEFT (reversed)
    (0x03, 0x03): None,                 # Stop
}


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
        self.needs_response = False
        self.inquiry_type = None

        # Pan-tilt specific
        self.pan_direction = 0x03
        self.tilt_direction = 0x03

        # Zoom specific
        self.zoom_direction = 0

        # Serial command to send to IR Pico
        self.serial_cmd = None

    def is_stop(self) -> bool:
        """Check if this is a stop command"""
        if self.command_type == VISCACommandType.PAN_TILT:
            return self.pan_direction == 0x03 and self.tilt_direction == 0x03
        elif self.command_type == VISCACommandType.ZOOM:
            return self.zoom_direction == 0x00
        return False

    def get_serial_command(self) -> int:
        """Get the serial command byte to send to IR Pico"""
        return self.serial_cmd


class VISCAParser:
    """Parses VISCA command packets"""

    def parse(self, data: bytes) -> VISCACommand:
        """Parse a VISCA command packet."""
        cmd = VISCACommand()
        cmd.raw_data = data

        if len(data) < 3 or data[-1] != 0xFF:
            return cmd

        addr = data[0]
        if addr == 0x88:
            self._parse_broadcast(data, cmd)
        elif addr == 0x81:
            if len(data) >= 4:
                if data[1] == 0x01:  # Command
                    if data[2] == 0x06:  # Pan-Tilt
                        self._parse_pan_tilt(data, cmd)
                    elif data[2] == 0x04:  # Camera (zoom, focus)
                        self._parse_camera(data, cmd)
                    elif data[2] == 0x00:  # Interface
                        self._parse_interface(data, cmd)
                elif data[1] == 0x09:  # Inquiry
                    self._parse_inquiry(data, cmd)

        return cmd

    def _parse_broadcast(self, data: bytes, cmd: VISCACommand):
        """Parse broadcast commands (address 0x88)"""
        if len(data) >= 5 and data[1] == 0x01 and data[2] == 0x00 and data[3] == 0x01:
            cmd.command_type = VISCACommandType.IF_CLEAR
            cmd.valid = True
            cmd.needs_response = True
        elif len(data) >= 4 and data[1] == 0x30:
            cmd.command_type = VISCACommandType.ADDRESS_SET
            cmd.valid = True
            cmd.needs_response = True

    def _parse_inquiry(self, data: bytes, cmd: VISCACommand):
        """Parse inquiry commands"""
        if len(data) < 5:
            return

        cmd.command_type = VISCACommandType.CAM_INQUIRY
        cmd.valid = True
        cmd.needs_response = True
        cmd.inquiry_type = (data[2], data[3])

        if data[2] == 0x00 and data[3] == 0x02:
            cmd.command_type = VISCACommandType.VERSION_INQ

    def _parse_interface(self, data: bytes, cmd: VISCACommand):
        """Parse interface commands"""
        if len(data) >= 5 and data[3] == 0x01:
            cmd.command_type = VISCACommandType.IF_CLEAR
            cmd.valid = True
            cmd.needs_response = True

    def _parse_pan_tilt(self, data: bytes, cmd: VISCACommand):
        """Parse pan-tilt commands"""
        if len(data) < 9:
            return

        if data[3] == 0x01:  # Pan-Tilt Drive
            cmd.command_type = VISCACommandType.PAN_TILT
            cmd.pan_direction = data[6]
            cmd.tilt_direction = data[7]
            cmd.valid = True

            # Map to serial command
            key = (cmd.pan_direction, cmd.tilt_direction)
            cmd.serial_cmd = VISCA_PANTILT_MAP.get(key)

            if DEBUG_VISCA:
                print(f"VISCA: Pan-Tilt pan={cmd.pan_direction:02X} tilt={cmd.tilt_direction:02X}")

        elif data[3] == 0x04 and len(data) == 5:  # Home
            cmd.command_type = VISCACommandType.PAN_TILT
            cmd.valid = True
            cmd.serial_cmd = Cmd.PRESS_OK

    def _parse_camera(self, data: bytes, cmd: VISCACommand):
        """Parse camera commands (zoom, etc)"""
        if len(data) < 6:
            return

        # OK Button: 81 01 04 3F 02 7F FF
        if data[3] == 0x3F:
            cmd.command_type = VISCACommandType.UNKNOWN
            cmd.valid = True
            cmd.serial_cmd = Cmd.PRESS_OK
            return

        # Zoom: 81 01 04 07 XX FF
        if data[3] == 0x07:
            cmd.command_type = VISCACommandType.ZOOM
            cmd.zoom_direction = data[4]
            cmd.valid = True

            if cmd.zoom_direction == 0x00:  # Stop
                cmd.serial_cmd = None  # Will send STOP
            elif cmd.zoom_direction == 0x02:  # Tele
                cmd.serial_cmd = Cmd.START_ZOOM_IN
            elif cmd.zoom_direction == 0x03:  # Wide
                cmd.serial_cmd = Cmd.START_ZOOM_OUT
            elif (cmd.zoom_direction & 0xF0) == 0x20:  # Variable tele
                cmd.serial_cmd = Cmd.START_ZOOM_IN
            elif (cmd.zoom_direction & 0xF0) == 0x30:  # Variable wide
                cmd.serial_cmd = Cmd.START_ZOOM_OUT

            if DEBUG_VISCA:
                print(f"VISCA: Zoom dir={cmd.zoom_direction:02X}")

    def _parse_power(self, data: bytes, cmd: VISCACommand):
        """Parse power commands"""
        if len(data) >= 6 and data[2] == 0x04 and data[3] == 0x00:
            cmd.command_type = VISCACommandType.POWER
            cmd.valid = True
            power_on = data[4] == 0x02
            cmd.serial_cmd = Cmd.POWER_ON if power_on else Cmd.POWER_OFF


class VISCAResponse:
    """Generates VISCA response packets"""

    @staticmethod
    def ack(socket_num: int = 0) -> bytes:
        return bytes([0x90, 0x40 | socket_num, 0xFF])

    @staticmethod
    def completion(socket_num: int = 0) -> bytes:
        return bytes([0x90, 0x50 | socket_num, 0xFF])

    @staticmethod
    def error(error_code: int, socket_num: int = 0) -> bytes:
        return bytes([0x90, 0x60 | socket_num, error_code, 0xFF])

    @staticmethod
    def address_set() -> bytes:
        return bytes([0x90, 0x30, 0x01, 0xFF])

    @staticmethod
    def if_clear() -> bytes:
        return bytes([0x90, 0x50, 0xFF])

    @staticmethod
    def version_inquiry() -> bytes:
        return bytes([
            0x90, 0x50,
            0x00, 0x20,  # Vendor
            0x04, 0x00,  # Model
            0x00, 0x01,  # ROM version
            0x00, 0x00,
            0xFF
        ])

    @staticmethod
    def power_inquiry(power_on: bool = True) -> bytes:
        return bytes([0x90, 0x50, 0x02 if power_on else 0x03, 0xFF])

    @staticmethod
    def zoom_position(position: int = 0) -> bytes:
        p = (position >> 12) & 0x0F
        q = (position >> 8) & 0x0F
        r = (position >> 4) & 0x0F
        s = position & 0x0F
        return bytes([0x90, 0x50, p, q, r, s, 0xFF])

    @staticmethod
    def pan_tilt_position(pan: int = 0, tilt: int = 0) -> bytes:
        pw = [(pan >> 12) & 0x0F, (pan >> 8) & 0x0F, (pan >> 4) & 0x0F, pan & 0x0F]
        tz = [(tilt >> 12) & 0x0F, (tilt >> 8) & 0x0F, (tilt >> 4) & 0x0F, tilt & 0x0F]
        return bytes([0x90, 0x50] + pw + tz + [0xFF])

    @staticmethod
    def block_inquiry() -> bytes:
        return bytes([0x90, 0x50, 0x00, 0x00, 0x00, 0x00, 0xFF])
