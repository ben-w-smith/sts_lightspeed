#!/usr/bin/env python3
"""Run sync test - wrapper for CommunicationMod integration.

This is the entry point that CommunicationMod should call.

Usage in CommunicationMod config (STSInstallDir/ModTheSpire.json):
{
    "mods": ["basemod", "stslib", "communicationmod"],
    "steam": true,
    "commands": {
        "default": "python3 /path/to/run_sync_test.py"
    }
}

Or set via environment:
    export COMMUNICATIONMOD_COMMAND="python3 /path/to/run_sync_test.py"
"""
import sys
from pathlib import Path

# Add integration directory to path
script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from spirecomm_sync import main

if __name__ == '__main__':
    main()
