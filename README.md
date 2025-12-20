# LifeSize PTZ Camera VISCA-to-IR Bridge

A MicroPython-based bridge that receives standard VISCA-over-IP commands and translates them to IR signals for controlling a LifeSize 10x PTZ camera.

## Architecture

This project uses a **two-Pico design** for reliable IR timing:

```
┌──────────────┐         ┌──────────────┐         ┌──────────────┐
│     PTZ      │  UDP    │  VISCA Pico  │  UART   │   IR Pico    │   IR    ┌────────┐
│  Controller  │────────►│   (W5500)    │────────►│  (38kHz PWM) │────────►│ Camera │
│  (PC/iPad)   │  52381  │  pico_visca/ │ 115200  │   pico_ir/   │         └────────┘
└──────────────┘         └──────────────┘         └──────────────┘
```

**Why two Picos?** The LifeSize camera requires precise 57.325ms gaps between IR frames for smooth movement. A dedicated IR Pico handles only timing-critical transmission, while the VISCA Pico handles network operations.

## Hardware Requirements

### VISCA Pico (Network Handler)
- Raspberry Pi Pico 2W
- W5500 Ethernet Module (SPI)
- 5V Relay Module (optional, for camera power)

### IR Pico (IR Transmitter)
- Raspberry Pi Pico 2W
- IR LED with driver circuit (38kHz)

### Connections Between Picos
| VISCA Pico | IR Pico | Function |
|------------|---------|----------|
| GP0 (TX)   | GP1 (RX)| UART TX  |
| GP1 (RX)   | GP0 (TX)| UART RX  |
| GND        | GND     | Ground   |

## Pin Configuration

### VISCA Pico
| Function     | GPIO |
|--------------|------|
| SPI SCK      | GP2  |
| SPI MOSI     | GP3  |
| SPI MISO     | GP4  |
| SPI CS       | GP5  |
| W5500 Reset  | GP6  |
| Relay        | GP7  |
| UART TX      | GP0  |
| UART RX      | GP1  |

### IR Pico
| Function     | GPIO |
|--------------|------|
| IR LED       | GP15 |
| UART TX      | GP0  |
| UART RX      | GP1  |
| Onboard LED  | GP25 |

## Network Configuration

Default settings (edit `pico_visca/config.py`):
- **IP**: 192.168.5.177
- **Subnet**: 255.255.255.0
- **Gateway**: 192.168.5.1
- **VISCA Port**: 52381 (UDP)

## Installation

### 1. Install MicroPython
Flash MicroPython with WIZNET5K support to both Picos.

### 2. Upload VISCA Pico Code
Copy to the first Pico:
```
pico_visca/main.py      → main.py
pico_visca/config.py    → config.py
pico_visca/visca_parser.py → visca_parser.py
pico_visca/protocol.py  → protocol.py
```

### 3. Upload IR Pico Code
Copy to the second Pico:
```
pico_ir/main.py         → main.py
pico_ir/protocol.py     → protocol.py
```

### 4. Connect Hardware
1. Wire W5500 to VISCA Pico (SPI)
2. Wire IR LED circuit to IR Pico GP15
3. Connect UART between Picos (TX↔RX cross-connection)
4. Connect relay to VISCA Pico GP7 (optional)

### 5. Power On
Both Picos start automatically. The IR Pico sends OK after 8 seconds to enable camera IR mode.

## PTZ Controller (PC Software)

Run the included GUI controller:
```bash
python3 ptz_controller.py
```

Features:
- Editable Bridge IP address
- Pan/Tilt/Zoom buttons
- Keyboard shortcuts (arrows, +/-, Space)
- Automatic connectivity monitoring

## Supported VISCA Commands

### Pan-Tilt
| Direction | VISCA Command |
|-----------|---------------|
| Up        | `81 01 06 01 VV WW 03 01 FF` |
| Down      | `81 01 06 01 VV WW 03 02 FF` |
| Left      | `81 01 06 01 VV WW 01 03 FF` |
| Right     | `81 01 06 01 VV WW 02 03 FF` |
| Stop      | `81 01 06 01 VV WW 03 03 FF` |

Diagonal movements are supported by alternating pan/tilt IR commands.

### Zoom
| Action    | VISCA Command |
|-----------|---------------|
| Zoom In   | `81 01 04 07 2X FF` |
| Zoom Out  | `81 01 04 07 3X FF` |
| Stop      | `81 01 04 07 00 FF` |

## LifeSize IR Protocol

- **Carrier**: 38kHz
- **Header**: 2550µs mark, 2500µs space
- **Bit 0**: 1200µs mark, 1050µs space
- **Bit 1**: 1200µs mark, 2825µs space
- **Frame**: Device (0x98) + Command (8-bit)
- **Gap**: 57.325ms between frames (critical!)

### IR Command Codes
| Button   | Code |
|----------|------|
| UP       | 0x15 |
| DOWN     | 0x1A |
| LEFT     | 0x25 |
| RIGHT    | 0x2A |
| OK       | 0x1C |
| ZOOM IN  | 0x34 |
| ZOOM OUT | 0x3B |

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

## Troubleshooting

**Camera doesn't respond to IR:**
- Camera may have timed out of IR mode. Restart IR Pico or press OK button.
- Check IR LED is working (phone camera can see IR).

**Jerky/stuttering movement:**
- The 57.325ms gap timing may be off. Check `IR_PACKET_GAP_US` in `protocol.py`.

**No network connection:**
- Verify IP address matches your network subnet.
- Check W5500 wiring (SPI pins, reset pin).
- Try pinging the bridge IP.

**STOP command ignored:**
- Ensure IR Pico checks UART every loop iteration.

## Testing

### Test IR Pico Standalone
Upload `pico_ir/test_ir.py` for keyboard-controlled testing:
- WASD or Arrow keys: Pan/Tilt
- +/-: Zoom
- O: OK button
- Q: Quit

### Debug Output
Enable debug flags in `pico_visca/config.py`:
```python
DEBUG_VISCA = True   # Print VISCA commands
DEBUG_UART = True    # Print UART communication
```

## File Structure

```
├── pico_visca/           # VISCA Pico (network handler)
│   ├── main.py           # Entry point, network, relay control
│   ├── config.py         # IP address, pin definitions
│   ├── visca_parser.py   # VISCA command parsing
│   └── protocol.py       # UART protocol definitions
│
├── pico_ir/              # IR Pico (timing-critical)
│   ├── main.py           # IR transmission, UART handling
│   ├── protocol.py       # UART protocol definitions
│   └── test_ir.py        # Keyboard test script
│
├── ptz_controller.py     # PC GUI controller
├── README.md             # This file
└── CLAUDE.md             # AI assistant context
```

## License

MIT License
