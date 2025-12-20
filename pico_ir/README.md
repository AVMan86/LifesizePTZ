# IR Pico - LifeSize Camera IR Transmitter

This Pico has ONE job: maintain perfect 57.325ms IR timing for smooth camera movement.

## Purpose

The IR Pico receives simple single-byte commands over UART from the VISCA Pico and translates them into precisely-timed IR signals. No network code, no complex parsing - just timing perfection.

## Files to Upload

Copy these files to the Pico's root filesystem:
```
main.py      - Main IR transmission code
protocol.py  - UART command definitions and IR timing constants
```

Optional for testing:
```
test_ir.py   - Keyboard-controlled manual testing
```

## Pin Configuration

| Function    | GPIO | Notes |
|-------------|------|-------|
| IR LED      | GP15 | 38kHz PWM output |
| UART TX     | GP0  | Connect to VISCA Pico GP1 |
| UART RX     | GP1  | Connect to VISCA Pico GP0 |
| Onboard LED | GP25 | Status indicator |

## IR LED Circuit

```
GP15 ──[1kΩ]──┬── Base (B)
              │
            2N2222
              │
           Emitter (E) ── GND
              │
           Collector (C)
              │
            [100Ω]
              │
           IR LED (+)
              │
           IR LED (-) ── 3.3V
```

## UART Commands

Commands received from VISCA Pico (single bytes at 115200 baud):

| Command | Byte | Action |
|---------|------|--------|
| START_UP | 0x01 | Begin moving up |
| START_DOWN | 0x02 | Begin moving down |
| START_LEFT | 0x03 | Begin moving left |
| START_RIGHT | 0x04 | Begin moving right |
| START_ZOOM_IN | 0x05 | Begin zoom in |
| START_ZOOM_OUT | 0x06 | Begin zoom out |
| START_UP_LEFT | 0x07 | Diagonal up-left |
| START_UP_RIGHT | 0x08 | Diagonal up-right |
| START_DOWN_LEFT | 0x09 | Diagonal down-left |
| START_DOWN_RIGHT | 0x0A | Diagonal down-right |
| STOP | 0x10 | Stop all movement |
| PRESS_OK | 0x20 | Send OK (enable IR mode) |

Response: ACK (0x06) on success.

## IR Protocol Details

LifeSize uses pulse-distance encoding at 38kHz:

- **Header**: 2550µs mark, 2500µs space
- **Bit mark**: 1200µs
- **Bit 0 space**: 1050µs
- **Bit 1 space**: 2825µs
- **Frame gap**: 57.325ms (CRITICAL for smooth movement!)

Frame format: 16-bit (device code 0x98 + command code)

## Startup Behavior

1. Initialize PWM and UART
2. Wait 8 seconds for camera to boot
3. Send OK command to enable IR remote mode
4. Begin listening for UART commands

## LED Status

- **Solid**: Transmitting IR
- **Blinking (slow)**: Idle, waiting for commands
- **Off during transmission gaps**: Normal

## Testing

Upload `test_ir.py` for manual keyboard testing:
- **WASD** or **Arrow keys**: Pan/Tilt
- **+/-**: Zoom In/Out
- **O**: OK button
- **Q**: Quit

## Troubleshooting

**Camera doesn't respond:**
- Check IR LED is working (phone camera can see 38kHz IR)
- Camera may have timed out of IR mode - press OK or restart Pico

**Jerky movement:**
- Check `IR_PACKET_GAP_US` in protocol.py (should be 57325)
- Ensure garbage collection is disabled during transmission

**STOP doesn't work:**
- UART must be checked every loop iteration, even during movement
