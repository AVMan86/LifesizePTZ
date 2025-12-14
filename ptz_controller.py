#!/usr/bin/env python3
"""
PTZ Controller for LifeSize IR Bridge
VISCA over IP command sender with GUI

This program sends VISCA commands to the Raspberry Pi Pico 2W bridge
to control the LifeSize camera via IR remote emulation.

Usage:
    python3 ptz_controller.py

Requirements:
    - Python 3.6+
    - tkinter (usually included with Python)
"""

import socket
import time
import threading
from tkinter import *
from tkinter import ttk, messagebox
import struct

# === CONFIGURATION ===
BRIDGE_IP = "192.168.5.177"
BRIDGE_PORT = 52381
LOCAL_PORT = 52382  # Port to receive responses

# === VISCA PROTOCOL ===
class VISCACommands:
    """VISCA command builder"""
    
    # Command headers
    PAN_TILT_DRIVE = b'\x81\x01\x06\x01'
    ZOOM_COMMAND = b'\x81\x01\x04\x07'
    
    # Direction codes
    PAN_LEFT = 0x01
    PAN_RIGHT = 0x02
    PAN_STOP = 0x03
    
    TILT_UP = 0x01
    TILT_DOWN = 0x02
    TILT_STOP = 0x03
    
    @staticmethod
    def pan_tilt(pan_speed, tilt_speed, pan_dir, tilt_dir):
        """Build pan/tilt command"""
        return (VISCACommands.PAN_TILT_DRIVE + 
                bytes([pan_speed, tilt_speed, pan_dir, tilt_dir]) + 
                b'\xFF')
    
    @staticmethod
    def zoom_in(speed):
        """Build zoom in command"""
        zoom_param = 0x20 | (speed & 0x0F)
        return VISCACommands.ZOOM_COMMAND + bytes([zoom_param]) + b'\xFF'
    
    @staticmethod
    def zoom_out(speed):
        """Build zoom out command"""
        zoom_param = 0x30 | (speed & 0x0F)
        return VISCACommands.ZOOM_COMMAND + bytes([zoom_param]) + b'\xFF'
    
    @staticmethod
    def zoom_stop():
        """Build zoom stop command"""
        return VISCACommands.ZOOM_COMMAND + b'\x00\xFF'
    
    @staticmethod
    def stop_all():
        """Stop all movement"""
        return VISCACommands.pan_tilt(0, 0, 
                                     VISCACommands.PAN_STOP, 
                                     VISCACommands.TILT_STOP)
    
    @staticmethod
    def inquiry_block_mode():
        """Inquiry command for testing connectivity"""
        return b'\x81\x09\x04\x39\xFF'

# === PTZ CONTROLLER ===
class PTZController:
    """Network interface for sending VISCA commands"""
    
    def __init__(self, bridge_ip, bridge_port):
        self.bridge_ip = bridge_ip
        self.bridge_port = bridge_port
        self.socket = None
        self.connected = False
        self.listener_thread = None
        self.running = False
        
        # Movement state
        self.active_movements = {
            'pan': None,
            'tilt': None,
            'zoom': None
        }
        
        self.lock = threading.Lock()
    
    def connect(self):
        """Initialize UDP socket and verify bridge is responding"""
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind(('', LOCAL_PORT))
            self.socket.settimeout(2.0)  # 2 second timeout for connection test
            
            print(f"Testing connection to bridge at {self.bridge_ip}:{self.bridge_port}...")
            print(f"  Local socket bound to port {LOCAL_PORT}")

            # Send test inquiry command
            test_cmd = VISCACommands.inquiry_block_mode()
            hex_cmd = ' '.join(f'{b:02X}' for b in test_cmd)
            print(f"  Sending inquiry: {hex_cmd}")
            print(f"  Destination: {self.bridge_ip}:{self.bridge_port}")

            bytes_sent = self.socket.sendto(test_cmd, (self.bridge_ip, self.bridge_port))
            print(f"  Sent {bytes_sent} bytes via UDP")

            # Wait for response
            try:
                data, addr = self.socket.recvfrom(128)
                hex_data = ' '.join(f'{b:02X}' for b in data)
                print(f"✓ Bridge responded: {hex_data}")
                
                # Valid response received
                self.connected = True
                self.socket.settimeout(0.5)  # Set normal timeout
                
                # Start response listener
                self.running = True
                self.listener_thread = threading.Thread(target=self._listen_responses, daemon=True)
                self.listener_thread.start()
                
                print(f"✓ Connected to bridge at {self.bridge_ip}:{self.bridge_port}")
                return True
                
            except socket.timeout:
                print(f"✗ No response from bridge (timeout)")
                print(f"  Make sure the Pico is powered on and at {self.bridge_ip}")
                self.socket.close()
                return False
            
        except Exception as e:
            print(f"✗ Connection failed: {e}")
            return False
    
    def _listen_responses(self):
        """Listen for responses from bridge"""
        while self.running:
            try:
                data, addr = self.socket.recvfrom(128)
                hex_data = ' '.join(f'{b:02X}' for b in data)
                print(f"Response from {addr}: {hex_data}")
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"Listener error: {e}")
    
    def send_command(self, command, description=""):
        """Send VISCA command to bridge"""
        if not self.connected or not self.socket:
            print("Not connected!")
            return False
        
        try:
            hex_cmd = ' '.join(f'{b:02X}' for b in command)
            print(f"Sending {description}: {hex_cmd}")
            
            self.socket.sendto(command, (self.bridge_ip, self.bridge_port))
            return True
            
        except Exception as e:
            print(f"Send failed: {e}")
            self.connected = False
            return False
    
    def pan_left(self, speed=10):
        """Pan left"""
        with self.lock:
            self.active_movements['pan'] = 'left'
        cmd = VISCACommands.pan_tilt(speed, 0, 
                                     VISCACommands.PAN_LEFT, 
                                     VISCACommands.TILT_STOP)
        self.send_command(cmd, f"Pan Left (speed {speed})")
    
    def pan_right(self, speed=10):
        """Pan right"""
        with self.lock:
            self.active_movements['pan'] = 'right'
        cmd = VISCACommands.pan_tilt(speed, 0, 
                                     VISCACommands.PAN_RIGHT, 
                                     VISCACommands.TILT_STOP)
        self.send_command(cmd, f"Pan Right (speed {speed})")
    
    def tilt_up(self, speed=10):
        """Tilt up"""
        with self.lock:
            self.active_movements['tilt'] = 'up'
        cmd = VISCACommands.pan_tilt(0, speed, 
                                     VISCACommands.PAN_STOP, 
                                     VISCACommands.TILT_UP)
        self.send_command(cmd, f"Tilt Up (speed {speed})")
    
    def tilt_down(self, speed=10):
        """Tilt down"""
        with self.lock:
            self.active_movements['tilt'] = 'down'
        cmd = VISCACommands.pan_tilt(0, speed, 
                                     VISCACommands.PAN_STOP, 
                                     VISCACommands.TILT_DOWN)
        self.send_command(cmd, f"Tilt Down (speed {speed})")
    
    def zoom_in(self, speed=5):
        """Zoom in"""
        with self.lock:
            self.active_movements['zoom'] = 'in'
        cmd = VISCACommands.zoom_in(speed)
        self.send_command(cmd, f"Zoom In (speed {speed})")
    
    def zoom_out(self, speed=5):
        """Zoom out"""
        with self.lock:
            self.active_movements['zoom'] = 'out'
        cmd = VISCACommands.zoom_out(speed)
        self.send_command(cmd, f"Zoom Out (speed {speed})")
    
    def stop_pan_tilt(self):
        """Stop pan/tilt movement"""
        with self.lock:
            self.active_movements['pan'] = None
            self.active_movements['tilt'] = None
        cmd = VISCACommands.stop_all()
        self.send_command(cmd, "Stop Pan/Tilt")
    
    def stop_zoom(self):
        """Stop zoom"""
        with self.lock:
            self.active_movements['zoom'] = None
        cmd = VISCACommands.zoom_stop()
        self.send_command(cmd, "Stop Zoom")
    
    def stop_all(self):
        """Emergency stop all movement"""
        with self.lock:
            self.active_movements = {'pan': None, 'tilt': None, 'zoom': None}
        self.stop_pan_tilt()
        self.stop_zoom()

    def send_ok(self):
        """Send OK button command (for enabling IR mode)"""
        # OK command - this is a special command that gets mapped to IR 'ok'
        # Using a custom inquiry format that our VISCA handler recognizes
        cmd = b'\x81\x01\x04\x3F\x02\x7F\xFF'  # Custom command for OK button
        self.send_command(cmd, "OK Button (Enable IR Mode)")

    def disconnect(self):
        """Close connection"""
        self.running = False
        if self.listener_thread and self.listener_thread.is_alive():
            self.listener_thread.join(timeout=1.0)
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        self.connected = False

# === GUI ===
class PTZControllerGUI:
    """Graphical interface for PTZ control"""
    
    def __init__(self, root):
        self.root = root
        self.root.title("LifeSize PTZ Controller")
        self.root.geometry("500x800")
        self.root.resizable(False, False)
        
        # Controller backend
        self.controller = PTZController(BRIDGE_IP, BRIDGE_PORT)
        
        # Speed variables
        self.pan_tilt_speed = IntVar(value=10)
        self.zoom_speed = IntVar(value=5)
        
        # Button press tracking
        self.pressed_buttons = set()

        # Continuous movement tracking for mouse buttons
        self.continuous_timers = {}
        self.button_held = {}

        self._create_ui()
        self._connect()
        
        # Bind cleanup
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
    
    def _create_ui(self):
        """Create the user interface"""
        
        # === CONNECTION STATUS ===
        status_frame = ttk.LabelFrame(self.root, text="Connection", padding=10)
        status_frame.pack(fill=X, padx=10, pady=10)
        
        ttk.Label(status_frame, text=f"Bridge IP: {BRIDGE_IP}:{BRIDGE_PORT}").pack()
        
        self.status_label = ttk.Label(status_frame, text="⚫ Disconnected", 
                                      foreground="red", font=("Arial", 12, "bold"))
        self.status_label.pack(pady=5)
        
        # Reconnect button
        self.reconnect_btn = ttk.Button(status_frame, text="🔄 Reconnect", 
                                        command=self._reconnect)
        self.reconnect_btn.pack(pady=5)
        
        # === MOVEMENT SPEEDS ===
        speed_frame = ttk.LabelFrame(self.root, text="Speed Control", padding=10)
        speed_frame.pack(fill=X, padx=10, pady=10)
        
        # Pan/Tilt Speed
        ttk.Label(speed_frame, text="Pan/Tilt Speed:").grid(row=0, column=0, sticky=W, padx=5)
        pan_tilt_scale = ttk.Scale(speed_frame, from_=1, to=24, 
                                   variable=self.pan_tilt_speed, orient=HORIZONTAL)
        pan_tilt_scale.grid(row=0, column=1, sticky=EW, padx=5)
        self.pan_tilt_value = ttk.Label(speed_frame, text="10")
        self.pan_tilt_value.grid(row=0, column=2, padx=5)
        
        # Zoom Speed
        ttk.Label(speed_frame, text="Zoom Speed:").grid(row=1, column=0, sticky=W, padx=5)
        zoom_scale = ttk.Scale(speed_frame, from_=0, to=7, 
                              variable=self.zoom_speed, orient=HORIZONTAL)
        zoom_scale.grid(row=1, column=1, sticky=EW, padx=5)
        self.zoom_value = ttk.Label(speed_frame, text="5")
        self.zoom_value.grid(row=1, column=2, padx=5)
        
        speed_frame.columnconfigure(1, weight=1)
        
        # Update labels
        self.pan_tilt_speed.trace('w', lambda *args: 
                                 self.pan_tilt_value.config(text=str(self.pan_tilt_speed.get())))
        self.zoom_speed.trace('w', lambda *args: 
                             self.zoom_value.config(text=str(self.zoom_speed.get())))
        
        # === PAN/TILT CONTROL ===
        pan_tilt_frame = ttk.LabelFrame(self.root, text="Pan/Tilt Control", padding=20)
        pan_tilt_frame.pack(fill=BOTH, expand=True, padx=10, pady=10)
        
        # Create directional pad layout
        button_size = 80
        
        # UP button
        self.up_btn = Button(pan_tilt_frame, text="▲\nUP", 
                            width=10, height=3, font=("Arial", 12, "bold"))
        self.up_btn.grid(row=0, column=1, padx=5, pady=5)
        self.up_btn.bind('<ButtonPress-1>', lambda e: self._on_tilt_up())
        self.up_btn.bind('<ButtonRelease-1>', lambda e: self._on_stop_pan_tilt())
        
        # LEFT button
        self.left_btn = Button(pan_tilt_frame, text="◄\nLEFT", 
                              width=10, height=3, font=("Arial", 12, "bold"))
        self.left_btn.grid(row=1, column=0, padx=5, pady=5)
        self.left_btn.bind('<ButtonPress-1>', lambda e: self._on_pan_left())
        self.left_btn.bind('<ButtonRelease-1>', lambda e: self._on_stop_pan_tilt())
        
        # CENTER/STOP button
        self.stop_btn = Button(pan_tilt_frame, text="⬛\nSTOP", 
                              width=10, height=3, font=("Arial", 12, "bold"),
                              bg="#ff4444", fg="white")
        self.stop_btn.grid(row=1, column=1, padx=5, pady=5)
        self.stop_btn.bind('<Button-1>', lambda e: self._on_stop_all())
        
        # RIGHT button
        self.right_btn = Button(pan_tilt_frame, text="►\nRIGHT", 
                               width=10, height=3, font=("Arial", 12, "bold"))
        self.right_btn.grid(row=1, column=2, padx=5, pady=5)
        self.right_btn.bind('<ButtonPress-1>', lambda e: self._on_pan_right())
        self.right_btn.bind('<ButtonRelease-1>', lambda e: self._on_stop_pan_tilt())
        
        # DOWN button
        self.down_btn = Button(pan_tilt_frame, text="▼\nDOWN",
                              width=10, height=3, font=("Arial", 12, "bold"))
        self.down_btn.grid(row=2, column=1, padx=5, pady=5)
        self.down_btn.bind('<ButtonPress-1>', lambda e: self._on_tilt_down())
        self.down_btn.bind('<ButtonRelease-1>', lambda e: self._on_stop_pan_tilt())

        # === OK BUTTON (for IR mode activation) ===
        ok_frame = ttk.LabelFrame(self.root, text="Camera Control", padding=10)
        ok_frame.pack(fill=X, padx=10, pady=10)

        self.ok_btn = Button(ok_frame, text="OK\n(Enable IR Mode)",
                            width=20, height=2, font=("Arial", 12, "bold"),
                            bg="#4444ff", fg="white")
        self.ok_btn.pack(pady=5)
        self.ok_btn.bind('<Button-1>', lambda e: self._on_ok())

        ttk.Label(ok_frame, text="Press to activate camera IR remote mode\n(Hold OK for 5 seconds on camera)").pack()

        # === ZOOM CONTROL ===
        zoom_frame = ttk.LabelFrame(self.root, text="Zoom Control", padding=20)
        zoom_frame.pack(fill=X, padx=10, pady=10)
        
        # ZOOM IN button
        self.zoom_in_btn = Button(zoom_frame, text="🔍+\nZOOM IN", 
                                 width=15, height=3, font=("Arial", 12, "bold"))
        self.zoom_in_btn.pack(side=LEFT, padx=10)
        self.zoom_in_btn.bind('<ButtonPress-1>', lambda e: self._on_zoom_in())
        self.zoom_in_btn.bind('<ButtonRelease-1>', lambda e: self._on_stop_zoom())
        
        # ZOOM OUT button
        self.zoom_out_btn = Button(zoom_frame, text="🔍-\nZOOM OUT", 
                                  width=15, height=3, font=("Arial", 12, "bold"))
        self.zoom_out_btn.pack(side=RIGHT, padx=10)
        self.zoom_out_btn.bind('<ButtonPress-1>', lambda e: self._on_zoom_out())
        self.zoom_out_btn.bind('<ButtonRelease-1>', lambda e: self._on_stop_zoom())
        
        # === KEYBOARD SHORTCUTS ===
        shortcuts_frame = ttk.LabelFrame(self.root, text="Keyboard Shortcuts", padding=10)
        shortcuts_frame.pack(fill=X, padx=10, pady=10)

        shortcuts_text = """
        Arrow Keys: Pan/Tilt (hold for continuous movement)
        +/-: Zoom In/Out (hold for continuous zoom)
        O: OK Button (enable IR mode)
        Space: Stop All Movement
        """
        ttk.Label(shortcuts_frame, text=shortcuts_text, justify=LEFT).pack()
        
        # Bind keyboard
        self.root.bind('<KeyPress>', self._on_key_press)
        self.root.bind('<KeyRelease>', self._on_key_release)
    
    def _connect(self):
        """Connect to bridge"""
        if self.controller.connect():
            self.status_label.config(text="🟢 Connected", foreground="green")
        else:
            self.status_label.config(text="🔴 Connection Failed", foreground="red")
            messagebox.showerror("Connection Error", 
                               f"Failed to connect to {BRIDGE_IP}:{BRIDGE_PORT}\n\n"
                               "Make sure the Pico is powered on and running.")
    
    def _reconnect(self):
        """Reconnect to bridge"""
        self.status_label.config(text="⚫ Reconnecting...", foreground="orange")
        self.root.update()
        
        # Disconnect first if needed
        if self.controller.connected:
            self.controller.disconnect()
        
        # Try to connect
        self._connect()
    
    # === CONTINUOUS MOVEMENT METHODS ===
    def _start_continuous_movement(self, direction, command_func):
        """Start continuous movement in a direction"""
        # Cancel any existing timer for this direction
        if direction in self.continuous_timers:
            self.root.after_cancel(self.continuous_timers[direction])

        # Mark button as held
        self.button_held[direction] = True

        # Send initial command
        command_func()

        # Start repeating timer (send command every 100ms while held)
        def repeat_command():
            if self.button_held.get(direction, False):
                command_func()
                self.continuous_timers[direction] = self.root.after(100, repeat_command)

        self.continuous_timers[direction] = self.root.after(100, repeat_command)

    def _stop_continuous_movement(self, direction, stop_func):
        """Stop continuous movement in a direction"""
        # Mark button as released
        self.button_held[direction] = False

        # Cancel timer
        if direction in self.continuous_timers:
            self.root.after_cancel(self.continuous_timers[direction])
            del self.continuous_timers[direction]

        # Send stop command
        stop_func()

    # === BUTTON HANDLERS ===
    def _on_pan_left(self):
        self.left_btn.config(bg="#90EE90")
        self._start_continuous_movement('left',
            lambda: self.controller.pan_left(self.pan_tilt_speed.get()))

    def _on_pan_right(self):
        self.right_btn.config(bg="#90EE90")
        self._start_continuous_movement('right',
            lambda: self.controller.pan_right(self.pan_tilt_speed.get()))

    def _on_tilt_up(self):
        self.up_btn.config(bg="#90EE90")
        self._start_continuous_movement('up',
            lambda: self.controller.tilt_up(self.pan_tilt_speed.get()))

    def _on_tilt_down(self):
        self.down_btn.config(bg="#90EE90")
        self._start_continuous_movement('down',
            lambda: self.controller.tilt_down(self.pan_tilt_speed.get()))

    def _on_stop_pan_tilt(self):
        # Stop all pan/tilt continuous movements
        for direction in ['left', 'right', 'up', 'down']:
            if direction in self.button_held:
                self._stop_continuous_movement(direction, lambda: None)

        self.controller.stop_pan_tilt()
        self.left_btn.config(bg="SystemButtonFace")
        self.right_btn.config(bg="SystemButtonFace")
        self.up_btn.config(bg="SystemButtonFace")
        self.down_btn.config(bg="SystemButtonFace")

    def _on_zoom_in(self):
        self.zoom_in_btn.config(bg="#90EE90")
        self._start_continuous_movement('zoom_in',
            lambda: self.controller.zoom_in(self.zoom_speed.get()))

    def _on_zoom_out(self):
        self.zoom_out_btn.config(bg="#90EE90")
        self._start_continuous_movement('zoom_out',
            lambda: self.controller.zoom_out(self.zoom_speed.get()))

    def _on_stop_zoom(self):
        # Stop zoom continuous movements
        for direction in ['zoom_in', 'zoom_out']:
            if direction in self.button_held:
                self._stop_continuous_movement(direction, lambda: None)

        self.controller.stop_zoom()
        self.zoom_in_btn.config(bg="SystemButtonFace")
        self.zoom_out_btn.config(bg="SystemButtonFace")

    def _on_ok(self):
        """Send OK button command"""
        self.controller.send_ok()
        # Flash button
        self.ok_btn.config(bg="#6666ff")
        self.root.after(200, lambda: self.ok_btn.config(bg="#4444ff"))

    def _on_stop_all(self):
        self.controller.stop_all()
        self._on_stop_pan_tilt()
        self._on_stop_zoom()
    
    # === KEYBOARD HANDLERS ===
    def _on_key_press(self, event):
        key = event.keysym

        if key in self.pressed_buttons:
            return  # Already pressed

        self.pressed_buttons.add(key)

        if key == 'Left':
            self._on_pan_left()
        elif key == 'Right':
            self._on_pan_right()
        elif key == 'Up':
            self._on_tilt_up()
        elif key == 'Down':
            self._on_tilt_down()
        elif key == 'plus' or key == 'equal':
            self._on_zoom_in()
        elif key == 'minus':
            self._on_zoom_out()
        elif key == 'o' or key == 'O':
            self._on_ok()
        elif key == 'space':
            self._on_stop_all()
    
    def _on_key_release(self, event):
        key = event.keysym
        
        if key not in self.pressed_buttons:
            return
        
        self.pressed_buttons.discard(key)
        
        if key in ['Left', 'Right', 'Up', 'Down']:
            self._on_stop_pan_tilt()
        elif key in ['plus', 'equal', 'minus']:
            self._on_stop_zoom()
    
    def _on_close(self):
        """Clean shutdown"""
        # Stop all continuous movements
        for timer in self.continuous_timers.values():
            self.root.after_cancel(timer)
        self.continuous_timers.clear()
        self.button_held.clear()

        # Stop all camera movement
        self.controller.stop_all()
        self.controller.disconnect()
        self.root.destroy()

# === MAIN ===
def main():
    """Main entry point"""
    print("=" * 50)
    print("LifeSize PTZ Controller")
    print("VISCA over IP Command Sender")
    print("=" * 50)
    print(f"Bridge IP: {BRIDGE_IP}:{BRIDGE_PORT}")
    print(f"Local Port: {LOCAL_PORT}")
    print("=" * 50)
    print()
    
    root = Tk()
    app = PTZControllerGUI(root)
    root.mainloop()

if __name__ == "__main__":
    main()

"""
=== USAGE INSTRUCTIONS ===

1. Make sure your LifeSize IR bridge is running on the Raspberry Pi Pico 2W
2. Update BRIDGE_IP if needed (default: 192.168.5.177)
3. Run this program:
   python3 ptz_controller.py

4. The program will test the connection by sending an inquiry command
   - 🟢 Green = Bridge is responding
   - 🔴 Red = No response from bridge
   - Use the "🔄 Reconnect" button to retry connection

5. Use the GUI buttons or keyboard shortcuts to control the camera:
   - Click and hold directional buttons for pan/tilt
   - Click and hold zoom buttons for zoom control
   - Press STOP to immediately halt all movement
   - Use arrow keys for keyboard control
   - Use +/- for zoom
   - Press Space to stop all

6. Watch the console for command/response logging

=== TESTING CHECKLIST ===

â˜ Connection Test - Should show "Connected" only if bridge responds
â˜ Pan Left - Should see IR LED flash on bridge
â˜ Pan Right - Should see IR LED flash on bridge  
â˜ Tilt Up - Should trigger UP_ARROW sequences
â˜ Tilt Down - Should trigger DOWN_ARROW sequences
â˜ Zoom In - Should send zoom commands
â˜ Zoom Out - Should send zoom commands
â˜ Stop - Should halt all movement
â˜ Speed adjustment - Higher speeds should send different values
â˜ Continuous movement - Hold button for smooth operation
â˜ Response logging - Check for ACK and COMPLETION messages
â˜ Reconnection - Unplug Pico, plug back in, hit Reconnect

=== TROUBLESHOOTING ===

If the controller shows "Connection Failed":
- Check that the Pico is powered on and running
- Verify the IP address matches (192.168.5.177)
- Check your network connection
- Try pinging the Pico: ping 192.168.5.177
- Check if ethernet link is up on the Pico (W5500 status)
- Use "🔄 Reconnect" button after fixing issues

If commands don't work after connecting:
- Check console output for sent commands
- Look for response messages from bridge
- Verify ethernet link is up on the Pico
- Check that camera is powered on (relay status)
- Try the Reconnect button

=== NETWORK TRAFFIC ===

You can monitor the VISCA commands with Wireshark:
1. Capture on your network interface
2. Filter: udp.port == 52381
3. Watch for VISCA command packets

Expected packet format:
81 01 06 01 [pan_speed] [tilt_speed] [pan_dir] [tilt_dir] FF

Connection test packet:
81 09 04 39 FF (inquiry block mode)
Expected response: 90 50 00 00 00 00 FF
"""
