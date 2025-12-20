# VISCA Pico - Network Handler

This Pico handles network communication and VISCA command parsing. It receives VISCA-over-IP commands and sends simple single-byte commands to the IR Pico.

## Purpose

The VISCA Pico:
1. Connects to the network via W5500 Ethernet module
2. Listens for VISCA commands on UDP port 52381
3. Parses VISCA pan/tilt/zoom commands
4. Sends simple commands to IR Pico over UART
5. Controls camera power relay based on network link status

## Files to Upload

Copy these files to the Pico's root filesystem:
```
main.py         - Entry point, network init, main loop
config.py       - IP address, pin definitions, debug flags
visca_parser.py - VISCA command parsing
protocol.py     - UART command definitions
```

## Pin Configuration

| Function     | GPIO | Notes |
|--------------|------|-------|
| SPI SCK      | GP2  | W5500 clock |
| SPI MOSI     | GP3  | W5500 data out |
| SPI MISO     | GP4  | W5500 data in |
| SPI CS       | GP5  | W5500 chip select |
| W5500 Reset  | GP6  | Active low |
| Relay        | GP7  | Camera power control |
| UART TX      | GP0  | Connect to IR Pico GP1 |
| UART RX      | GP1  | Connect to IR Pico GP0 |
| Onboard LED  | GP25 | Status indicator |

## Network Configuration

Edit `config.py` to change network settings:

```python
BRIDGE_IP = "192.168.5.177"      # Static IP address
BRIDGE_SUBNET = "255.255.255.0"  # Subnet mask
BRIDGE_GATEWAY = "192.168.5.1"   # Default gateway
BRIDGE_DNS = "8.8.8.8"           # DNS server
VISCA_PORT = 52381               # UDP port (VISCA standard)
```

## W5500 Wiring

| W5500 Pin | Pico GPIO |
|-----------|-----------|
| SCLK      | GP2       |
| MOSI      | GP3       |
| MISO      | GP4       |
| CS        | GP5       |
| RST       | GP6       |
| VCC       | 3.3V      |
| GND       | GND       |

## Relay Control

The relay on GP7 controls camera power:
- **ON**: When Ethernet link is stable (after 500ms stability check)
- **OFF**: When Ethernet link is lost

This provides automatic camera power management - the camera powers on when the PTZ controller connects to the network.

## Supported VISCA Commands

### Pan-Tilt Drive (0x81 0x01 0x06 0x01)
```
81 01 06 01 VV WW PP TT FF
             │  │  │  └── Tilt direction (01=up, 02=down, 03=stop)
             │  │  └───── Pan direction (01=left, 02=right, 03=stop)
             │  └──────── Tilt speed (ignored)
             └─────────── Pan speed (ignored)
```

**Note:** Left/Right are reversed for "audience perspective" - when you press Left, the image moves left (camera moves counterclockwise).

### Zoom (0x81 0x01 0x04 0x07)
```
81 01 04 07 PP FF
             └── 00=stop, 2X=in, 3X=out (X=speed, ignored)
```

### OK Button (0x81 0x01 0x04 0x3F 0x02 0x7F)
Custom command to send OK (enables camera IR mode).

## Debug Output

Enable debug flags in `config.py`:
```python
DEBUG_VISCA = True   # Print received VISCA commands
DEBUG_UART = True    # Print UART communication with IR Pico
```

## Startup Sequence

1. Initialize W5500 hardware (SPI, reset)
2. Wait for Ethernet link
3. Configure static IP
4. Enable relay (power on camera)
5. Initialize UART to IR Pico
6. Start listening for VISCA commands

## UART Protocol

Commands sent to IR Pico (115200 baud, 8N1):

| Command | Byte | VISCA Trigger |
|---------|------|---------------|
| START_UP | 0x01 | Pan-tilt up |
| START_DOWN | 0x02 | Pan-tilt down |
| START_LEFT | 0x03 | Pan-tilt left |
| START_RIGHT | 0x04 | Pan-tilt right |
| START_ZOOM_IN | 0x05 | Zoom tele |
| START_ZOOM_OUT | 0x06 | Zoom wide |
| STOP | 0x10 | Pan-tilt/zoom stop |
| PRESS_OK | 0x20 | OK button command |

## Troubleshooting

**No network connection:**
- Check W5500 wiring (especially SPI pins and reset)
- Verify IP address matches your network subnet
- Try pinging the configured IP address

**VISCA commands not working:**
- Enable `DEBUG_VISCA = True` in config.py
- Check UDP port 52381 is not blocked
- Verify PTZ controller is sending to correct IP

**Relay not activating:**
- Check GP7 wiring
- Ethernet link must be stable for 500ms before relay enables

**IR Pico not responding:**
- Check UART wiring (TX↔RX cross-connection)
- Enable `DEBUG_UART = True` in config.py
