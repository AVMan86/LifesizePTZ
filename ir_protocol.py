"""
LifeSize IR Protocol Encoding

Protocol structure (NEC-like pulse-distance encoding):
- Leader: 2600us mark, 1120us space
- Device code: 8 bits (0x98)
- Device code inverted: 8 bits (0x67)
- Command: 8 bits
- Command inverted: 8 bits
- Stop bit: 560us mark

Bit encoding:
- Mark: always 560us
- Space: 560us for 0, 1680us for 1

All transmitted LSB first within each byte.
"""

from config import (
    LIFESIZE_DEVICE_CODE,
    LIFESIZE_DEVICE_CODE_INV,
    IR_LEADER_MARK_US,
    IR_LEADER_SPACE_US,
    IR_BIT_MARK_US,
    IR_BIT_0_SPACE_US,
    IR_BIT_1_SPACE_US,
    IR_STOP_MARK_US,
)


class LifeSizeProtocol:
    """Encodes commands into LifeSize IR protocol timing sequences"""

    def __init__(self):
        self.device_code = LIFESIZE_DEVICE_CODE
        self.device_code_inv = LIFESIZE_DEVICE_CODE_INV

    def encode_command(self, command_code: int) -> list:
        """
        Encode a command into a sequence of mark/space timings.

        Args:
            command_code: 8-bit command code (e.g., 0x15 for UP)

        Returns:
            List of (mark_us, space_us) tuples representing the IR signal.
            The final tuple has space_us = 0 for the stop bit.
        """
        timings = []

        # Leader pulse
        timings.append((IR_LEADER_MARK_US, IR_LEADER_SPACE_US))

        # Encode device code (LSB first)
        timings.extend(self._encode_byte(self.device_code))

        # Encode inverted device code (LSB first)
        timings.extend(self._encode_byte(self.device_code_inv))

        # Encode command (LSB first)
        timings.extend(self._encode_byte(command_code))

        # Encode inverted command (LSB first)
        command_inv = (~command_code) & 0xFF
        timings.extend(self._encode_byte(command_inv))

        # Stop bit (mark only, no trailing space)
        timings.append((IR_STOP_MARK_US, 0))

        return timings

    def _encode_byte(self, byte_val: int) -> list:
        """
        Encode a single byte as mark/space pairs (LSB first).

        Args:
            byte_val: 8-bit value to encode

        Returns:
            List of 8 (mark_us, space_us) tuples
        """
        timings = []
        for i in range(8):
            bit = (byte_val >> i) & 1
            if bit:
                timings.append((IR_BIT_MARK_US, IR_BIT_1_SPACE_US))
            else:
                timings.append((IR_BIT_MARK_US, IR_BIT_0_SPACE_US))
        return timings

    def get_raw_pulses(self, command_code: int) -> tuple:
        """
        Get the raw pulse sequence as separate mark and space arrays.

        This format is useful for PIO transmission where we need
        separate timing values.

        Args:
            command_code: 8-bit command code

        Returns:
            Tuple of (marks_us, spaces_us) as lists of microsecond values
        """
        timings = self.encode_command(command_code)
        marks = [t[0] for t in timings]
        spaces = [t[1] for t in timings]
        return marks, spaces

    def get_pulse_train(self, command_code: int) -> list:
        """
        Get the complete pulse train as alternating mark/space values.

        Starts with mark, alternates mark/space/mark/space...
        This format is useful for direct timing control.

        Args:
            command_code: 8-bit command code

        Returns:
            List of microsecond values, alternating mark/space
        """
        timings = self.encode_command(command_code)
        train = []
        for mark, space in timings:
            train.append(mark)
            if space > 0:  # Don't add trailing zero space
                train.append(space)
        return train

    def calculate_frame_duration(self, command_code: int) -> int:
        """
        Calculate the total duration of an IR frame in microseconds.

        Args:
            command_code: 8-bit command code

        Returns:
            Total frame duration in microseconds
        """
        timings = self.encode_command(command_code)
        total = sum(mark + space for mark, space in timings)
        return total

    def verify_encoding(self, command_code: int) -> dict:
        """
        Verify the encoding of a command and return diagnostic info.

        Args:
            command_code: 8-bit command code

        Returns:
            Dictionary with encoding details
        """
        timings = self.encode_command(command_code)
        frame_us = self.calculate_frame_duration(command_code)

        return {
            "command": hex(command_code),
            "command_inv": hex((~command_code) & 0xFF),
            "device": hex(self.device_code),
            "device_inv": hex(self.device_code_inv),
            "num_pulses": len(timings),
            "frame_duration_us": frame_us,
            "frame_duration_ms": frame_us / 1000,
            "total_bits": 32,  # 8+8+8+8 bits
        }


# Pre-instantiate for convenience
protocol = LifeSizeProtocol()


def encode_ir_command(command_code: int) -> list:
    """Convenience function to encode a command."""
    return protocol.encode_command(command_code)


def get_pulse_train(command_code: int) -> list:
    """Convenience function to get pulse train."""
    return protocol.get_pulse_train(command_code)


# Test/demonstration code
if __name__ == "__main__":
    from config import IRCommand

    print("LifeSize IR Protocol Encoder Test")
    print("=" * 50)

    # Test encoding UP command
    cmd = IRCommand.UP
    info = protocol.verify_encoding(cmd)

    print(f"\nCommand: UP (0x{cmd:02X})")
    print(f"Device code: {info['device']} / {info['device_inv']}")
    print(f"Command: {info['command']} / {info['command_inv']}")
    print(f"Frame duration: {info['frame_duration_ms']:.2f}ms")
    print(f"Number of pulses: {info['num_pulses']}")

    # Show first few timings
    timings = protocol.encode_command(cmd)
    print(f"\nFirst 5 mark/space pairs:")
    for i, (mark, space) in enumerate(timings[:5]):
        print(f"  {i}: mark={mark}us, space={space}us")

    # Calculate expected frame time for all commands
    print(f"\nFrame durations for all commands:")
    for name in ["UP", "DOWN", "LEFT", "RIGHT", "ZOOM_IN", "ZOOM_OUT"]:
        cmd = getattr(IRCommand, name)
        duration = protocol.calculate_frame_duration(cmd)
        print(f"  {name}: {duration}us ({duration/1000:.2f}ms)")
