#!/usr/bin/env python3
"""Bridge Coordinator - Queue manager for multi-project STS bridge access.

A lightweight background service that:
- Manages a persistent request queue
- Runs the next pending request when current completes
- Handles crashes (auto-releases locks, re-runs failed tests)
- Provides status endpoint

Usage:
    # Start the coordinator daemon (foreground)
    python bridge_coordinator.py start

    # Start as background daemon
    python bridge_coordinator.py start --daemon

    # Stop the daemon
    python bridge_coordinator.py stop

    # Check status
    python bridge_coordinator.py status

    # Submit a test request
    python bridge_coordinator.py submit --project ai_factory --command "python run_tests.py --quick"

    # Watch queue (for scripts)
    python bridge_coordinator.py watch --json

    # Cancel a pending request
    python bridge_coordinator.py cancel <request_id>

Queue File Format (/tmp/sts_bridge/.coordinator/queue.json):
    {
      "version": 1,
      "updated_at": "2026-02-21T10:30:00Z",
      "current": {...},      # Currently running request or null
      "pending": [...],      # List of waiting requests
      "completed": [...]     # Recent completed requests (last 10)
    }
"""
import argparse
import json
import os
import signal
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional, List, Dict, Any

# Optional daemon support
try:
    import daemon  # type: ignore
    import daemon.pidfile  # type: ignore
    DAEMON_AVAILABLE = True
except ImportError:
    DAEMON_AVAILABLE = False

from .bridge_lock import (
    bridge_lock,
    get_lock_info,
    release_lock,
    is_locked,
    LOCK_DIR,
    LOCK_FILE
)


# Constants
QUEUE_FILE = LOCK_DIR / "queue.json"
PID_FILE = LOCK_DIR / "coordinator.pid"
LOG_FILE = LOCK_DIR / "coordinator.log"
MAX_COMPLETED = 10  # Keep last N completed requests
POLL_INTERVAL = 1.0  # Seconds between queue checks
REQUEST_TIMEOUT = 3600  # 1 hour default timeout for requests


@dataclass
class Request:
    """A test request in the queue."""
    id: str
    project: str
    command: List[str]
    submitted_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    pid: Optional[int] = None
    exit_code: Optional[int] = None
    status: str = "pending"  # pending, running, completed, failed, cancelled
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Request":
        return cls(**data)

    @classmethod
    def create(cls, project: str, command: List[str]) -> "Request":
        return cls(
            id=f"req-{uuid.uuid4().hex[:8]}",
            project=project,
            command=command,
            submitted_at=datetime.now(timezone.utc).isoformat()
        )


@dataclass
class Queue:
    """The request queue."""
    version: int = 1
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    current: Optional[Dict[str, Any]] = None
    pending: List[Dict[str, Any]] = field(default_factory=list)
    completed: List[Dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": self.version,
            "updated_at": self.updated_at,
            "current": self.current,
            "pending": self.pending,
            "completed": self.completed
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Queue":
        return cls(
            version=data.get("version", 1),
            updated_at=data.get("updated_at", datetime.now(timezone.utc).isoformat()),
            current=data.get("current"),
            pending=data.get("pending", []),
            completed=data.get("completed", [])
        )

    @classmethod
    def load(cls) -> "Queue":
        """Load queue from file, create empty if not exists."""
        if QUEUE_FILE.exists():
            try:
                with open(QUEUE_FILE, 'r') as f:
                    data = json.load(f)
                return cls.from_dict(data)
            except (json.JSONDecodeError, KeyError):
                pass
        return cls()

    def save(self):
        """Save queue to file atomically."""
        self.updated_at = datetime.now(timezone.utc).isoformat()
        LOCK_DIR.mkdir(parents=True, exist_ok=True)

        # Write to temp file then rename for atomicity
        temp_file = QUEUE_FILE.with_suffix('.tmp')
        with open(temp_file, 'w') as f:
            json.dump(self.to_dict(), f, indent=2)
        temp_file.rename(QUEUE_FILE)

    def add_request(self, request: Request) -> int:
        """Add a request to the queue. Returns position in queue."""
        self.pending.append(request.to_dict())
        self.save()
        return len(self.pending)

    def get_next_request(self) -> Optional[Request]:
        """Get the next pending request."""
        if self.pending:
            return Request.from_dict(self.pending[0])
        return None

    def start_request(self, request: Request, pid: int):
        """Mark a request as started."""
        request.status = "running"
        request.started_at = datetime.now(timezone.utc).isoformat()
        request.pid = pid

        # Remove from pending, add to current
        self.pending = [r for r in self.pending if r["id"] != request.id]
        self.current = request.to_dict()
        self.save()

    def complete_request(self, request_id: str, exit_code: int, error: Optional[str] = None):
        """Mark current request as completed."""
        if self.current and self.current["id"] == request_id:
            self.current["completed_at"] = datetime.now(timezone.utc).isoformat()
            self.current["exit_code"] = exit_code
            self.current["status"] = "completed" if exit_code == 0 else "failed"
            self.current["error"] = error

            # Move to completed list
            self.completed.append(self.current)
            # Keep only last N completed
            if len(self.completed) > MAX_COMPLETED:
                self.completed = self.completed[-MAX_COMPLETED:]

            self.current = None
            self.save()

    def cancel_request(self, request_id: str) -> bool:
        """Cancel a pending request. Returns True if found and cancelled."""
        for i, r in enumerate(self.pending):
            if r["id"] == request_id:
                self.pending.pop(i)
                # Add to completed as cancelled
                r["status"] = "cancelled"
                r["completed_at"] = datetime.now(timezone.utc).isoformat()
                self.completed.append(r)
                self.save()
                return True
        return False

    def get_request(self, request_id: str) -> Optional[Request]:
        """Find a request by ID."""
        if self.current and self.current["id"] == request_id:
            return Request.from_dict(self.current)
        for r in self.pending:
            if r["id"] == request_id:
                return Request.from_dict(r)
        for r in self.completed:
            if r["id"] == request_id:
                return Request.from_dict(r)
        return None


class Coordinator:
    """The bridge coordinator daemon."""

    def __init__(self):
        self.running = False
        self.current_process: Optional[subprocess.Popen] = None

    def log(self, message: str):
        """Log a message."""
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        log_line = f"[{timestamp}] {message}"
        print(log_line, flush=True)

        # Also write to log file
        try:
            with open(LOG_FILE, 'a') as f:
                f.write(log_line + "\n")
        except:
            pass

    def start(self):
        """Start the coordinator daemon."""
        self.log("Starting Bridge Coordinator...")

        # Check if already running
        if self._is_running():
            print("Coordinator is already running")
            return False

        self.running = True

        # Set up signal handlers
        signal.signal(signal.SIGTERM, self._handle_signal)
        signal.signal(signal.SIGINT, self._handle_signal)

        # Clean up any stale state
        self._cleanup_stale_state()

        self.log("Coordinator started")
        self.log(f"Queue file: {QUEUE_FILE}")
        self.log(f"Lock file: {LOCK_FILE}")

        try:
            self._run_loop()
        finally:
            self._cleanup()

        return True

    def _is_running(self) -> bool:
        """Check if coordinator is already running."""
        if PID_FILE.exists():
            try:
                with open(PID_FILE, 'r') as f:
                    pid = int(f.read().strip())
                # Check if process exists
                os.kill(pid, 0)
                return True
            except (ValueError, OSError):
                # Stale PID file
                PID_FILE.unlink()
        return False

    def _write_pid(self):
        """Write our PID to the PID file."""
        with open(PID_FILE, 'w') as f:
            f.write(str(os.getpid()))

    def _handle_signal(self, signum, frame):
        """Handle shutdown signals."""
        self.log(f"Received signal {signum}, shutting down...")
        self.running = False

    def _cleanup_stale_state(self):
        """Clean up any stale locks or state."""
        # Check if current request's process is still alive
        queue = Queue.load()
        if queue.current:
            pid = queue.current.get("pid")
            if pid:
                try:
                    os.kill(pid, 0)
                    # Process still alive, leave it alone
                except OSError:
                    # Process is dead, mark as failed
                    self.log(f"Stale process detected (PID {pid}), marking as failed")
                    queue.complete_request(
                        queue.current["id"],
                        exit_code=-1,
                        error="Process died unexpectedly"
                    )

        # Clean up stale locks (handled by bridge_lock, but double-check)
        if LOCK_FILE.exists():
            info = get_lock_info()
            if info is None:
                # Lock was stale and cleaned up
                pass

    def _cleanup(self):
        """Clean up on shutdown."""
        self.log("Cleaning up...")

        # Terminate any running process
        if self.current_process:
            self.log("Terminating current process...")
            self.current_process.terminate()
            try:
                self.current_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.current_process.kill()

        # Remove PID file
        if PID_FILE.exists():
            PID_FILE.unlink()

        # Mark current request as failed if any
        queue = Queue.load()
        if queue.current:
            queue.complete_request(
                queue.current["id"],
                exit_code=-1,
                error="Coordinator shutdown"
            )

        self.log("Cleanup complete")

    def _run_loop(self):
        """Main coordinator loop."""
        self._write_pid()

        while self.running:
            try:
                self._process_queue()
            except Exception as e:
                self.log(f"Error in queue processing: {e}")

            time.sleep(POLL_INTERVAL)

    def _process_queue(self):
        """Process the queue - start next request if idle."""
        queue = Queue.load()

        # Check if we have a current request
        if queue.current:
            request = Request.from_dict(queue.current)

            # Check if process is still running
            if self.current_process:
                poll_result = self.current_process.poll()
                if poll_result is not None:
                    # Process finished
                    exit_code = poll_result
                    self.log(f"Request {request.id} completed with exit code {exit_code}")
                    queue.complete_request(request.id, exit_code)
                    self.current_process = None

                    # Release the bridge lock
                    release_lock()
            elif request.pid:
                # Check if process exists (may have been started before restart)
                try:
                    os.kill(request.pid, 0)
                    # Still running
                except OSError:
                    # Process died
                    self.log(f"Request {request.id} process died (PID {request.pid})")
                    queue.complete_request(request.id, -1, "Process died")
                    release_lock()
        else:
            # No current request, check for pending
            next_request = queue.get_next_request()
            if next_request:
                self._start_request(queue, next_request)

    def _start_request(self, queue: Queue, request: Request):
        """Start executing a request."""
        self.log(f"Starting request {request.id} for project '{request.project}'")
        self.log(f"  Command: {' '.join(request.command)}")

        try:
            # Acquire the bridge lock
            # Note: This may block if another process holds it
            lock_ctx = bridge_lock(request.project, timeout=60.0)
            lock_ctx.__enter__()
            self._lock_ctx = lock_ctx
        except TimeoutError as e:
            self.log(f"Could not acquire lock for request {request.id}: {e}")
            queue.complete_request(request.id, -1, f"Could not acquire bridge lock: {e}")
            return
        except Exception as e:
            self.log(f"Error acquiring lock: {e}")
            queue.complete_request(request.id, -1, str(e))
            return

        try:
            # Start the process
            self.current_process = subprocess.Popen(
                request.command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                start_new_session=True
            )

            # Update queue
            queue.start_request(request, self.current_process.pid)
            self.log(f"  Started as PID {self.current_process.pid}")

        except Exception as e:
            self.log(f"Failed to start request: {e}")
            queue.complete_request(request.id, -1, str(e))
            release_lock()
            self._lock_ctx = None


def cmd_start(args):
    """Start the coordinator."""
    if args.daemon and not DAEMON_AVAILABLE:
        print("Error: --daemon requires python-daemon package")
        print("Install with: pip install python-daemon")
        print("Alternatively, run without --daemon and use & or nohup")
        return 1

    coordinator = Coordinator()

    if args.daemon:
        # Run as background daemon
        context = daemon.DaemonContext(
            pidfile=daemon.pidfile.PIDLockFile(PID_FILE),
            stdout=open(LOG_FILE, 'a'),
            stderr=open(LOG_FILE, 'a')
        )
        with context:
            coordinator.start()
    else:
        # Run in foreground
        coordinator.start()


def cmd_stop(args):
    """Stop the coordinator."""
    if not PID_FILE.exists():
        print("Coordinator is not running")
        return 1

    try:
        with open(PID_FILE, 'r') as f:
            pid = int(f.read().strip())

        print(f"Stopping coordinator (PID {pid})...")
        os.kill(pid, signal.SIGTERM)

        # Wait for it to stop
        for _ in range(10):
            time.sleep(0.5)
            try:
                os.kill(pid, 0)
            except OSError:
                print("Coordinator stopped")
                return 0

        # Force kill if still running
        print("Coordinator did not stop gracefully, forcing...")
        os.kill(pid, signal.SIGKILL)
        return 0

    except (ValueError, OSError) as e:
        print(f"Error stopping coordinator: {e}")
        return 1


def cmd_status(args):
    """Show coordinator and queue status."""
    queue = Queue.load()

    # Check coordinator status
    coordinator_running = False
    if PID_FILE.exists():
        try:
            with open(PID_FILE, 'r') as f:
                pid = int(f.read().strip())
            os.kill(pid, 0)
            coordinator_running = True
        except (ValueError, OSError):
            pass

    # Check bridge lock status
    lock_info = get_lock_info()

    # Build status dict
    status = {
        "coordinator": {
            "running": coordinator_running,
            "pid": None
        },
        "bridge": {
            "locked": lock_info is not None,
            "lock_info": lock_info.to_dict() if lock_info else None
        },
        "queue": {
            "current": queue.current,
            "pending_count": len(queue.pending),
            "pending": queue.pending if args.verbose else [
                {"id": r["id"], "project": r["project"], "submitted_at": r["submitted_at"]}
                for r in queue.pending
            ],
            "completed_count": len(queue.completed)
        }
    }

    if coordinator_running:
        with open(PID_FILE, 'r') as f:
            status["coordinator"]["pid"] = int(f.read().strip())

    if args.json:
        print(json.dumps(status, indent=2))
    else:
        # Human-readable output
        print("=== Bridge Coordinator Status ===")
        print(f"Coordinator: {'running' if coordinator_running else 'stopped'}")
        if coordinator_running:
            print(f"  PID: {status['coordinator']['pid']}")

        print(f"\nBridge: {'locked' if lock_info else 'unlocked'}")
        if lock_info:
            print(f"  Project: {lock_info.project}")
            print(f"  PID: {lock_info.pid}")

        print(f"\nQueue:")
        if queue.current:
            print(f"  Current: {queue.current['id']} ({queue.current['project']})")
            print(f"    Command: {' '.join(queue.current['command'])}")
            print(f"    Status: {queue.current['status']}")
        else:
            print("  Current: idle")

        print(f"  Pending: {len(queue.pending)}")
        for r in queue.pending[:5]:  # Show first 5
            print(f"    - {r['id']} ({r['project']})")
        if len(queue.pending) > 5:
            print(f"    ... and {len(queue.pending) - 5} more")

        print(f"  Completed (recent): {len(queue.completed)}")

    return 0


def cmd_submit(args):
    """Submit a new request to the queue."""
    project = args.project
    command = args.command

    # Validate command
    if not command:
        print("Error: No command specified")
        return 1

    # Create request
    request = Request.create(project, command)

    # Add to queue
    queue = Queue.load()
    position = queue.add_request(request)

    print(f"Request submitted: {request.id}")
    print(f"  Project: {project}")
    print(f"  Command: {' '.join(command)}")
    print(f"  Position in queue: {position}")

    if args.json:
        print(json.dumps({
            "request_id": request.id,
            "position": position,
            "request": request.to_dict()
        }, indent=2))

    # If wait flag, wait for completion
    if args.wait:
        return cmd_wait_wait(request.id, args.timeout)

    return 0


def cmd_cancel(args):
    """Cancel a pending request."""
    queue = Queue.load()
    request_id = args.request_id

    # Check if it's the current request
    if queue.current and queue.current["id"] == request_id:
        print(f"Error: Request {request_id} is currently running. Stop the coordinator to cancel.")
        return 1

    # Try to cancel from pending
    if queue.cancel_request(request_id):
        print(f"Request {request_id} cancelled")
        return 0
    else:
        print(f"Request {request_id} not found in pending queue")
        return 1


def cmd_watch(args):
    """Watch the queue for changes."""
    last_updated = None

    try:
        while True:
            queue = Queue.load()

            if queue.updated_at != last_updated:
                last_updated = queue.updated_at

                if args.json:
                    print(json.dumps(queue.to_dict()))
                else:
                    current_id = queue.current["id"] if queue.current else "idle"
                    print(f"[{datetime.now().strftime('%H:%M:%S')}] "
                          f"Current: {current_id}, Pending: {len(queue.pending)}")

            time.sleep(args.interval)

    except KeyboardInterrupt:
        print("\nStopped watching")
        return 0


def cmd_request_status(args):
    """Get status of a specific request."""
    queue = Queue.load()
    request = queue.get_request(args.request_id)

    if not request:
        print(f"Request {args.request_id} not found")
        return 1

    if args.json:
        print(json.dumps(request.to_dict(), indent=2))
    else:
        print(f"Request: {request.id}")
        print(f"  Project: {request.project}")
        print(f"  Status: {request.status}")
        print(f"  Command: {' '.join(request.command)}")
        print(f"  Submitted: {request.submitted_at}")
        if request.started_at:
            print(f"  Started: {request.started_at}")
        if request.completed_at:
            print(f"  Completed: {request.completed_at}")
        if request.exit_code is not None:
            print(f"  Exit code: {request.exit_code}")
        if request.error:
            print(f"  Error: {request.error}")

        # Position in queue if pending
        for i, r in enumerate(queue.pending):
            if r["id"] == request.id:
                print(f"  Queue position: {i + 1}")
                break

    # Return exit code if completed
    if request.status in ("completed", "failed", "cancelled"):
        return request.exit_code if request.exit_code is not None else 1

    return 0


def cmd_wait(args):
    """Wait for a request to complete."""
    return cmd_wait_wait(args.request_id, args.timeout)


def cmd_wait_wait(request_id: str, timeout: Optional[float]):
    """Wait for a request to complete."""
    queue = Queue.load()
    start_time = time.time()

    while True:
        request = queue.get_request(request_id)

        if not request:
            print(f"Request {request_id} not found")
            return 1

        if request.status in ("completed", "failed", "cancelled"):
            print(f"Request {request_id} {request.status}")
            if request.exit_code is not None:
                return request.exit_code
            return 1

        # Check timeout
        if timeout:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                print(f"Timeout waiting for request {request_id}")
                return 124  # Standard timeout exit code

        # Show status
        if request.status == "running":
            print(f"Request {request_id} is running...")
        else:
            # Find position
            for i, r in enumerate(queue.pending):
                if r["id"] == request_id:
                    print(f"Request {request_id} is pending (position {i + 1})...")
                    break

        time.sleep(2)
        queue = Queue.load()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Bridge Coordinator - Queue manager for multi-project STS bridge access"
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # start
    start_parser = subparsers.add_parser("start", help="Start the coordinator daemon")
    start_parser.add_argument("--daemon", action="store_true",
                              help="Run as background daemon")
    start_parser.set_defaults(func=cmd_start)

    # stop
    stop_parser = subparsers.add_parser("stop", help="Stop the coordinator daemon")
    stop_parser.set_defaults(func=cmd_stop)

    # status
    status_parser = subparsers.add_parser("status", help="Show coordinator and queue status")
    status_parser.add_argument("--json", action="store_true", help="Output as JSON")
    status_parser.add_argument("--verbose", "-v", action="store_true", help="Show more details")
    status_parser.set_defaults(func=cmd_status)

    # submit
    submit_parser = subparsers.add_parser("submit", help="Submit a new request to the queue")
    submit_parser.add_argument("--project", required=True, help="Project name")
    submit_parser.add_argument("--command", nargs="+", required=True, help="Command to execute")
    submit_parser.add_argument("--json", action="store_true", help="Output as JSON")
    submit_parser.add_argument("--wait", action="store_true", help="Wait for completion")
    submit_parser.add_argument("--timeout", type=float, default=None,
                               help="Timeout in seconds (with --wait)")
    submit_parser.set_defaults(func=cmd_submit)

    # cancel
    cancel_parser = subparsers.add_parser("cancel", help="Cancel a pending request")
    cancel_parser.add_argument("request_id", help="Request ID to cancel")
    cancel_parser.set_defaults(func=cmd_cancel)

    # watch
    watch_parser = subparsers.add_parser("watch", help="Watch the queue for changes")
    watch_parser.add_argument("--json", action="store_true", help="Output as JSON")
    watch_parser.add_argument("--interval", type=float, default=1.0,
                              help="Poll interval in seconds")
    watch_parser.set_defaults(func=cmd_watch)

    # status <request_id>
    request_parser = subparsers.add_parser("request", help="Get status of a specific request")
    request_parser.add_argument("request_id", help="Request ID")
    request_parser.add_argument("--json", action="store_true", help="Output as JSON")
    request_parser.set_defaults(func=cmd_request_status)

    # wait
    wait_parser = subparsers.add_parser("wait", help="Wait for a request to complete")
    wait_parser.add_argument("request_id", help="Request ID")
    wait_parser.add_argument("--timeout", type=float, default=None,
                             help="Timeout in seconds")
    wait_parser.set_defaults(func=cmd_wait)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args) if hasattr(args, 'func') else 0


if __name__ == "__main__":
    sys.exit(main())
