import os
import sys
import time
import subprocess
import logging
import signal
import psutil
import threading
import socket
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional, Dict, Any
from gpiozero import Button, LED, GPIOPinInUse, BadPinFactory
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configuration
LOG_FILE = os.getenv("LOG_FILE", "./logs.log")
PID_FILE = os.getenv("PID_FILE", "./launch-game.pid")
BUTTON_GPIO = int(os.getenv("BUTTON_GPIO", "17"))
LED_GPIO = int(os.getenv("LED_GPIO", "27"))
MOONLIGHT_HOST = os.getenv("MOONLIGHT_HOST", "192.168.1.100")
HEALTH_CHECK_INTERVAL = int(os.getenv("HEALTH_CHECK_INTERVAL", "30"))  # seconds
CONNECTION_TIMEOUT = int(os.getenv("CONNECTION_TIMEOUT", "10"))  # seconds
MAX_RESTART_ATTEMPTS = int(os.getenv("MAX_RESTART_ATTEMPTS", "3"))
PROCESS_CHECK_INTERVAL = int(os.getenv("PROCESS_CHECK_INTERVAL", "5"))  # seconds

class StreamState(Enum):
    """Enumeration for stream states"""
    IDLE = "idle"
    STARTING = "starting"
    RUNNING = "running"
    STOPPING = "stopping"
    ERROR = "error"
    UNKNOWN = "unknown"

class ButtonHandler:
    """Enhanced button handler with comprehensive error handling and monitoring"""
    
    def __init__(self):
        self.current_state = StreamState.IDLE
        self.button = None
        self.led = None
        self.logger = None
        self.monitoring_thread = None
        self.shutdown_event = threading.Event()
        self.last_button_press = None
        self.restart_attempts = 0
        self.last_health_check = None
        self.process_monitor_thread = None
        
        # Initialize components
        self._setup_logging()
        self._setup_hardware()
        self._setup_signal_handlers()
        self._start_monitoring()
        
    def _setup_logging(self):
        """Setup comprehensive logging with multiple levels and handlers"""
        self.logger = logging.getLogger("ButtonHandler")
        self.logger.setLevel(logging.DEBUG)
        
        # Clear any existing handlers
        self.logger.handlers.clear()
        
        # Custom formatter with more details
        formatter = CustomFormatter()
        
        # File handler for all logs
        file_handler = logging.FileHandler(LOG_FILE)
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # Console handler for important messages
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # Error file handler for errors only
        error_handler = logging.FileHandler(LOG_FILE.replace('.log', '_errors.log'))
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        self.logger.addHandler(error_handler)
        
        self.logger.info("=== Button Handler Starting ===")
        self.logger.info(f"Configuration: GPIO Button={BUTTON_GPIO}, LED={LED_GPIO}")
        self.logger.info(f"Host: {MOONLIGHT_HOST}, Health Check: {HEALTH_CHECK_INTERVAL}s")
        
    def _setup_hardware(self):
        """Setup GPIO hardware with comprehensive error handling"""
        try:
            # Test GPIO availability first
            self.logger.debug(f"Initializing button on GPIO {BUTTON_GPIO}")
            self.button = Button(BUTTON_GPIO, pull_up=False, bounce_time=0.2)
            self.button.when_pressed = self._on_button_press
            self.logger.info(f"Button initialized successfully on GPIO {BUTTON_GPIO}")
            
            self.logger.debug(f"Initializing LED on GPIO {LED_GPIO}")
            self.led = LED(LED_GPIO)
            
            # Test LED functionality
            self._test_led()
            self.logger.info(f"LED initialized successfully on GPIO {LED_GPIO}")
            
        except GPIOPinInUse as e:
            self.logger.error(f"GPIO pin already in use: {e}")
            self.logger.error("Another process may be using the GPIO pins. Check running services.")
            raise
        except BadPinFactory as e:
            self.logger.error(f"GPIO pin factory error: {e}")
            self.logger.error("GPIO hardware may not be available or configured correctly")
            raise
        except Exception as e:
            self.logger.error(f"Hardware initialization failed: {e}")
            self.logger.error(f"Error type: {type(e).__name__}")
            raise
            
    def _test_led(self):
        """Test LED functionality during startup"""
        try:
            self.logger.debug("Testing LED functionality...")
            for i in range(3):
                self.led.on()
                time.sleep(0.1)
                self.led.off()
                time.sleep(0.1)
            self.logger.debug("LED test completed successfully")
        except Exception as e:
            self.logger.warning(f"LED test failed: {e}")
            
    def _setup_signal_handlers(self):
        """Setup signal handlers for graceful shutdown"""
        def signal_handler(signum, frame):
            signal_name = signal.Signals(signum).name
            self.logger.info(f"Received signal {signal_name}. Initiating graceful shutdown...")
            self.shutdown()
            
        signal.signal(signal.SIGINT, signal_handler)
        signal.signal(signal.SIGTERM, signal_handler)
        
    def _start_monitoring(self):
        """Start background monitoring threads"""
        # Health monitoring thread
        self.monitoring_thread = threading.Thread(
            target=self._health_monitor,
            name="HealthMonitor",
            daemon=True
        )
        self.monitoring_thread.start()
        self.logger.info("Health monitoring thread started")
        
        # Process monitoring thread
        self.process_monitor_thread = threading.Thread(
            target=self._process_monitor,
            name="ProcessMonitor", 
            daemon=True
        )
        self.process_monitor_thread.start()
        self.logger.info("Process monitoring thread started")
        
    def _health_monitor(self):
        """Background thread for health monitoring"""
        while not self.shutdown_event.is_set():
            try:
                self._perform_health_check()
                self.shutdown_event.wait(HEALTH_CHECK_INTERVAL)
            except Exception as e:
                self.logger.error(f"Health monitor error: {e}")
                self.shutdown_event.wait(5)  # Wait 5 seconds before retry
                
    def _process_monitor(self):
        """Background thread for process state monitoring"""
        while not self.shutdown_event.is_set():
            try:
                self._check_process_state()
                self.shutdown_event.wait(PROCESS_CHECK_INTERVAL)
            except Exception as e:
                self.logger.error(f"Process monitor error: {e}")
                self.shutdown_event.wait(5)
                
    def _perform_health_check(self):
        """Perform comprehensive health checks"""
        self.last_health_check = datetime.now()
        
        # Check PID file consistency
        self._check_pid_file_health()
        
        # Check network connectivity to gaming PC
        self._check_network_connectivity()
        
        # Check system resources
        self._check_system_resources()
        
        # Validate current state
        self._validate_current_state()
        
    def _check_pid_file_health(self):
        """Check PID file for stale or invalid entries"""
        if not os.path.exists(PID_FILE):
            if self.current_state == StreamState.RUNNING:
                self.logger.warning("PID file missing but state is RUNNING. Resetting state.")
                self._set_state(StreamState.IDLE)
            return
            
        try:
            with open(PID_FILE, 'r') as f:
                pid_str = f.read().strip()
                
            if not pid_str.isdigit():
                self.logger.error(f"Invalid PID in file: '{pid_str}'. Cleaning up.")
                self._cleanup_pid_file()
                return
                
            pid = int(pid_str)
            
            # Check if process exists and is actually moonlight
            if not psutil.pid_exists(pid):
                self.logger.warning(f"Process {pid} no longer exists. Cleaning up PID file.")
                self._cleanup_pid_file()
                return
                
            try:
                process = psutil.Process(pid)
                cmdline = ' '.join(process.cmdline()).lower()
                
                if 'moonlight' not in cmdline:
                    self.logger.warning(f"Process {pid} is not moonlight: {cmdline}")
                    self._cleanup_pid_file()
                    return
                    
                # Check process status
                status = process.status()
                if status in [psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD]:
                    self.logger.warning(f"Moonlight process {pid} is {status}. Cleaning up.")
                    self._cleanup_pid_file()
                    return
                    
                self.logger.debug(f"Process {pid} is healthy (status: {status})")
                
            except psutil.NoSuchProcess:
                self.logger.warning(f"Process {pid} disappeared during check")
                self._cleanup_pid_file()
                
        except Exception as e:
            self.logger.error(f"Error checking PID file health: {e}")
            self._cleanup_pid_file()
            
    def _check_network_connectivity(self):
        """Check network connectivity to gaming PC"""
        try:
            # Quick ping test
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(CONNECTION_TIMEOUT)
                result = sock.connect_ex((MOONLIGHT_HOST, 47989))  # Sunshine default port
                
                if result == 0:
                    self.logger.debug(f"Network connectivity to {MOONLIGHT_HOST} OK")
                else:
                    self.logger.warning(f"Cannot connect to {MOONLIGHT_HOST}:47989")
                    
        except Exception as e:
            self.logger.warning(f"Network connectivity check failed: {e}")
            
    def _check_system_resources(self):
        """Check system resource usage"""
        try:
            # Check memory usage
            memory = psutil.virtual_memory()
            if memory.percent > 90:
                self.logger.warning(f"High memory usage: {memory.percent:.1f}%")
                
            # Check CPU usage
            cpu_percent = psutil.cpu_percent(interval=1)
            if cpu_percent > 90:
                self.logger.warning(f"High CPU usage: {cpu_percent:.1f}%")
                
            # Check disk space
            disk = psutil.disk_usage('/')
            if disk.percent > 90:
                self.logger.warning(f"High disk usage: {disk.percent:.1f}%")
                
            self.logger.debug(f"System resources: CPU {cpu_percent:.1f}%, RAM {memory.percent:.1f}%, Disk {disk.percent:.1f}%")
            
        except Exception as e:
            self.logger.error(f"System resource check failed: {e}")
            
    def _validate_current_state(self):
        """Validate and correct current state if needed"""
        actual_running = self._is_process_running()
        
        if self.current_state == StreamState.RUNNING and not actual_running:
            self.logger.warning("State mismatch: RUNNING but no process found. Correcting to IDLE.")
            self._set_state(StreamState.IDLE)
            self._set_led_state()
            
        elif self.current_state == StreamState.IDLE and actual_running:
            self.logger.warning("State mismatch: IDLE but process found. Correcting to RUNNING.")
            self._set_state(StreamState.RUNNING)
            self._set_led_state()
            
    def _check_process_state(self):
        """Monitor process state changes"""
        if self.current_state in [StreamState.STARTING, StreamState.STOPPING]:
            # Check if state has been stuck for too long
            if hasattr(self, '_state_change_time'):
                elapsed = datetime.now() - self._state_change_time
                if elapsed > timedelta(seconds=120):  # 2 minutes timeout
                    self.logger.error(f"State {self.current_state.value} stuck for {elapsed}. Resetting to IDLE.")
                    self._set_state(StreamState.IDLE)
                    self._cleanup_pid_file()
                    self._set_led_state()
                    
    def _is_process_running(self) -> bool:
        """Enhanced process running check with detailed logging"""
        if not os.path.exists(PID_FILE):
            self.logger.debug("No PID file exists")
            return False
            
        try:
            with open(PID_FILE, 'r') as f:
                pid_str = f.read().strip()
                
            if not pid_str.isdigit():
                self.logger.error(f"Invalid PID format in file: '{pid_str}'")
                self._cleanup_pid_file()
                return False
                
            pid = int(pid_str)
            self.logger.debug(f"Checking process PID: {pid}")
            
            if not psutil.pid_exists(pid):
                self.logger.debug(f"Process {pid} does not exist")
                self._cleanup_pid_file()
                return False
                
            try:
                process = psutil.Process(pid)
                cmdline = ' '.join(process.cmdline()).lower()
                status = process.status()
                
                self.logger.debug(f"Process {pid}: status={status}, cmdline='{cmdline}'")
                
                if 'moonlight' not in cmdline:
                    self.logger.warning(f"Process {pid} is not moonlight: {cmdline}")
                    self._cleanup_pid_file()
                    return False
                    
                if status in [psutil.STATUS_ZOMBIE, psutil.STATUS_DEAD]:
                    self.logger.warning(f"Process {pid} is {status}")
                    self._cleanup_pid_file()
                    return False
                    
                self.logger.debug(f"Process {pid} is running and healthy")
                return True
                
            except psutil.NoSuchProcess:
                self.logger.debug(f"Process {pid} no longer exists")
                self._cleanup_pid_file()
                return False
                
        except Exception as e:
            self.logger.error(f"Error checking process state: {e}")
            self._cleanup_pid_file()
            return False
            
    def _cleanup_pid_file(self):
        """Safely clean up PID file"""
        try:
            if os.path.exists(PID_FILE):
                os.remove(PID_FILE)
                self.logger.info("PID file cleaned up")
        except Exception as e:
            self.logger.error(f"Failed to cleanup PID file: {e}")
            
    def _set_state(self, new_state: StreamState):
        """Set current state with logging"""
        if self.current_state != new_state:
            old_state = self.current_state
            self.current_state = new_state
            self._state_change_time = datetime.now()
            self.logger.info(f"State changed: {old_state.value} → {new_state.value}")
            
    def _set_led_state(self):
        """Set LED based on current state"""
        try:
            if self.current_state == StreamState.IDLE:
                self.led.off()
            elif self.current_state == StreamState.STARTING:
                self.led.blink(on_time=0.5, off_time=0.5)
            elif self.current_state == StreamState.RUNNING:
                self.led.on()
            elif self.current_state == StreamState.STOPPING:
                self.led.blink(on_time=0.1, off_time=0.1)
            elif self.current_state == StreamState.ERROR:
                self.led.blink(on_time=0.05, off_time=0.05)  # Very fast blink for errors
                
        except Exception as e:
            self.logger.error(f"Failed to set LED state: {e}")
            
    def _on_button_press(self):
        """Enhanced button press handler with debouncing and state management"""
        current_time = datetime.now()
        
        # Debouncing: ignore rapid button presses
        if (self.last_button_press and 
            current_time - self.last_button_press < timedelta(seconds=2)):
            self.logger.debug("Button press ignored (debouncing)")
            return
            
        self.last_button_press = current_time
        
        self.logger.info(f"Button pressed! Current state: {self.current_state.value}")
        
        # Prevent action if already in transition
        if self.current_state in [StreamState.STARTING, StreamState.STOPPING]:
            self.logger.warning(f"Ignoring button press - system busy ({self.current_state.value})")
            return
            
        try:
            if self.current_state in [StreamState.RUNNING]:
                self._stop_stream()
            elif self.current_state in [StreamState.IDLE, StreamState.ERROR]:
                self._start_stream()
            else:
                self.logger.warning(f"Button press in unexpected state: {self.current_state.value}")
                
        except Exception as e:
            self.logger.error(f"Error handling button press: {e}")
            self._set_state(StreamState.ERROR)
            self._set_led_state()
            
    def _start_stream(self):
        """Enhanced stream start with comprehensive error handling"""
        self.logger.info("=== Starting Stream Sequence ===")
        self._set_state(StreamState.STARTING)
        self._set_led_state()
        
        try:
            # Pre-flight checks
            self._perform_preflight_checks()
            
            # Execute start script
            self.logger.info("Executing launch script...")
            result = subprocess.run(
                ["./launch-game.sh", "start"],
                capture_output=True,
                text=True,
                timeout=180,  # 3 minute timeout
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            
            if result.returncode == 0:
                self.logger.info("Launch script completed successfully")
                self.logger.debug(f"Script output: {result.stdout}")
                
                # Wait for process to appear
                if self._wait_for_process_start():
                    self._set_state(StreamState.RUNNING)
                    self.restart_attempts = 0  # Reset counter on success
                    self.logger.info("=== Stream Started Successfully ===")
                else:
                    raise Exception("Process did not start within expected time")
                    
            else:
                error_msg = f"Launch script failed (exit code {result.returncode})"
                if result.stderr:
                    error_msg += f": {result.stderr}"
                raise Exception(error_msg)
                
        except subprocess.TimeoutExpired:
            self.logger.error("Launch script timed out after 3 minutes")
            self._handle_start_failure("Script timeout")
            
        except Exception as e:
            self.logger.error(f"Stream start failed: {e}")
            self._handle_start_failure(str(e))
            
        finally:
            self._set_led_state()
            
    def _stop_stream(self):
        """Enhanced stream stop with comprehensive error handling"""
        self.logger.info("=== Stopping Stream Sequence ===")
        self._set_state(StreamState.STOPPING)
        self._set_led_state()
        
        try:
            # Execute stop script
            self.logger.info("Executing stop script...")
            result = subprocess.run(
                ["./launch-game.sh", "stop"],
                capture_output=True,
                text=True,
                timeout=60,  # 1 minute timeout
                cwd=os.path.dirname(os.path.abspath(__file__))
            )
            
            if result.returncode == 0:
                self.logger.info("Stop script completed successfully")
                self.logger.debug(f"Script output: {result.stdout}")
            else:
                self.logger.warning(f"Stop script returned non-zero exit code: {result.returncode}")
                if result.stderr:
                    self.logger.warning(f"Script stderr: {result.stderr}")
                    
            # Force cleanup regardless of script result
            self._force_cleanup()
            
            # Wait for process to stop
            if self._wait_for_process_stop():
                self._set_state(StreamState.IDLE)
                self.logger.info("=== Stream Stopped Successfully ===")
            else:
                self.logger.warning("Process may still be running, but continuing with stop sequence")
                self._set_state(StreamState.IDLE)
                
        except subprocess.TimeoutExpired:
            self.logger.error("Stop script timed out. Forcing cleanup...")
            self._force_cleanup()
            self._set_state(StreamState.IDLE)
            
        except Exception as e:
            self.logger.error(f"Error during stop sequence: {e}")
            self._force_cleanup()
            self._set_state(StreamState.IDLE)
            
        finally:
            self._set_led_state()
            
    def _perform_preflight_checks(self):
        """Perform checks before starting stream"""
        self.logger.debug("Performing preflight checks...")
        
        # Check if script exists and is executable
        script_path = "./launch-game.sh"
        if not os.path.exists(script_path):
            raise Exception(f"Launch script not found: {script_path}")
            
        if not os.access(script_path, os.X_OK):
            raise Exception(f"Launch script not executable: {script_path}")
            
        # Check network connectivity
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(CONNECTION_TIMEOUT)
                result = sock.connect_ex((MOONLIGHT_HOST, 47989))
                if result != 0:
                    self.logger.warning(f"Cannot reach gaming PC at {MOONLIGHT_HOST}:47989")
        except Exception as e:
            self.logger.warning(f"Network preflight check failed: {e}")
            
        self.logger.debug("Preflight checks completed")
        
    def _wait_for_process_start(self, timeout: int = 60) -> bool:
        """Wait for moonlight process to start"""
        self.logger.debug(f"Waiting up to {timeout}s for process to start...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if self._is_process_running():
                elapsed = time.time() - start_time
                self.logger.info(f"Process started after {elapsed:.1f}s")
                return True
            time.sleep(2)
            
        self.logger.error(f"Process did not start within {timeout}s")
        return False
        
    def _wait_for_process_stop(self, timeout: int = 30) -> bool:
        """Wait for moonlight process to stop"""
        self.logger.debug(f"Waiting up to {timeout}s for process to stop...")
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            if not self._is_process_running():
                elapsed = time.time() - start_time
                self.logger.info(f"Process stopped after {elapsed:.1f}s")
                return True
            time.sleep(1)
            
        self.logger.warning(f"Process did not stop within {timeout}s")
        return False
        
    def _force_cleanup(self):
        """Force cleanup of any remaining processes and files"""
        self.logger.debug("Performing force cleanup...")
        
        # Clean PID file
        self._cleanup_pid_file()
        
        # Try to kill any remaining moonlight processes
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                cmdline = ' '.join(proc.info['cmdline'] or []).lower()
                if 'moonlight' in cmdline and 'stream' in cmdline:
                    self.logger.warning(f"Killing orphaned moonlight process {proc.info['pid']}")
                    proc.kill()
        except Exception as e:
            self.logger.error(f"Error during force cleanup: {e}")
            
    def _handle_start_failure(self, error_msg: str):
        """Handle stream start failure with retry logic"""
        self.restart_attempts += 1
        self.logger.error(f"Start attempt {self.restart_attempts} failed: {error_msg}")
        
        if self.restart_attempts < MAX_RESTART_ATTEMPTS:
            self.logger.info(f"Will retry in 10 seconds (attempt {self.restart_attempts + 1}/{MAX_RESTART_ATTEMPTS})")
            self._set_state(StreamState.IDLE)
            # Could implement automatic retry here
        else:
            self.logger.error(f"Maximum restart attempts ({MAX_RESTART_ATTEMPTS}) reached. Entering error state.")
            self._set_state(StreamState.ERROR)
            self.restart_attempts = 0  # Reset for next manual attempt
            
    def run(self):
        """Main run loop"""
        self.logger.info("Button handler ready. Press button to control stream.")
        
        try:
            while not self.shutdown_event.is_set():
                time.sleep(1)
        except Exception as e:
            self.logger.error(f"Unexpected error in main loop: {e}")
            raise
            
    def shutdown(self):
        """Graceful shutdown"""
        self.logger.info("Initiating graceful shutdown...")
        
        # Signal threads to stop
        self.shutdown_event.set()
        
        # Turn off LED
        if self.led:
            try:
                self.led.off()
            except Exception as e:
                self.logger.error(f"Error turning off LED: {e}")
                
        # Wait for threads
        if self.monitoring_thread and self.monitoring_thread.is_alive():
            self.logger.debug("Waiting for monitoring thread...")
            self.monitoring_thread.join(timeout=5)
            
        if self.process_monitor_thread and self.process_monitor_thread.is_alive():
            self.logger.debug("Waiting for process monitor thread...")
            self.process_monitor_thread.join(timeout=5)
            
        # Clean up GPIO
        if self.button:
            try:
                self.button.close()
            except Exception as e:
                self.logger.error(f"Error closing button: {e}")
                
        if self.led:
            try:
                self.led.close()
            except Exception as e:
                self.logger.error(f"Error closing LED: {e}")
                
        self.logger.info("=== Button Handler Shutdown Complete ===")
        
class CustomFormatter(logging.Formatter):
    """Enhanced formatter with more detailed information"""
    def format(self, record):
        timestamp = datetime.now().strftime('%d.%m.%Y %H:%M:%S.%f')[:-3]  # Include milliseconds
        thread_name = threading.current_thread().name
        return f"[{timestamp}] [{record.levelname}] [{thread_name}] [ButtonHandler] {record.getMessage()}"

def main():
    """Main entry point with comprehensive error handling"""
    handler = None
    try:
        # Create and run button handler
        handler = ButtonHandler()
        handler.run()
        
    except KeyboardInterrupt:
        print("\nReceived keyboard interrupt...")
        
    except Exception as e:
        print(f"Fatal error: {e}")
        if handler and handler.logger:
            handler.logger.error(f"Fatal error: {e}")
        sys.exit(1)
        
    finally:
        if handler:
            handler.shutdown()

if __name__ == "__main__":
    main()
