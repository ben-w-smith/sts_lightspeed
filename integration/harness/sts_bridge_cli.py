#!/usr/bin/env python3
"""STS Bridge CLI - Command-line interface for bridge coordination.

A convenient wrapper for agents to submit and manage test requests
across multiple STS projects.

Usage:
    # Submit and wait for completion
    sts-bridge submit --project ai_factory -- python run_tests.py --quick

    # Submit and return immediately (get request ID)
    sts-bridge submit --async --project ai_factory -- python run_tests.py --quick

    # Check request status
    sts-bridge status req-abc123

    # Wait for request to complete
    sts-bridge wait req-abc123 --timeout 3600

    # Check bridge lock status
    sts-bridge lock-status

    # View queue
    sts-bridge queue

Installation:
    # Add to PATH (from sts_lightspeed root)
    ln -s $(pwd)/integration/harness/sts_bridge_cli.py /usr/local/bin/sts-bridge

    # Or run directly
    python integration/harness/sts_bridge_cli.py ...
"""
import argparse
import json
import os
import sys
import time
from pathlib import Path

# Add paths for imports
_project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(_project_root))

from integration.harness.bridge_coordinator import (
    Queue,
    Request,
    QUEUE_FILE,
    cmd_submit as coord_submit,
    cmd_request_status,
    cmd_wait,
)
from integration.harness.bridge_lock import (
    get_lock_info,
    is_locked,
    wait_for_lock,
    LOCK_FILE,
)


def cmd_submit_cli(args):
    """Submit a test request."""
    # Parse command after --
    if not args.command:
        print("Error: No command specified. Use -- <command>")
        return 1

    # Create request
    project = args.project or os.environ.get("STS_PROJECT", "unknown")
    request = Request.create(project, args.command)

    # Add to queue
    queue = Queue.load()
    position = queue.add_request(request)

    if args.async_submit:
        # Return immediately with request ID
        result = {
            "request_id": request.id,
            "position": position,
            "status": "pending"
        }
        if args.json:
            print(json.dumps(result))
        else:
            print(f"Submitted: {request.id}")
            print(f"Position: {position}")
            if position > 1:
                print(f"ETA: approximately {position * 15} minutes (estimated)")
        return 0
    else:
        # Wait for completion
        if args.json:
            print(json.dumps({
                "request_id": request.id,
                "position": position,
                "status": "waiting"
            }))

        return wait_for_request(request.id, args.timeout)


def wait_for_request(request_id: str, timeout: Optional[float] = None) -> int:
    """Wait for a request to complete."""
    queue = Queue.load()
    start_time = time.time()

    while True:
        request = queue.get_request(request_id)

        if not request:
            print(f"Error: Request {request_id} not found")
            return 1

        if request.status == "completed":
            print(f"Request {request_id} completed successfully")
            return request.exit_code or 0

        if request.status == "failed":
            print(f"Request {request_id} failed (exit code: {request.exit_code})")
            if request.error:
                print(f"Error: {request.error}")
            return request.exit_code or 1

        if request.status == "cancelled":
            print(f"Request {request_id} was cancelled")
            return 1

        # Check timeout
        if timeout:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                print(f"Timeout: Request {request_id} did not complete within {timeout}s")
                return 124

        # Show progress
        if request.status == "running":
            print(f"Running...", end="\r")
        else:
            # Find position
            for i, r in enumerate(queue.pending):
                if r["id"] == request_id:
                    print(f"Waiting (position {i + 1})...", end="\r")
                    break

        time.sleep(2)
        queue = Queue.load()


def cmd_lock_status(args):
    """Show bridge lock status."""
    info = get_lock_info()

    if args.json:
        result = {
            "locked": info is not None,
            "lock_info": info.to_dict() if info else None,
            "lock_file": str(LOCK_FILE)
        }
        print(json.dumps(result, indent=2))
    else:
        if info:
            print(f"Bridge is LOCKED")
            print(f"  Project: {info.project}")
            print(f"  PID: {info.pid}")
            if info.acquired_at:
                elapsed = time.time() - info.acquired_at
                print(f"  Held for: {elapsed:.0f} seconds")
            print(f"  Lock file: {LOCK_FILE}")
            print()
            print("To release:")
            print(f"  kill {info.pid}  # or wait for process to finish")
            print(f"  rm {LOCK_FILE}  # force release (if process crashed)")
        else:
            print("Bridge is UNLOCKED")
            print(f"  Lock file: {LOCK_FILE}")

    return 0 if info is None else 1


def cmd_queue(args):
    """Show the request queue."""
    queue = Queue.load()

    if args.json:
        print(json.dumps(queue.to_dict(), indent=2))
        return 0

    print("=== STS Bridge Queue ===")
    print()

    # Current
    if queue.current:
        r = queue.current
        print("Current (running):")
        print(f"  ID: {r['id']}")
        print(f"  Project: {r['project']}")
        print(f"  Command: {' '.join(r['command'])}")
        print(f"  Started: {r.get('started_at', 'unknown')}")
        print()
    else:
        print("Current: (idle)")
        print()

    # Pending
    print(f"Pending ({len(queue.pending)}):")
    if queue.pending:
        for i, r in enumerate(queue.pending):
            print(f"  {i+1}. {r['id']} ({r['project']})")
            if args.verbose:
                print(f"     Command: {' '.join(r['command'])}")
                print(f"     Submitted: {r['submitted_at']}")
    else:
        print("  (empty)")
    print()

    # Recent completed
    print(f"Recent completed ({len(queue.completed)}):")
    if queue.completed:
        for r in queue.completed[-5:]:  # Show last 5
            status = "✓" if r.get('exit_code') == 0 else "✗"
            print(f"  {status} {r['id']} ({r['project']}) - {r['status']}")
    else:
        print("  (none)")

    return 0


def cmd_wait_unlock(args):
    """Wait for bridge to become unlocked."""
    print(f"Waiting for bridge to unlock (timeout: {args.timeout or 'infinite'}s)...")

    if wait_for_lock(timeout=args.timeout):
        print("Bridge is now unlocked")
        return 0
    else:
        print("Timeout waiting for bridge to unlock")
        return 1


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="STS Bridge CLI - Manage bridge coordination and test requests",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Submit and wait for completion
  sts-bridge submit --project ai_factory -- python run_tests.py --quick

  # Submit and return immediately
  sts-bridge submit --async --project intelligence -- python integration/run_tests.py

  # Check status of a request
  sts-bridge status req-abc123

  # Wait for request to complete
  sts-bridge wait req-abc123 --timeout 3600

  # Check if bridge is locked
  sts-bridge lock-status

  # View the queue
  sts-bridge queue
"""
    )
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # submit
    submit_parser = subparsers.add_parser(
        "submit",
        help="Submit a test request",
        description="Submit a test request to the queue"
    )
    submit_parser.add_argument(
        "--project", "-p",
        help="Project name (default: $STS_PROJECT or 'unknown')"
    )
    submit_parser.add_argument(
        "--async", "-a",
        dest="async_submit",
        action="store_true",
        help="Return immediately with request ID (don't wait)"
    )
    submit_parser.add_argument(
        "--timeout", "-t",
        type=float,
        default=3600,
        help="Timeout in seconds when waiting (default: 3600)"
    )
    submit_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON"
    )
    submit_parser.add_argument(
        "command",
        nargs="*",
        help="Command to execute (after --)"
    )
    submit_parser.set_defaults(func=cmd_submit_cli)

    # status
    status_parser = subparsers.add_parser(
        "status",
        help="Get status of a request",
        description="Get the status of a specific request"
    )
    status_parser.add_argument("request_id", help="Request ID")
    status_parser.add_argument("--json", action="store_true", help="Output as JSON")
    status_parser.set_defaults(func=cmd_request_status)

    # wait
    wait_parser = subparsers.add_parser(
        "wait",
        help="Wait for a request to complete",
        description="Wait for a request to complete"
    )
    wait_parser.add_argument("request_id", help="Request ID")
    wait_parser.add_argument("--timeout", "-t", type=float, default=None,
                             help="Timeout in seconds")
    wait_parser.set_defaults(func=cmd_wait)

    # lock-status
    lock_parser = subparsers.add_parser(
        "lock-status",
        help="Show bridge lock status",
        description="Show whether the bridge is locked and by whom"
    )
    lock_parser.add_argument("--json", action="store_true", help="Output as JSON")
    lock_parser.set_defaults(func=cmd_lock_status)

    # queue
    queue_parser = subparsers.add_parser(
        "queue",
        help="Show the request queue",
        description="Show all pending, running, and recent completed requests"
    )
    queue_parser.add_argument("--json", action="store_true", help="Output as JSON")
    queue_parser.add_argument("--verbose", "-v", action="store_true", help="Show more details")
    queue_parser.set_defaults(func=cmd_queue)

    # wait-unlock
    wait_unlock_parser = subparsers.add_parser(
        "wait-unlock",
        help="Wait for bridge to unlock",
        description="Wait until the bridge becomes unlocked"
    )
    wait_unlock_parser.add_argument("--timeout", "-t", type=float, default=None,
                                    help="Timeout in seconds")
    wait_unlock_parser.set_defaults(func=cmd_wait_unlock)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return 1

    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
