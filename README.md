# LifeSize PTZ Camera VISCA-to-IR Bridge

A MicroPython-based bridge that receives standard VISCA-over-IP commands and translates them to IR signals for controlling a LifeSize 10x PTZ camera.

## Hardware Requirements

- **Raspberry Pi Pico 2W** (RP2350)
- **W5500 Ethernet Module** (SPI connection)
- **IR LED** with NPN transistor driver (2N2222 or similar)
- **TSOP38238** IR receiver (optional, for signal verification)
- **Relay Module** (optional, for camera power control)

## Pin Configuration

| Function | GPIO Pin |
|----------|----------|
| IR LED | GP15 |
| SPI MISO | GP16 |
| SPI CS | GP17 |
| SPI SCK | GP18 |
| SPI MOSI | GP19 |
| Relay Control | GP20 |
| W5500 Reset | GP21 |
| IR Receiver | GP22 |

## Network Configuration

- **Bridge IP**: 192.168.5.177
- **Subnet**: 255.255.255.0
- **Gateway**: 192.168.5.1
- **VISCA Port**: 52381 (UDP)

Edit `config.py` to change these settings.

## Installation

1. Install MicroPython on the Pico 2W (ensure it includes W5500/WIZNET support)
2. Copy all `.py` files to the Pico's filesystem
3. Connect the W5500 module and IR LED circuit
4. Reset the Pico to start the bridge

## File Structure

```
├── main.py              # Entry point, network init, main loop
├── config.py            # Pin definitions, IP config, timing constants
├── visca_parser.py      # VISCA command parsing
├── ir_transmitter.py    # PIO-based IR transmission
├── ir_protocol.py       # LifeSize IR protocol encoding
├── command_scheduler.py # 57ms timing management for smooth movement
└── README.md            # This file
```

## Supported VISCA Commands

### Pan-Tilt

| Direction | VISCA Command |
|-----------|---------------|
| Up | `81 01 06 01 VV WW 03 01 FF` |
| Down | `81 01 06 01 VV WW 03 02 FF` |
| Left | `81 01 06 01 VV WW 01 03 FF` |
| Right | `81 01 06 01 VV WW 02 03 FF` |
| Stop | `81 01 06 01 VV WW 03 03 FF` |

Diagonal movements (e.g., Up-Left: `01 01`) are supported by alternating between pan and tilt IR commands.

### Zoom

| Action | VISCA Command |
|--------|---------------|
| Zoom In (Tele) | `81 01 04 07 02 FF` |
| Zoom Out (Wide) | `81 01 04 07 03 FF` |
| Zoom Stop | `81 01 04 07 00 FF` |

## LifeSize IR Protocol

The camera uses pulse-distance encoding at 38kHz carrier:

- **Leader**: 2600µs mark, 1120µs space
- **Bit 0**: 560µs mark, 560µs space
- **Bit 1**: 560µs mark, 1680µs space
- **Frame**: Device code (0x98) + inverted + Command + inverted
- **Critical**: 57ms gap between frames for smooth movement

### Known IR Command Codes

| Button | Code |
|--------|------|
| UP | 0x15 |
| DOWN | 0x1A |
| LEFT | 0x25 |
| RIGHT | 0x2A |
| OK/Select | 0x1C |
| ZOOM IN | 0x37 |
| ZOOM OUT | 0x38 |

## Testing

### Test IR Transmission

```python
import main
main.test_ir_commands()  # Test all IR commands
main.test_continuous_movement("right", 3)  # Move right for 3 seconds
main.test_diagonal(2)  # Diagonal up-right for 2 seconds
```

### Echo VISCA Commands

```python
import main
main.echo_visca()  # Print received VISCA commands without IR output
```

### Test Individual Components

```python
# Test IR protocol encoding
import ir_protocol
ir_protocol.protocol.verify_encoding(0x15)  # UP command

# Test VISCA parser
import visca_parser
parser = visca_parser.VISCAParser()
cmd = parser.parse(bytes([0x81, 0x01, 0x06, 0x01, 0x10, 0x10, 0x03, 0x01, 0xFF]))
print(cmd.get_ir_commands())
```

## Debugging

Enable debug output in `config.py`:

```python
DEBUG_VISCA = True   # Print received VISCA commands
DEBUG_IR = True      # Print IR transmission details
DEBUG_TIMING = True  # Print detailed timing info
```

## IR LED Circuit

```
GPIO15 ──┬──[1kΩ]──┬── Base (B)
         │         │
        GND      2N2222
                   │
                Emitter (E) ── GND
                   │
                Collector (C)
                   │
                [100Ω]
                   │
                IR LED (+)
                   │
                IR LED (-) ── 3.3V or 5V
```

Note: IR LED cathode connects to Vcc, anode through resistor to collector. LED is active when transistor conducts (GPIO high).

## License

MIT License
