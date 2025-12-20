# CLAUDE.md - Project Context for AI Assistants

## Project Overview

This is a **VISCA-over-IP to IR bridge** for controlling a LifeSize 10x PTZ camera. The camera only accepts IR remote commands, but we want to control it via standard VISCA protocol over Ethernet from PTZ controller software.

## Architecture: Two-Pico Design

The system uses **two Raspberry Pi Pico 2W** boards connected via UART:

```
┌─────────────────┐     UART     ┌─────────────────┐
│   VISCA Pico    │◄────────────►│    IR Pico      │
│   (pico_visca/) │  115200 8N1  │   (pico_ir/)    │
├─────────────────┤              ├─────────────────┤
│ • W5500 Ethernet│              │ • IR LED @ GP15 │
│ • VISCA parsing │              │ • 38kHz PWM     │
│ • Relay @ GP7   │              │ • 57.3ms timing │
│ • Static IP     │              │ • Camera init   │
└─────────────────┘              └─────────────────┘
```

**Why two Picos?** The IR protocol requires precise 57.325ms gaps between frames for smooth camera movement. Network/SPI operations cause timing jitter. The dedicated IR Pico handles only timing-critical IR transmission.

## Key Technical Details

### IR Protocol (LifeSize)
- **Carrier**: 38kHz
- **Encoding**: Pulse-distance (NEC-like but different timing)
- **Header**: 2550µs mark, 2500µs space
- **Bits**: 1200µs mark, then 1050µs (0) or 2825µs (1) space
- **Frame**: 16-bit (device code 0x98 + command code)
- **Critical**: 57.325ms gap between frames for smooth movement

### UART Protocol (between Picos)
- **Baud**: 115200, 8N1
- **Commands**: Single bytes (see `protocol.py`)
  - 0x01-0x0A: Start movements (up, down, left, right, diagonals, zoom)
  - 0x10: Stop
  - 0x20: OK button (enables IR mode on camera)
- **Responses**: ACK (0x06), ERROR (0x15)

### Network Configuration
- **IP**: 192.168.5.177 (configurable in `pico_visca/config.py`)
- **Port**: 52381 UDP (VISCA standard)
- Left/Right are **reversed** for "audience perspective" (operator sees image move in direction pressed)

### Relay Control
- VISCA Pico controls a relay on GP7
- Relay enables when Ethernet link is stable
- Used to power the camera on/off

## File Structure

```
LifesizePTZ_12-2025/
├── pico_visca/           # VISCA Pico code (network handler)
│   ├── main.py           # Network init, VISCA handling, UART TX
│   ├── config.py         # IP address, pin definitions
│   ├── visca_parser.py   # VISCA command parsing
│   └── protocol.py       # UART command definitions
│
├── pico_ir/              # IR Pico code (timing-critical)
│   ├── main.py           # IR transmission, UART RX
│   ├── protocol.py       # Same as pico_visca (shared)
│   └── test_ir.py        # Manual keyboard testing
│
├── ptz_controller.py     # PC-side GUI controller
└── README.md             # User documentation
```

## Common Modifications

### Change IP Address
Edit `pico_visca/config.py`:
```python
BRIDGE_IP = "192.168.5.177"
BRIDGE_SUBNET = "255.255.255.0"
BRIDGE_GATEWAY = "192.168.5.1"
```

### Change IR Timing
Edit `pico_ir/protocol.py` - the `IR_PACKET_GAP_US` value (57325µs) is critical for smooth movement.

### Reverse Pan Direction
Edit `pico_visca/visca_parser.py` - swap LEFT/RIGHT in `VISCA_PANTILT_MAP`.

### Add New IR Commands
1. Add code to `IRCode` class in `protocol.py`
2. Add command byte to `Cmd` class in `protocol.py`
3. Handle in IR Pico's `handle_command()` function
4. Add VISCA mapping in `visca_parser.py`

## Testing

### Test IR Pico Standalone
Upload `pico_ir/test_ir.py` and run:
- WASD/arrow keys for pan/tilt
- +/- for zoom
- O for OK
- Q to quit

### Test VISCA Pico
Use `ptz_controller.py` on a PC:
```bash
python3 ptz_controller.py
```

## Build Notes

- Both Picos run MicroPython with WIZNET5K support
- The IR Pico sends OK on startup (8 sec delay) to enable camera IR mode
- Garbage collection is disabled during IR transmission for timing accuracy
- The UART is checked every loop iteration (even during movement) to catch STOP commands

## Troubleshooting

1. **Camera doesn't respond**: Camera may have timed out of IR mode. Press OK or restart IR Pico.
2. **Jerky movement**: Check 57.3ms gap timing. Network operations on wrong Pico?
3. **No network**: Check W5500 wiring, verify IP/subnet match your network.
4. **STOP doesn't work**: Ensure UART is checked before/during movement loop.
