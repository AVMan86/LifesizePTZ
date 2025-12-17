"""
Command Scheduler for LifeSize IR Bridge

Manages the timing-critical 57ms gaps between IR frames for smooth camera movement.
Handles:
- Movement state machine (idle, moving, stopping)
- Precise timing between IR frame transmissions
- Diagonal movement by alternating commands
- Queuing of new commands during transmission
- Safety timeout for runaway movement
"""

import time
from machine import Timer

from config import (
    IR_PACKET_GAP_US,
    SINGLE_PRESS_REPEATS,
    MOVEMENT_TIMEOUT_MS,
    MovementState,
    IRCommand,
    DEBUG_IR,
    DEBUG_TIMING,
)
from ir_transmitter import get_transmitter

# Derive millisecond values from config
IR_FRAME_GAP_MS = IR_PACKET_GAP_US // 1000  # ~57ms
IR_FRAME_CYCLE_MS = IR_FRAME_GAP_MS + 54    # Frame + gap (~111ms)


class CommandScheduler:
    """
    Schedules and manages IR command transmission with precise timing.

    The LifeSize camera requires a specific 57ms gap between IR frames
    for smooth acceleration. This scheduler ensures that timing is maintained
    even when network packets arrive at irregular intervals.
    """

    def __init__(self):
        self.transmitter = get_transmitter()
        self.state = MovementState.IDLE
        self.current_commands = []  # Current IR command(s) to repeat
        self.diagonal_index = 0     # For alternating diagonal commands
        self.last_transmit_time = 0
        self.movement_start_time = 0

        # Timer for scheduled transmission
        self.timer = None
        self.timer_active = False

        # Pending command queue
        self.pending_command = None
        self.stop_requested = False

    def start_movement(self, ir_commands: list):
        """
        Start continuous movement with the given IR command(s).

        Args:
            ir_commands: List of IR command codes. If multiple commands
                        (diagonal), they will be alternated.
        """
        if not ir_commands:
            return

        if DEBUG_IR:
            cmd_names = []
            for cmd in ir_commands:
                for name in dir(IRCommand):
                    if not name.startswith('_') and getattr(IRCommand, name) == cmd:
                        cmd_names.append(name)
                        break
            print(f"Scheduler: Starting movement {cmd_names}")

        self.current_commands = ir_commands
        self.diagonal_index = 0
        self.state = MovementState.MOVING
        self.movement_start_time = time.ticks_ms()
        self.stop_requested = False

        # Send first command immediately
        self._transmit_next()

        # Start the repeating timer
        self._start_timer()

    def stop_movement(self):
        """Stop the current movement."""
        if DEBUG_IR:
            print("Scheduler: Stopping movement")

        self.stop_requested = True
        self.state = MovementState.STOPPING
        self._stop_timer()

        # Clear state
        self.current_commands = []
        self.diagonal_index = 0
        self.state = MovementState.IDLE

    def send_single_press(self, ir_command: int, repeats: int = SINGLE_PRESS_REPEATS):
        """
        Send a single button press (not continuous movement).

        Args:
            ir_command: IR command code to send
            repeats: Number of times to repeat the frame
        """
        if DEBUG_IR:
            print(f"Scheduler: Single press 0x{ir_command:02X} x{repeats}")

        for i in range(repeats):
            self.transmitter.transmit_command(ir_command)
            if i < repeats - 1:
                time.sleep_ms(IR_FRAME_GAP_MS)

    def update(self):
        """
        Update the scheduler state (called from main loop).

        This handles timeout checking and any deferred operations.
        Returns True if currently moving, False otherwise.
        """
        if self.state == MovementState.IDLE:
            return False

        # Check for timeout
        if self.state == MovementState.MOVING:
            elapsed = time.ticks_diff(time.ticks_ms(), self.movement_start_time)
            if elapsed > MOVEMENT_TIMEOUT_MS:
                print("Scheduler: Movement timeout, stopping")
                self.stop_movement()
                return False

        return self.state == MovementState.MOVING

    def _transmit_next(self):
        """Transmit the next IR frame in the sequence."""
        if not self.current_commands or self.stop_requested:
            return

        # Select command (for diagonal, alternate between commands)
        if len(self.current_commands) == 1:
            cmd = self.current_commands[0]
        else:
            # Diagonal movement - alternate between pan and tilt
            cmd = self.current_commands[self.diagonal_index]
            self.diagonal_index = (self.diagonal_index + 1) % len(self.current_commands)

        # Transmit
        start = time.ticks_us()
        self.transmitter.transmit_command(cmd)
        self.last_transmit_time = time.ticks_ms()

        if DEBUG_TIMING:
            elapsed = time.ticks_diff(time.ticks_us(), start)
            print(f"Scheduler: TX took {elapsed}us")

    def _timer_callback(self, timer):
        """Timer callback for scheduled transmission."""
        if self.stop_requested or self.state != MovementState.MOVING:
            return

        # Check timing since last transmission
        now = time.ticks_ms()
        elapsed = time.ticks_diff(now, self.last_transmit_time)

        if DEBUG_TIMING:
            print(f"Scheduler: Timer callback, elapsed={elapsed}ms")

        # Transmit if enough time has passed
        if elapsed >= IR_FRAME_GAP_MS:
            self._transmit_next()

    def _start_timer(self):
        """Start the repeating timer for frame transmission."""
        if self.timer_active:
            return

        # Use hardware timer for precise intervals
        # The timer fires at the frame cycle rate (111ms)
        self.timer = Timer()
        self.timer.init(
            period=IR_FRAME_CYCLE_MS,
            mode=Timer.PERIODIC,
            callback=self._timer_callback
        )
        self.timer_active = True

        if DEBUG_IR:
            print(f"Scheduler: Timer started, period={IR_FRAME_CYCLE_MS}ms")

    def _stop_timer(self):
        """Stop the repeating timer."""
        if self.timer is not None:
            self.timer.deinit()
            self.timer = None
        self.timer_active = False

        if DEBUG_IR:
            print("Scheduler: Timer stopped")

    def is_moving(self) -> bool:
        """Check if currently in a movement state."""
        return self.state == MovementState.MOVING

    def get_state(self) -> int:
        """Get the current movement state."""
        return self.state


class PollingScheduler:
    """
    Simplified scheduler using polling.

    The IR transmitter handles all timing internally (57.3ms gap),
    so this scheduler just manages state and delegates to the transmitter.
    """

    def __init__(self):
        self.transmitter = get_transmitter()
        self.state = MovementState.IDLE
        self.current_commands = []
        self.diagonal_index = 0
        self.movement_start_time = 0
        self.stop_requested = False

    def start_movement(self, ir_commands: list):
        """Start continuous movement."""
        if not ir_commands:
            return

        # If already moving with the same commands, don't reset anything
        # This preserves the precise 57.3ms timing cadence
        if self.state == MovementState.MOVING and self.current_commands == ir_commands:
            if DEBUG_IR:
                print("PollingScheduler: Already moving with same commands, ignoring")
            return

        # If already moving but with different commands, just update the commands
        # without resetting timing - this allows smooth direction changes
        if self.state == MovementState.MOVING:
            if DEBUG_IR:
                print(f"PollingScheduler: Updating commands while moving")
            self.current_commands = ir_commands
            self.diagonal_index = 0
            self.movement_start_time = time.ticks_ms()  # Reset timeout for new direction
            # Don't reset timing - next frame will send at the natural 57.3ms cadence
            return

        # First time starting movement - reset timing so first frame sends immediately
        if DEBUG_IR:
            print(f"PollingScheduler: Starting movement with {len(ir_commands)} commands")

        self.transmitter.reset_timing()
        self.current_commands = ir_commands
        self.diagonal_index = 0
        self.state = MovementState.MOVING
        self.movement_start_time = time.ticks_ms()
        self.stop_requested = False

    def stop_movement(self):
        """Stop movement."""
        if self.state != MovementState.IDLE:
            if DEBUG_IR:
                print("PollingScheduler: Stopping")

            self.stop_requested = True
            self.current_commands = []
            self.state = MovementState.IDLE
            self.transmitter.stop()  # Reset timing for next movement

    def poll(self) -> bool:
        """
        Poll the scheduler - call this frequently from the main loop.

        The IR transmitter handles the 57.3ms gap timing internally,
        so we can poll as often as we like - it will only send when ready.

        Returns True if a transmission occurred, False otherwise.
        """
        if self.state != MovementState.MOVING or self.stop_requested:
            return False

        # Check for safety timeout
        elapsed_total = time.ticks_diff(time.ticks_ms(), self.movement_start_time)
        if elapsed_total > MOVEMENT_TIMEOUT_MS:
            print("PollingScheduler: Timeout - stopping")
            self.stop_movement()
            return False

        # Check if transmitter is ready (gap has elapsed)
        if not self._transmitter_ready():
            return False  # Not ready yet, return quickly to allow packet checks

        # Transmit next frame
        self._transmit_next()
        return True

    def _transmitter_ready(self) -> bool:
        """Check if enough time has passed since last frame for the gap."""
        if self.transmitter.last_frame_end_us == 0:
            return True  # First frame, always ready

        now = time.ticks_us()
        elapsed = time.ticks_diff(now, self.transmitter.last_frame_end_us)
        return elapsed >= IR_PACKET_GAP_US

    def _transmit_next(self):
        """Transmit next frame."""
        if not self.current_commands:
            return

        # Select command (alternate for diagonal movement)
        if len(self.current_commands) == 1:
            cmd = self.current_commands[0]
        else:
            cmd = self.current_commands[self.diagonal_index]
            self.diagonal_index = (self.diagonal_index + 1) % len(self.current_commands)

        self.transmitter.transmit_command(cmd)

    def send_single_press(self, ir_command: int, repeats: int = SINGLE_PRESS_REPEATS):
        """Send a single button press."""
        self.transmitter.reset_timing()  # Start immediately
        self.transmitter.transmit_command(ir_command, repeats)

    def is_moving(self) -> bool:
        return self.state == MovementState.MOVING


# =============================================================================
# Module-level instance
# =============================================================================

_scheduler = None


def get_scheduler(use_timer: bool = False):
    """
    Get or create the scheduler instance.

    Args:
        use_timer: If True, use hardware timer (may conflict with network).
                  If False, use polling scheduler (recommended).
    """
    global _scheduler
    if _scheduler is None:
        if use_timer:
            _scheduler = CommandScheduler()
        else:
            _scheduler = PollingScheduler()
    return _scheduler


# =============================================================================
# Test code
# =============================================================================

if __name__ == "__main__":
    print("Command Scheduler Test")
    print("=" * 50)

    # Use polling scheduler for testing
    scheduler = PollingScheduler()

    print("\nTest 1: Single press UP")
    scheduler.send_single_press(IRCommand.UP, repeats=3)

    time.sleep(1)

    print("\nTest 2: Continuous RIGHT for 3 seconds")
    scheduler.start_movement([IRCommand.RIGHT])

    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < 3000:
        scheduler.poll()
        time.sleep_ms(10)  # Small delay to prevent tight loop

    scheduler.stop_movement()

    time.sleep(1)

    print("\nTest 3: Diagonal UP-LEFT for 2 seconds")
    scheduler.start_movement([IRCommand.UP, IRCommand.LEFT])

    start = time.ticks_ms()
    while time.ticks_diff(time.ticks_ms(), start) < 2000:
        scheduler.poll()
        time.sleep_ms(10)

    scheduler.stop_movement()

    print("\nTests complete")
