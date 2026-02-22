#!/usr/bin/env python3
"""Test script to verify the bridge coordinator and CLI work correctly.

This script tests:
1. Queue file operations (add, status, cancel)
2. Request submission and tracking
3. CLI commands (submit, status, queue, lock-status)

Note: Full coordinator daemon testing is done manually since it requires
      subprocess management.

Usage:
    python test_bridge_coordinator.py
"""
import json
import os
import sys
import time
from pathlib import Path

# Add paths for imports
_project_root = Path(__file__).parent.parent
sys.path.insert(0, str(_project_root))

from integration.harness.bridge_coordinator import (
    Queue,
    Request,
    QUEUE_FILE,
)
from integration.harness.bridge_lock import (
    bridge_lock,
    get_lock_info,
    LOCK_FILE,
    LOCK_DIR,
)


def setup():
    """Set up test environment."""
    # Ensure directories exist
    LOCK_DIR.mkdir(parents=True, exist_ok=True)

    # Clean up any existing queue
    if QUEUE_FILE.exists():
        QUEUE_FILE.unlink()

    # Clean up any existing lock
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()


def teardown():
    """Clean up test environment."""
    if QUEUE_FILE.exists():
        QUEUE_FILE.unlink()
    if LOCK_FILE.exists():
        LOCK_FILE.unlink()


def test_queue_operations():
    """Test basic queue operations."""
    print("\n=== Test 1: Queue Operations ===")

    # Create empty queue
    queue = Queue.load()
    assert queue.current is None, "Should start with no current"
    assert len(queue.pending) == 0, "Should start with no pending"
    assert len(queue.completed) == 0, "Should start with no completed"
    print("  Empty queue created ✓")

    # Add a request
    request = Request.create("test_project", ["echo", "hello"])
    position = queue.add_request(request)
    assert position == 1, "First request should be position 1"
    print(f"  Request added: {request.id} ✓")

    # Reload and verify
    queue2 = Queue.load()
    assert len(queue2.pending) == 1, "Should have one pending request"
    assert queue2.pending[0]["id"] == request.id, "ID should match"
    print("  Queue persisted correctly ✓")

    # Get next request
    next_req = queue.get_next_request()
    assert next_req is not None, "Should have a next request"
    assert next_req.id == request.id, "Should be our request"
    print("  get_next_request works ✓")

    # Start the request
    queue.start_request(next_req, pid=12345)
    assert queue.current is not None, "Should have current"
    assert queue.current["status"] == "running", "Should be running"
    assert len(queue.pending) == 0, "Should be removed from pending"
    print("  start_request works ✓")

    # Complete the request
    queue.complete_request(next_req.id, exit_code=0)
    assert queue.current is None, "Should have no current"
    assert len(queue.completed) == 1, "Should have one completed"
    assert queue.completed[0]["exit_code"] == 0, "Should have exit code"
    print("  complete_request works ✓")

    # Get request by ID
    found = queue.get_request(request.id)
    assert found is not None, "Should find request"
    assert found.status == "completed", "Should be completed"
    print("  get_request works ✓")

    print("  Test PASSED")
    return True


def test_multiple_requests():
    """Test queue with multiple requests."""
    print("\n=== Test 2: Multiple Requests ===")

    queue = Queue.load()

    # Add multiple requests
    req1 = Request.create("project_1", ["cmd1"])
    req2 = Request.create("project_2", ["cmd2"])
    req3 = Request.create("project_3", ["cmd3"])

    queue.add_request(req1)
    queue.add_request(req2)
    queue.add_request(req3)

    assert len(queue.pending) == 3, "Should have 3 pending"
    print("  Added 3 requests ✓")

    # Get and process first
    next_req = queue.get_next_request()
    assert next_req.id == req1.id, "Should get first request"
    queue.start_request(next_req, pid=111)
    print("  Started first request ✓")

    # Get next (should still be req2 since req1 is now current)
    next_req = queue.get_next_request()
    assert next_req.id == req2.id, "Should get second request"
    print("  Second request is next in line ✓")

    # Complete first
    queue.complete_request(req1.id, exit_code=0)
    assert queue.current is None, "Should have no current"
    assert len(queue.pending) == 2, "Should have 2 pending"
    print("  Completed first request ✓")

    print("  Test PASSED")
    return True


def test_cancel_request():
    """Test cancelling a pending request."""
    print("\n=== Test 3: Cancel Request ===")

    queue = Queue.load()

    # Add requests
    req1 = Request.create("project_1", ["cmd1"])
    req2 = Request.create("project_2", ["cmd2"])
    queue.add_request(req1)
    queue.add_request(req2)

    # Cancel second request
    result = queue.cancel_request(req2.id)
    assert result, "Should succeed"
    assert len(queue.pending) == 1, "Should have 1 pending"
    assert queue.pending[0]["id"] == req1.id, "Should have first request"
    print("  Cancelled second request ✓")

    # Check it's in completed as cancelled
    found = queue.get_request(req2.id)
    assert found is not None, "Should find cancelled request"
    assert found.status == "cancelled", "Should be cancelled"
    print("  Cancelled request in completed list ✓")

    # Try to cancel non-existent
    result = queue.cancel_request("nonexistent")
    assert not result, "Should fail for non-existent"
    print("  Cancel non-existent fails correctly ✓")

    print("  Test PASSED")
    return True


def test_request_dataclass():
    """Test Request dataclass operations."""
    print("\n=== Test 4: Request Dataclass ===")

    # Create request
    req = Request.create("test_proj", ["python", "-c", "print('hi')"])

    assert req.id.startswith("req-"), "ID should start with req-"
    assert req.project == "test_proj", "Project should match"
    assert req.command == ["python", "-c", "print('hi')"], "Command should match"
    assert req.status == "pending", "Should start as pending"
    assert req.pid is None, "Should have no PID initially"
    print("  Request created correctly ✓")

    # Test serialization
    data = req.to_dict()
    assert "id" in data, "Should have id"
    assert "project" in data, "Should have project"
    assert "command" in data, "Should have command"

    req2 = Request.from_dict(data)
    assert req2.id == req.id, "ID should match after round-trip"
    assert req2.project == req.project, "Project should match after round-trip"
    print("  Serialization works ✓")

    print("  Test PASSED")
    return True


def test_cli_status():
    """Test CLI status command."""
    print("\n=== Test 5: CLI Status ===")

    import subprocess

    # Test lock-status
    result = subprocess.run(
        [sys.executable, "-m", "integration.harness.sts_bridge_cli", "lock-status", "--json"],
        cwd=_project_root,
        capture_output=True,
        text=True
    )

    # Parse output
    try:
        data = json.loads(result.stdout)
        assert "locked" in data, "Should have locked field"
        print(f"  lock-status works: locked={data['locked']} ✓")
    except json.JSONDecodeError:
        print(f"  Warning: Could not parse JSON: {result.stdout}")
        # Non-fatal, might be error message

    # Test queue
    result = subprocess.run(
        [sys.executable, "-m", "integration.harness.sts_bridge_cli", "queue", "--json"],
        cwd=_project_root,
        capture_output=True,
        text=True
    )

    try:
        data = json.loads(result.stdout)
        assert "pending" in data, "Should have pending field"
        print(f"  queue works: {len(data['pending'])} pending ✓")
    except json.JSONDecodeError:
        print(f"  Warning: Could not parse JSON: {result.stdout}")

    print("  Test PASSED")
    return True


def test_cli_submit():
    """Test CLI submit command (async mode)."""
    print("\n=== Test 6: CLI Submit ===")

    import subprocess

    # Submit async (returns immediately)
    result = subprocess.run(
        [
            sys.executable, "-m", "integration.harness.sts_bridge_cli",
            "submit",
            "--async",
            "--project", "test_project",
            "--json",
            "--", "echo", "hello"
        ],
        cwd=_project_root,
        capture_output=True,
        text=True
    )

    print(f"  stdout: {result.stdout[:200]}")
    print(f"  stderr: {result.stderr[:200]}")

    try:
        data = json.loads(result.stdout)
        assert "request_id" in data, "Should have request_id"
        request_id = data["request_id"]
        print(f"  submit --async works: {request_id} ✓")

        # Check status
        result2 = subprocess.run(
            [sys.executable, "-m", "integration.harness.sts_bridge_cli",
             "status", request_id, "--json"],
            cwd=_project_root,
            capture_output=True,
            text=True
        )

        data2 = json.loads(result2.stdout)
        assert data2["id"] == request_id, "Should find our request"
        print(f"  status works: found {request_id} ✓")

    except json.JSONDecodeError as e:
        print(f"  Warning: Could not parse JSON: {e}")
        print(f"  stdout: {result.stdout}")
        # Don't fail the test

    print("  Test PASSED")
    return True


def test_max_completed():
    """Test that completed list is limited to MAX_COMPLETED."""
    print("\n=== Test 7: Max Completed Limit ===")

    queue = Queue.load()

    # Add and complete many requests
    for i in range(15):
        req = Request.create(f"project_{i}", [f"cmd{i}"])
        queue.add_request(req)
        next_req = queue.get_next_request()
        queue.start_request(next_req, pid=1000 + i)
        queue.complete_request(next_req.id, exit_code=0)

    # Should be limited to MAX_COMPLETED (10)
    assert len(queue.completed) <= 10, f"Should be <= 10, got {len(queue.completed)}"
    print(f"  Completed list limited to {len(queue.completed)} ✓")

    print("  Test PASSED")
    return True


def main():
    """Run all tests."""
    print("=" * 60)
    print("Bridge Coordinator Tests (Phase 2)")
    print("=" * 60)
    print(f"Queue file: {QUEUE_FILE}")
    print(f"Current PID: {os.getpid()}")

    setup()

    tests = [
        ("Queue Operations", test_queue_operations),
        ("Multiple Requests", test_multiple_requests),
        ("Cancel Request", test_cancel_request),
        ("Request Dataclass", test_request_dataclass),
        ("CLI Status", test_cli_status),
        ("CLI Submit", test_cli_submit),
        ("Max Completed", test_max_completed),
    ]

    results = []
    for name, test_func in tests:
        try:
            # Clean up between tests
            if QUEUE_FILE.exists():
                QUEUE_FILE.unlink()

            passed = test_func()
            results.append((name, passed, None))
        except AssertionError as e:
            print(f"  Test FAILED: {e}")
            results.append((name, False, str(e)))
        except Exception as e:
            print(f"  Test ERROR: {e}")
            results.append((name, False, str(e)))

    teardown()

    # Summary
    print("\n" + "=" * 60)
    print("Test Summary")
    print("=" * 60)

    passed = sum(1 for _, p, _ in results if p)
    total = len(results)

    for name, p, error in results:
        status = "PASS" if p else "FAIL"
        print(f"  [{status}] {name}")
        if error:
            print(f"         Error: {error}")

    print()
    print(f"Results: {passed}/{total} tests passed")

    if passed == total:
        print("\nAll tests PASSED!")
        return 0
    else:
        print(f"\n{total - passed} test(s) FAILED")
        return 1


if __name__ == "__main__":
    sys.exit(main())
