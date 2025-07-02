#!/bin/bash
set -euo pipefail  # Enhanced error handling: exit on error, undefined vars, pipe failures

# Script metadata and configuration
readonly SCRIPT_NAME="$(basename "$0")"
readonly SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
readonly SCRIPT_VERSION="2.0.0"
readonly SCRIPT_START_TIME="$(date '+%s')"

# Default configuration values
DEFAULT_BOOT_WAIT_TIME=30
DEFAULT_CONNECTION_TIMEOUT=10
DEFAULT_MAX_RETRIES=3
DEFAULT_RETRY_DELAY=5
DEFAULT_CEC_TIMEOUT=5
DEFAULT_WOL_RETRIES=2
DEFAULT_PROCESS_WAIT_TIMEOUT=60

# Load environment variables safely with validation
load_environment() {
    local env_file="${SCRIPT_DIR}/.env"
    
    if [[ ! -f "$env_file" ]]; then
        log "ERROR" "Environment file not found: $env_file"
        exit 1
    fi
    
    # Source environment with error checking
    set -a
    if ! source "$env_file"; then
        log "ERROR" "Failed to load environment file: $env_file"
        exit 1
    fi
    set +a
    
    # Validate required environment variables
    validate_environment
}

# Enhanced logging with multiple levels and better formatting
log() {
    local level="$1"
    local message="$2"
    local timestamp="$(date '+%d.%m.%Y %H:%M:%S.%3N')"
    local thread_id="$$"
    local log_entry="[${timestamp}] [${level}] [${thread_id}] [LaunchGame] ${message}"
    
    # Always log to file if LOG_FILE is set
    if [[ -n "${LOG_FILE:-}" ]]; then
        echo "$log_entry" >> "$LOG_FILE"
    fi
    
    # Also log to stderr for ERROR and WARN levels
    case "$level" in
        "ERROR"|"WARN")
            echo "$log_entry" >&2
            ;;
        "DEBUG")
            # Only show debug if DEBUG mode is enabled
            [[ "${DEBUG:-false}" == "true" ]] && echo "$log_entry" >&2
            ;;
        *)
            # INFO and other levels to stderr in verbose mode
            [[ "${VERBOSE:-false}" == "true" ]] && echo "$log_entry" >&2
            ;;
    esac
}

# Comprehensive environment validation
validate_environment() {
    local required_vars=("LOG_FILE" "PID_FILE" "PC_MAC" "MOONLIGHT_HOST" "MOONLIGHT_APP" "TV_CEC_NAME")
    local missing_vars=()
    
    log "DEBUG" "Validating environment variables..."
    
    for var in "${required_vars[@]}"; do
        if [[ -z "${!var:-}" ]]; then
            missing_vars+=("$var")
        fi
    done
    
    if [[ ${#missing_vars[@]} -gt 0 ]]; then
        log "ERROR" "Missing required environment variables: ${missing_vars[*]}"
        exit 1
    fi
    
    # Validate MAC address format
    if ! [[ "$PC_MAC" =~ ^([0-9A-Fa-f]{2}[:-]){5}([0-9A-Fa-f]{2})$ ]]; then
        log "ERROR" "Invalid MAC address format: $PC_MAC"
        exit 1
    fi
    
    # Validate IP address format
    if ! [[ "$MOONLIGHT_HOST" =~ ^[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,3}$ ]]; then
        log "ERROR" "Invalid IP address format: $MOONLIGHT_HOST"
        exit 1
    fi
    
    # Set default values for optional variables
    BOOT_WAIT_TIME="${BOOT_WAIT_TIME:-$DEFAULT_BOOT_WAIT_TIME}"
    CONNECTION_TIMEOUT="${CONNECTION_TIMEOUT:-$DEFAULT_CONNECTION_TIMEOUT}"
    MAX_RETRIES="${MAX_RETRIES:-$DEFAULT_MAX_RETRIES}"
    RETRY_DELAY="${RETRY_DELAY:-$DEFAULT_RETRY_DELAY}"
    CEC_TIMEOUT="${CEC_TIMEOUT:-$DEFAULT_CEC_TIMEOUT}"
    WOL_RETRIES="${WOL_RETRIES:-$DEFAULT_WOL_RETRIES}"
    PROCESS_WAIT_TIMEOUT="${PROCESS_WAIT_TIMEOUT:-$DEFAULT_PROCESS_WAIT_TIMEOUT}"
    
    log "INFO" "Environment validation successful"
    log "DEBUG" "Configuration: MAC=$PC_MAC, Host=$MOONLIGHT_HOST, App='$MOONLIGHT_APP'"
    log "DEBUG" "Timing: Boot wait=${BOOT_WAIT_TIME}s, Timeout=${CONNECTION_TIMEOUT}s, Retries=$MAX_RETRIES"
}

# Enhanced dependency checking
check_dependencies() {
    local deps=("cec-client" "wakeonlan" "moonlight" "ping" "nc")
    local missing_deps=()
    
    log "DEBUG" "Checking system dependencies..."
    
    for dep in "${deps[@]}"; do
        if ! command -v "$dep" >/dev/null 2>&1; then
            missing_deps+=("$dep")
        fi
    done
    
    if [[ ${#missing_deps[@]} -gt 0 ]]; then
        log "ERROR" "Missing required dependencies: ${missing_deps[*]}"
        log "ERROR" "Install missing dependencies and try again"
        exit 1
    fi
    
    log "DEBUG" "All dependencies available"
}

# Network connectivity testing with retries
test_network_connectivity() {
    local host="$1"
    local timeout="${2:-$CONNECTION_TIMEOUT}"
    local retries="${3:-3}"
    
    log "DEBUG" "Testing network connectivity to $host (timeout: ${timeout}s, retries: $retries)"
    
    for ((i=1; i<=retries; i++)); do
        # Test basic ping connectivity
        if ping -c 1 -W "$timeout" "$host" >/dev/null 2>&1; then
            log "DEBUG" "Ping to $host successful (attempt $i/$retries)"
            
            # Test specific Sunshine port (47989) if available
            if nc -z -w "$timeout" "$host" 47989 >/dev/null 2>&1; then
                log "DEBUG" "Sunshine port (47989) accessible on $host"
                return 0
            else
                log "WARN" "Sunshine port (47989) not accessible on $host, but host is reachable"
                return 0  # Host is reachable even if Sunshine isn't ready
            fi
        fi
        
        if [[ $i -lt $retries ]]; then
            log "WARN" "Network test failed (attempt $i/$retries), retrying in ${RETRY_DELAY}s..."
            sleep "$RETRY_DELAY"
        fi
    done
    
    log "ERROR" "Network connectivity test failed after $retries attempts"
    return 1
}

# Enhanced CEC control with validation and error handling
cec_command() {
    local command="$1"
    local description="$2"
    local timeout="${3:-$CEC_TIMEOUT}"
    
    log "INFO" "$description"
    log "DEBUG" "Executing CEC command: $command (timeout: ${timeout}s)"
    
    # Check if cec-client is available
    if ! command -v cec-client >/dev/null 2>&1; then
        log "ERROR" "cec-client not found. Cannot control TV."
        return 1
    fi
    
    # Execute CEC command with timeout
    if timeout "$timeout" cec-client -s -d 1 <<< "$command" >/dev/null 2>&1; then
        log "DEBUG" "CEC command successful: $command"
        return 0
    else
        log "WARN" "CEC command failed or timed out: $command"
        log "WARN" "TV may not support CEC or HDMI-CEC may be disabled"
        return 1
    fi
}

# Advanced Wake-on-LAN with multiple attempts and validation
send_wake_on_lan() {
    local mac="$1"
    local retries="${2:-$WOL_RETRIES}"
    
    log "INFO" "Sending Wake-on-LAN to $mac"
    
    for ((i=1; i<=retries; i++)); do
        log "DEBUG" "WoL attempt $i/$retries to $mac"
        
        if wakeonlan "$mac" >/dev/null 2>&1; then
            log "DEBUG" "WoL packet sent successfully (attempt $i)"
            
            # Wait a moment between attempts
            if [[ $i -lt $retries ]]; then
                sleep 2
            fi
        else
            log "ERROR" "Failed to send WoL packet (attempt $i)"
            if [[ $i -eq $retries ]]; then
                return 1
            fi
        fi
    done
    
    return 0
}

# Smart wait for PC boot with connectivity testing
wait_for_pc_boot() {
    local wait_time="$1"
    local check_interval=5
    local max_checks=$((wait_time / check_interval))
    
    log "INFO" "Waiting for PC to boot (up to ${wait_time}s with connectivity testing)..."
    
    for ((i=1; i<=max_checks; i++)); do
        local elapsed=$((i * check_interval))
        
        # Test connectivity every check_interval seconds
        if test_network_connectivity "$MOONLIGHT_HOST" 3 1; then
            log "INFO" "PC is responsive after ${elapsed}s (ahead of schedule!)"
            return 0
        fi
        
        log "DEBUG" "Boot wait progress: ${elapsed}/${wait_time}s (PC not yet responsive)"
        sleep "$check_interval"
    done
    
    # Final connectivity test
    if test_network_connectivity "$MOONLIGHT_HOST" "$CONNECTION_TIMEOUT" 1; then
        log "INFO" "PC is responsive after full wait period"
        return 0
    else
        log "WARN" "PC may not be fully ready, but proceeding with stream attempt"
        return 1
    fi
}

# Comprehensive process management and PID handling
cleanup_existing_process() {
    log "DEBUG" "Checking for existing processes..."
    
    if [[ ! -f "$PID_FILE" ]]; then
        log "DEBUG" "No PID file found, no cleanup needed"
        return 0
    fi
    
    local pid
    if ! pid="$(cat "$PID_FILE" 2>/dev/null)" || [[ ! "$pid" =~ ^[0-9]+$ ]]; then
        log "WARN" "Invalid PID file content, removing: $PID_FILE"
        rm -f "$PID_FILE"
        return 0
    fi
    
    log "DEBUG" "Found PID file with PID: $pid"
    
    # Check if process exists and is actually moonlight
    if kill -0 "$pid" 2>/dev/null; then
        local cmdline
        if cmdline="$(ps -p "$pid" -o cmd= 2>/dev/null)" && [[ "$cmdline" == *moonlight* ]]; then
            log "WARN" "Active Moonlight process found (PID: $pid). Terminating..."
            
            # Graceful termination first
            if kill -TERM "$pid" 2>/dev/null; then
                # Wait for graceful shutdown
                for ((i=1; i<=10; i++)); do
                    if ! kill -0 "$pid" 2>/dev/null; then
                        log "INFO" "Process terminated gracefully"
                        break
                    fi
                    sleep 1
                done
                
                # Force kill if still running
                if kill -0 "$pid" 2>/dev/null; then
                    log "WARN" "Process did not terminate gracefully, forcing..."
                    kill -KILL "$pid" 2>/dev/null || true
                fi
            fi
        else
            log "DEBUG" "PID $pid exists but is not Moonlight process"
        fi
    else
        log "DEBUG" "PID $pid no longer exists"
    fi
    
    # Clean up PID file
    rm -f "$PID_FILE"
    log "DEBUG" "PID file cleaned up"
}

# Enhanced Moonlight launch with comprehensive error handling
launch_moonlight() {
    local app="$1"
    local host="$2"
    
    log "INFO" "Launching Moonlight stream: '$app' on $host"
    
    # Setup runtime environment
    export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/tmp/xdg-$$}"
    mkdir -p "$XDG_RUNTIME_DIR"
    log "DEBUG" "XDG_RUNTIME_DIR set to: $XDG_RUNTIME_DIR"
    
    # Find moonlight executable
    local moonlight_cmd
    if ! moonlight_cmd="$(command -v moonlight 2>/dev/null)"; then
        log "ERROR" "Moonlight executable not found in PATH"
        return 1
    fi
    
    log "DEBUG" "Using Moonlight: $moonlight_cmd"
    
    # Construct moonlight command with error handling
    local moonlight_args=(
        "stream"
        "-app" "$app"
        "$host"
    )
    
    # Add additional arguments if available
    [[ -n "${MOONLIGHT_EXTRA_ARGS:-}" ]] && read -ra extra_args <<< "$MOONLIGHT_EXTRA_ARGS" && moonlight_args+=("${extra_args[@]}")
    
    log "DEBUG" "Moonlight command: $moonlight_cmd ${moonlight_args[*]}"
    
    # Launch with output redirection and error capture
    local temp_log="$(mktemp)"
    
    # Start moonlight in background with comprehensive logging
    if "$moonlight_cmd" "${moonlight_args[@]}" >"$temp_log" 2>&1 &
    then
        local pid=$!
        echo "$pid" > "$PID_FILE"
        log "INFO" "Moonlight started with PID: $pid"
        log "DEBUG" "PID file created: $PID_FILE"
        
        # Wait a moment to check if process started successfully
        sleep 3
        
        if kill -0 "$pid" 2>/dev/null; then
            log "INFO" "Moonlight process confirmed running"
            
            # Log any initial output
            if [[ -s "$temp_log" ]]; then
                log "DEBUG" "Moonlight initial output: $(head -3 "$temp_log" | tr '\n' ' ')"
            fi
            
            # Append temp log to main log file
            cat "$temp_log" >> "$LOG_FILE" 2>/dev/null || true
            rm -f "$temp_log"
            
            return 0
        else
            log "ERROR" "Moonlight process failed to start or exited immediately"
            
            # Capture error output
            if [[ -s "$temp_log" ]]; then
                log "ERROR" "Moonlight error output:"
                while IFS= read -r line; do
                    log "ERROR" "  $line"
                done < "$temp_log"
            fi
            
            rm -f "$temp_log" "$PID_FILE"
            return 1
        fi
    else
        log "ERROR" "Failed to execute Moonlight command"
        rm -f "$temp_log"
        return 1
    fi
}

# Wait for process to be fully established
wait_for_process_ready() {
    local timeout="${1:-$PROCESS_WAIT_TIMEOUT}"
    
    if [[ ! -f "$PID_FILE" ]]; then
        log "ERROR" "PID file not found after launch"
        return 1
    fi
    
    local pid
    if ! pid="$(cat "$PID_FILE")" || [[ ! "$pid" =~ ^[0-9]+$ ]]; then
        log "ERROR" "Invalid PID in file"
        return 1
    fi
    
    log "DEBUG" "Waiting up to ${timeout}s for process $pid to be ready..."
    
    for ((i=1; i<=timeout; i++)); do
        if kill -0 "$pid" 2>/dev/null; then
            # Process exists, check if it's actually streaming
            sleep 1
            
            # Additional checks could be added here
            # e.g., checking for network connections, GPU usage, etc.
            
            if [[ $i -ge 10 ]]; then  # Process has been running for at least 10 seconds
                log "INFO" "Moonlight process appears to be running successfully"
                return 0
            fi
        else
            log "ERROR" "Process $pid died during startup (after ${i}s)"
            rm -f "$PID_FILE"
            return 1
        fi
    done
    
    log "WARN" "Process startup timeout reached, but process still running"
    return 0
}

# Enhanced stream start sequence with comprehensive error handling
start_stream() {
    local start_time="$(date '+%s')"
    
    log "INFO" "=== Starting Enhanced Launch Sequence v$SCRIPT_VERSION ==="
    
    # Pre-flight checks
    log "DEBUG" "Performing pre-flight checks..."
    check_dependencies
    
    # Cleanup any existing processes
    cleanup_existing_process
    
    # Step 1: Power on TV with CEC
    if ! cec_command "on 0" "Powering on TV via CEC..." "$CEC_TIMEOUT"; then
        log "WARN" "CEC TV power-on failed, continuing anyway..."
    fi
    
    # Brief pause for TV to respond
    sleep 2
    
    # Step 2: Network connectivity test before WoL
    log "DEBUG" "Testing initial network connectivity..."
    if test_network_connectivity "$MOONLIGHT_HOST" 3 1; then
        log "INFO" "PC appears to already be awake and responding"
    else
        log "DEBUG" "PC not responding, will attempt wake-on-LAN"
        
        # Step 3: Send Wake-on-LAN with retries
        if ! send_wake_on_lan "$PC_MAC" "$WOL_RETRIES"; then
            log "ERROR" "Failed to send Wake-on-LAN packets"
            return 1
        fi
        
        # Step 4: Smart wait for PC boot
        if ! wait_for_pc_boot "$BOOT_WAIT_TIME"; then
            log "WARN" "PC boot wait completed with warnings"
        fi
    fi
    
    # Step 5: Final network connectivity verification
    if ! test_network_connectivity "$MOONLIGHT_HOST" "$CONNECTION_TIMEOUT" "$MAX_RETRIES"; then
        log "ERROR" "PC is not responding after boot sequence"
        log "ERROR" "Check PC power state, network connectivity, and Sunshine service"
        return 1
    fi
    
    # Step 6: Launch Moonlight
    if ! launch_moonlight "$MOONLIGHT_APP" "$MOONLIGHT_HOST"; then
        log "ERROR" "Failed to launch Moonlight stream"
        return 1
    fi
    
    # Step 7: Wait for process to be ready
    if ! wait_for_process_ready; then
        log "ERROR" "Moonlight process failed to initialize properly"
        return 1
    fi
    
    local end_time="$(date '+%s')"
    local duration=$((end_time - start_time))
    
    log "INFO" "=== Launch sequence completed successfully in ${duration}s ==="
    return 0
}

# Enhanced stream stop sequence with comprehensive cleanup
stop_stream() {
    local start_time="$(date '+%s')"
    
    log "INFO" "=== Starting Enhanced Stop Sequence v$SCRIPT_VERSION ==="
    
    local success=true
    
    # Step 1: Graceful Moonlight termination
    if [[ -f "$PID_FILE" ]]; then
        local pid
        if pid="$(cat "$PID_FILE" 2>/dev/null)" && [[ "$pid" =~ ^[0-9]+$ ]]; then
            log "INFO" "Terminating Moonlight process (PID: $pid)..."
            
            if kill -0 "$pid" 2>/dev/null; then
                # Send SIGTERM for graceful shutdown
                if kill -TERM "$pid" 2>/dev/null; then
                    log "DEBUG" "SIGTERM sent to process $pid"
                    
                    # Wait for graceful termination
                    local timeout=15
                    for ((i=1; i<=timeout; i++)); do
                        if ! kill -0 "$pid" 2>/dev/null; then
                            log "INFO" "Moonlight terminated gracefully after ${i}s"
                            break
                        fi
                        sleep 1
                    done
                    
                    # Force termination if still running
                    if kill -0 "$pid" 2>/dev/null; then
                        log "WARN" "Forcing termination of Moonlight process..."
                        kill -KILL "$pid" 2>/dev/null || true
                        sleep 2
                        
                        if kill -0 "$pid" 2>/dev/null; then
                            log "ERROR" "Failed to terminate Moonlight process"
                            success=false
                        else
                            log "INFO" "Moonlight process force-terminated"
                        fi
                    fi
                else
                    log "ERROR" "Failed to send termination signal to process $pid"
                    success=false
                fi
            else
                log "DEBUG" "Process $pid no longer exists"
            fi
        else
            log "WARN" "Invalid PID file content"
        fi
        
        # Clean up PID file
        rm -f "$PID_FILE"
        log "DEBUG" "PID file removed"
    else
        log "DEBUG" "No PID file found, no process to terminate"
    fi
    
    # Step 2: Additional cleanup - find any orphaned moonlight processes
    local orphaned_pids
    if orphaned_pids="$(pgrep -f "moonlight.*stream" 2>/dev/null)"; then
        log "WARN" "Found orphaned Moonlight processes: $orphaned_pids"
        echo "$orphaned_pids" | while read -r pid; do
            if [[ -n "$pid" ]]; then
                log "WARN" "Terminating orphaned process: $pid"
                kill -TERM "$pid" 2>/dev/null || kill -KILL "$pid" 2>/dev/null || true
            fi
        done
    fi
    
    # Step 3: Power off TV with CEC
    if ! cec_command "standby 0" "Powering off TV via CEC..." "$CEC_TIMEOUT"; then
        log "WARN" "CEC TV power-off failed"
        success=false
    fi
    
    # Step 4: Cleanup temporary files
    if [[ -n "${XDG_RUNTIME_DIR:-}" ]] && [[ "$XDG_RUNTIME_DIR" == *"tmp"* ]]; then
        log "DEBUG" "Cleaning up XDG runtime directory: $XDG_RUNTIME_DIR"
        rm -rf "$XDG_RUNTIME_DIR" 2>/dev/null || true
    fi
    
    local end_time="$(date '+%s')"
    local duration=$((end_time - start_time))
    
    if $success; then
        log "INFO" "=== Stop sequence completed successfully in ${duration}s ==="
        return 0
    else
        log "WARN" "=== Stop sequence completed with warnings in ${duration}s ==="
        return 1
    fi
}

# Enhanced status check function
status_check() {
    log "INFO" "=== Galaxy Stream Status Check ==="
    
    # Check PID file
    if [[ -f "$PID_FILE" ]]; then
        local pid
        if pid="$(cat "$PID_FILE" 2>/dev/null)" && [[ "$pid" =~ ^[0-9]+$ ]]; then
            if kill -0 "$pid" 2>/dev/null; then
                local cmdline
                if cmdline="$(ps -p "$pid" -o cmd= 2>/dev/null)" && [[ "$cmdline" == *moonlight* ]]; then
                    log "INFO" "Stream is RUNNING (PID: $pid)"
                    log "INFO" "Command: $cmdline"
                    
                    # Additional process info
                    local start_time
                    if start_time="$(ps -p "$pid" -o lstart= 2>/dev/null)"; then
                        log "INFO" "Started: $start_time"
                    fi
                    
                    return 0
                else
                    log "WARN" "PID $pid exists but is not Moonlight process"
                fi
            else
                log "WARN" "PID $pid no longer exists"
            fi
        else
            log "ERROR" "Invalid PID file content"
        fi
        
        # Clean up invalid PID file
        rm -f "$PID_FILE"
        log "DEBUG" "Cleaned up invalid PID file"
    fi
    
    log "INFO" "Stream is NOT RUNNING"
    
    # Check for orphaned processes
    local orphaned_pids
    if orphaned_pids="$(pgrep -f "moonlight.*stream" 2>/dev/null)"; then
        log "WARN" "Found orphaned Moonlight processes: $orphaned_pids"
    fi
    
    # Network connectivity test
    if test_network_connectivity "$MOONLIGHT_HOST" 3 1; then
        log "INFO" "Gaming PC is reachable at $MOONLIGHT_HOST"
    else
        log "WARN" "Gaming PC is not reachable at $MOONLIGHT_HOST"
    fi
    
    return 1
}

# Signal handlers for graceful shutdown
cleanup_on_exit() {
    local exit_code=$?
    log "DEBUG" "Script exiting with code: $exit_code"
    
    # Cleanup temporary files
    [[ -n "${temp_log:-}" ]] && rm -f "$temp_log" 2>/dev/null || true
    
    exit $exit_code
}

# Help function
show_help() {
    cat << EOF
Galaxy Enhanced Launch Script v$SCRIPT_VERSION

USAGE:
    $SCRIPT_NAME {start|stop|status|help} [options]

COMMANDS:
    start     Start the streaming sequence (TV power, WoL, Moonlight)
    stop      Stop the streaming sequence (terminate Moonlight, TV off)
    status    Check current streaming status
    help      Show this help message

OPTIONS:
    --verbose     Enable verbose output
    --debug       Enable debug output
    --dry-run     Show what would be done without executing

ENVIRONMENT VARIABLES:
    All configuration is loaded from .env file in the script directory.
    
    Required: LOG_FILE, PID_FILE, PC_MAC, MOONLIGHT_HOST, MOONLIGHT_APP, TV_CEC_NAME
    Optional: BOOT_WAIT_TIME, CONNECTION_TIMEOUT, MAX_RETRIES, DEBUG, VERBOSE

EXAMPLES:
    $SCRIPT_NAME start --verbose
    $SCRIPT_NAME stop --debug
    $SCRIPT_NAME status

EOF
}

# Parse command line arguments
parse_arguments() {
    while [[ $# -gt 0 ]]; do
        case $1 in
            --verbose)
                VERBOSE=true
                shift
                ;;
            --debug)
                DEBUG=true
                VERBOSE=true
                shift
                ;;
            --dry-run)
                DRY_RUN=true
                shift
                ;;
            --help)
                show_help
                exit 0
                ;;
            -*)
                log "ERROR" "Unknown option: $1"
                show_help
                exit 1
                ;;
            *)
                break
                ;;
        esac
    done
}

# Main execution flow
main() {
    # Set up signal handlers
    trap cleanup_on_exit EXIT
    trap 'log "WARN" "Script interrupted by user"; exit 130' INT TERM
    
    # Parse arguments first
    parse_arguments "$@"
    
    # Load and validate environment
    load_environment
    
    # Log script start
    log "INFO" "Galaxy Launch Script v$SCRIPT_VERSION starting"
    log "DEBUG" "Script directory: $SCRIPT_DIR"
    log "DEBUG" "Process ID: $$"
    [[ "${VERBOSE:-false}" == "true" ]] && log "DEBUG" "Verbose mode enabled"
    [[ "${DEBUG:-false}" == "true" ]] && log "DEBUG" "Debug mode enabled"
    [[ "${DRY_RUN:-false}" == "true" ]] && log "DEBUG" "Dry-run mode enabled"
    
    # Get the command
    local command="${1:-}"
    
    # Execute command
    case "$command" in
        start)
            if [[ "${DRY_RUN:-false}" == "true" ]]; then
                log "INFO" "DRY-RUN: Would start streaming sequence"
                exit 0
            fi
            start_stream
            ;;
        stop)
            if [[ "${DRY_RUN:-false}" == "true" ]]; then
                log "INFO" "DRY-RUN: Would stop streaming sequence"
                exit 0
            fi
            stop_stream
            ;;
        status)
            status_check
            ;;
        help|--help)
            show_help
            exit 0
            ;;
        "")
            log "ERROR" "No command specified"
            show_help
            exit 1
            ;;
        *)
            log "ERROR" "Unknown command: $command"
            show_help
            exit 1
            ;;
    esac
}

# Execute main function with all arguments
main "$@"
