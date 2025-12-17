import machine
import time
import micropython

# High-precision timing
micropython.alloc_emergency_exception_buf(100)

# ==========================================
# CONFIGURATION
# ==========================================
IR_PIN_ID = 16
FREQUENCY = 38000
DUTY_CYCLE = 32768

# Protocol Timings (Tuned for Pico Overhead)
HDR_MARK   = 2550
HDR_SPACE  = 2500
BIT_MARK   = 1200
ONE_SPACE  = 2825
ZERO_SPACE = 1050
PACKET_GAP_US = 57325 

# Lifesize Remote Codes
COMMANDS = {
    "UP":       0x9815,
    "DOWN":     0x981A,
    "LEFT":     0x9825,
    "RIGHT":    0x982A,
    "ZOOM_IN":  0x9834,
    "ZOOM_OUT": 0x983B,
    "OK":       0x981C
}

# ==========================================
# IR TRANSMITTER
# ==========================================
def send_code(pwm, code):
    """Sends a single IR packet"""
    # 1. Header
    pwm.duty_u16(DUTY_CYCLE)
    time.sleep_us(HDR_MARK)
    pwm.duty_u16(0)
    time.sleep_us(HDR_SPACE)
    
    # 2. Data (16 bits, MSB first)
    for i in range(15, -1, -1):
        bit = (code >> i) & 1
        
        pwm.duty_u16(DUTY_CYCLE)
        time.sleep_us(BIT_MARK)
        pwm.duty_u16(0)
        
        if bit == 1:
            time.sleep_us(ONE_SPACE)
        else:
            time.sleep_us(ZERO_SPACE)
    
    # 3. Stop Bit
    pwm.duty_u16(DUTY_CYCLE)
    time.sleep_us(BIT_MARK)
    pwm.duty_u16(0)

def send_command(pin_id, command_name, repeats=3):
    """Sends a named command with the correct protocol gap"""
    if command_name not in COMMANDS:
        print(f"Error: Unknown command '{command_name}'")
        return

    code = COMMANDS[command_name]
    print(f"Sending {command_name} ({hex(code)})...")
    
    # Initialize PWM
    pwm = machine.PWM(machine.Pin(pin_id))
    pwm.freq(FREQUENCY)
    pwm.duty_u16(0)
    
    try:
        for _ in range(repeats):
            send_code(pwm, code)
            time.sleep_us(PACKET_GAP_US)
    finally:
        pwm.deinit()

# ==========================================
# MAIN LOOP
# ==========================================
# Example: Cycle through commands
print("Starting IR Demo...")

while True:
    # Example sequence
    send_command(IR_PIN_ID, "UP")
    time.sleep(1) 
    
    send_command(IR_PIN_ID, "DOWN")
    time.sleep(1)
    
    send_command(IR_PIN_ID, "OK")
    time.sleep(2)