"""
LifeSize IR Protocol Utilities

Protocol structure (16-bit pulse-distance encoding):
- Header: 2550us mark, 2500us space
- Data: 16 bits MSB first as (device_code << 8 | command)
- Stop: 1200us mark

Device code: 0x98
Bit encoding: 1200us mark, then 1050us (0) or 2825us (1) space
"""

from config import (
    LIFESIZE_DEVICE_CODE,
    IR_HEADER_MARK_US,
    IR_HEADER_SPACE_US,
    IR_BIT_MARK_US,
    IR_BIT_0_SPACE_US,
    IR_BIT_1_SPACE_US,
    IR_STOP_MARK_US,
    IR_PACKET_GAP_US,
    IRCommand,
)


def build_code(command: int) -> int:
    """
    Build the 16-bit IR code from a command.

    Args:
        command: 8-bit command code (e.g., 0x15 for UP)

    Returns:
        16-bit code as (device_code << 8 | command)
    """
    return (LIFESIZE_DEVICE_CODE << 8) | (command & 0xFF)


def calculate_frame_duration() -> int:
    """
    Calculate the duration of a single IR frame in microseconds.

    Returns:
        Frame duration in microseconds
    """
    # Header
    duration = IR_HEADER_MARK_US + IR_HEADER_SPACE_US

    # 16 data bits (average of 0s and 1s for estimate)
    avg_space = (IR_BIT_0_SPACE_US + IR_BIT_1_SPACE_US) // 2
    duration += 16 * (IR_BIT_MARK_US + avg_space)

    # Stop bit
    duration += IR_STOP_MARK_US

    return duration


def print_protocol_info():
    """Print protocol timing information for debugging."""
    print("LifeSize IR Protocol")
    print("=" * 40)
    print(f"Device code: 0x{LIFESIZE_DEVICE_CODE:02X}")
    print(f"Header: {IR_HEADER_MARK_US}us mark, {IR_HEADER_SPACE_US}us space")
    print(f"Bit mark: {IR_BIT_MARK_US}us")
    print(f"Bit 0 space: {IR_BIT_0_SPACE_US}us")
    print(f"Bit 1 space: {IR_BIT_1_SPACE_US}us")
    print(f"Stop mark: {IR_STOP_MARK_US}us")
    print(f"Packet gap: {IR_PACKET_GAP_US}us ({IR_PACKET_GAP_US/1000:.2f}ms)")
    print(f"Estimated frame: ~{calculate_frame_duration()}us")

    print("\nCommand codes:")
    for name in ["UP", "DOWN", "LEFT", "RIGHT", "ZOOM_IN", "ZOOM_OUT", "OK"]:
        if hasattr(IRCommand, name):
            cmd = getattr(IRCommand, name)
            code = build_code(cmd)
            print(f"  {name}: 0x{cmd:02X} -> 0x{code:04X}")


if __name__ == "__main__":
    print_protocol_info()
