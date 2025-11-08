#!/usr/bin/env bash
# run_wayfarer.sh
# Starts houston (npm), starts wayfarer inside .wayfarer_venv with a config
# Waits for a user command to start pathfinder/main.py (runs mission) and exits when it completes.

set -u

# Resolve base dir (repo root assumed one level up from this script when stored in scripts/)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_DIR="$SCRIPT_DIR/.."
BASE_DIR="$(cd "$BASE_DIR" && pwd)"

LOG_DIR="$BASE_DIR/.logs"
mkdir -p "$LOG_DIR"

HOUSTON_DIR="$BASE_DIR/wayfarer/houston"
PATHFINDER_DIR="$BASE_DIR/wayfarer/pathfinder"
VENV="$BASE_DIR/.wayfarer_venv"
DEFAULT_CONFIG="$BASE_DIR/examples/config.min.yaml"
WAYFARER_CONFIG="${1:-$DEFAULT_CONFIG}"

HOUSTON_PID=""
WAYFARER_PID=""

# cleanup function: stop background processes
cleanup() {
  echo "Cleaning up..."
  if [ -n "$HOUSTON_PID" ] && kill -0 "$HOUSTON_PID" 2>/dev/null; then
    echo "Stopping houston (pid $HOUSTON_PID)"
    kill "$HOUSTON_PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$HOUSTON_PID" 2>/dev/null; then
      kill -9 "$HOUSTON_PID" 2>/dev/null || true
    fi
    pkill "node"
    echo "Pkill node because nothing else can kill it for now, to be fixed"
  fi

  if [ -n "$WAYFARER_PID" ] && kill -0 "$WAYFARER_PID" 2>/dev/null; then
    echo "Stopping wayfarer (pid $WAYFARER_PID)"
    kill "$WAYFARER_PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$WAYFARER_PID" 2>/dev/null; then
      kill -9 "$WAYFARER_PID" 2>/dev/null || true
    fi
    # If a child process of the backgrounded shell survived, try to kill by name as a last resort
    pkill -f "wayfarer" 2>/dev/null || true
  fi

  echo "Done. Logs are in $LOG_DIR"
}

trap 'cleanup; exit' INT TERM EXIT

# Start houston (npm start)
start_houston() {
  if [ -d "$HOUSTON_DIR" ]; then
    echo "Starting Houston (npm start) in $HOUSTON_DIR"
    pushd "$HOUSTON_DIR" >/dev/null || return
    # run npm in background and capture pid
    npm install
    npm run build
    npm start > "$LOG_DIR/houston.log" 2>&1 &
    HOUSTON_PID=$!
    popd >/dev/null || return
    echo "Houston started (pid $HOUSTON_PID). Logs: $LOG_DIR/houston.log"
  else
    echo "Houston directory not found: $HOUSTON_DIR" >&2
  fi
}

# Start wayfarer using virtualenv
start_wayfarer() {
  if [ -f "$VENV/bin/activate" ]; then
    echo "Starting wayfarer inside venv $VENV with config $WAYFARER_CONFIG"
    # use exec to replace the shell so $! refers to the actual wayfarer process
    bash -lc "source \"$VENV/bin/activate\" && exec wayfarer -c \"$WAYFARER_CONFIG\"" > "$LOG_DIR/wayfarer.log" 2>&1 &
    WAYFARER_PID=$!
    echo "Wayfarer started (pid $WAYFARER_PID). Logs: $LOG_DIR/wayfarer.log"
  else
    echo "Virtualenv not found at $VENV. Trying to run system 'wayfarer' if available."
    # Use exec in subshell to ensure PID maps to the actual process
    bash -lc "exec wayfarer -c \"$WAYFARER_CONFIG\"" > "$LOG_DIR/wayfarer.log" 2>&1 &
    WAYFARER_PID=$!
    echo "Wayfarer started (pid $WAYFARER_PID). Logs: $LOG_DIR/wayfarer.log"
  fi
}

# Show status of background processes
show_status() {
  echo "-- Status --"
  if [ -n "$HOUSTON_PID" ] && kill -0 "$HOUSTON_PID" 2>/dev/null; then
    echo "Houston: running (pid $HOUSTON_PID)"
  else
    echo "Houston: not running"
  fi
  if [ -n "$WAYFARER_PID" ] && kill -0 "$WAYFARER_PID" 2>/dev/null; then
    echo "Wayfarer: running (pid $WAYFARER_PID)"
  else
    echo "Wayfarer: not running"
  fi
  echo "Logs: $LOG_DIR"
}

# Print last N lines of logs
show_logs() {
  N=${1:-200}
  echo "--- houston.log (last $N lines) ---"
  [ -f "$LOG_DIR/houston.log" ] && tail -n "$N" "$LOG_DIR/houston.log" || echo "(no houston.log yet)"
  echo "--- wayfarer.log (last $N lines) ---"
  [ -f "$LOG_DIR/wayfarer.log" ] && tail -n "$N" "$LOG_DIR/wayfarer.log" || echo "(no wayfarer.log yet)"
}

# Start the mission (pathfinder/main.py) in foreground and wait for it to finish.
start_mission() {
  PF="$PATHFINDER_DIR/main.py"
  if [ ! -f "$PF" ]; then
    echo "pathfinder/main.py not found at $PF" >&2
    return 1
  fi

  echo "Starting pathfinder mission (this will run in foreground). Logs (mission) appended to $LOG_DIR/mission.log"
  if [ -f "$VENV/bin/activate" ]; then
    bash -lc "source \"$VENV/bin/activate\" && python3 \"$PF\"" 2>&1 | tee -a "$LOG_DIR/mission.log"
    RC=${PIPESTATUS[0]:-0}
  else
    python3 "$PF" 2>&1 | tee -a "$LOG_DIR/mission.log"
    RC=${PIPESTATUS[0]:-0}
  fi

  echo "Mission process finished with exit code $RC"
  return $RC
}

# Main run
echo "==== run_wayfarer.sh ===="
echo "Repository base dir: $BASE_DIR"
echo "Wayfarer config: $WAYFARER_CONFIG"
start_houston
echo "wait for houston startup"
sleep 1
start_wayfarer

echo
echo "Background services started. Use the interactive prompt to control the mission."

# Interactive loop
while true; do
  echo
  echo "Commands: status | logs [N] | start | stop | quit"
  read -r -p "> " CMD ARGS
  case "$CMD" in
    status)
      show_status
      ;;
    logs)
      show_logs "$ARGS"
      ;;
    start)
      echo "Starting mission now..."
      # Run mission; when mission finishes, stop background services and exit
      if start_mission; then
        echo "Mission completed successfully. Exiting and cleaning up."
      else
        echo "Mission exited with non-zero code. Cleaning up and exiting."
      fi
      ;;
    stop)
      echo "Stopping background services and exiting."
      exit 0
      ;;
    quit)
      echo "Quit requested. Stopping everything and exiting."
      exit 0
      ;;
    *)
      echo "Unknown command: $CMD"
      ;;
  esac
done
