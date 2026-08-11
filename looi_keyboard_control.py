#!/usr/bin/env python3
"""Dedicated keyboard controller for the LOOI robot base.

The BLE implementation and logging live in ``looi_control_lab.py`` so the
manual controller and guided experiments use exactly the same protocol code.
"""

import argparse
import asyncio
import sys

from looi_control_lab import main


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Control a LOOI robot base from the keyboard with BLE logging."
    )
    parser.add_argument(
        "--address",
        help="BLE address/UUID. If omitted, scan for a device whose name contains LOOI.",
    )
    parser.add_argument(
        "--log-dir",
        default="looi_control_logs",
        help="Directory where a timestamped run log is created.",
    )
    parser.add_argument(
        "--quiet-ble",
        action="store_true",
        help="Keep raw BLE traffic in log files without printing it to the terminal.",
    )
    parser.add_argument(
        "--battery-interval",
        type=float,
        default=None,
        help="FED8 battery polling interval in seconds. Default: 4.0.",
    )
    args = parser.parse_args()

    for test_mode in (
        "dock_test",
        "sensor_test",
        "physics_test",
        "passive_test",
        "fed9_motion_test",
        "fed9_angle_test",
    ):
        setattr(args, test_mode, False)
    return args


if __name__ == "__main__":
    try:
        asyncio.run(main(parse_args()))
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        sys.exit(1)
