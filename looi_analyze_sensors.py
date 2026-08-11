import argparse
import csv
import json
import statistics
from collections import Counter
from pathlib import Path
from typing import Any

from looi_control_lab import decode_fed9, compact_decode


def int8(value: int) -> int:
    return value - 256 if value >= 128 else value


def latest_run(root: Path) -> Path:
    runs = [path for path in root.iterdir() if path.is_dir() and not path.name.startswith("._")]
    if not runs:
        raise SystemExit(f"No log runs found in {root}")
    return max(runs, key=lambda path: path.stat().st_mtime)


def load_events(run_dir: Path) -> list[dict[str, Any]]:
    events_path = run_dir / "events.jsonl"
    if not events_path.exists():
        raise SystemExit(f"Missing events.jsonl in {run_dir}")
    return [json.loads(line) for line in events_path.read_text().splitlines() if line.strip()]


def event_label(event: dict[str, Any]) -> str:
    if event.get("kind") == "notify" and event.get("char") == "FED9":
        raw = bytes.fromhex(event["hex"])
        decoded = decode_fed9(raw)
        return f"FED9 {event['hex']} | {compact_decode(decoded)}"
    if event.get("kind") == "notify":
        return f"{event.get('char')} {event.get('hex')}"
    if event.get("kind") == "battery":
        status = event.get("status_guess")
        power = "usb" if status == 1 else "battery" if status == 0 else "?"
        return f"FED8 {event.get('hex')} pct={event.get('percent_guess')} status={status}({power})"
    return f"{event.get('kind')} {event}"


def fed9_numeric_sample(event: dict[str, Any], start_time: float, step_id: str, run_dir: Path) -> dict[str, Any] | None:
    if event.get("kind") != "notify" or event.get("char") != "FED9":
        return None
    raw = bytes.fromhex(event["hex"])
    if len(raw) < 3 or raw[0] not in {0x02, 0x0E}:
        return None
    return {
        "run": str(run_dir),
        "step": step_id,
        "t": event.get("t"),
        "t_rel": event.get("t", 0) - start_time,
        "type": f"{raw[0]:02x}",
        "raw": event["hex"],
        "axis_a_i8": int8(raw[1]),
        "axis_b_i8": int8(raw[2]),
        "value_i16_le": int.from_bytes(raw[1:3], "little", signed=True),
        "value_i16_be": int.from_bytes(raw[1:3], "big", signed=True),
        "b1": raw[1],
        "b2": raw[2],
    }


def print_numeric_stats(samples: list[dict[str, Any]]) -> None:
    for packet_type in ["02", "0e"]:
        typed = [sample for sample in samples if sample["type"] == packet_type]
        if not typed:
            continue
        le_values = [sample["value_i16_le"] for sample in typed]
        be_values = [sample["value_i16_be"] for sample in typed]
        first = typed[0]
        last = typed[-1]
        axis_text = ""
        if packet_type == "02":
            axis_a = [sample["axis_a_i8"] for sample in typed]
            axis_b = [sample["axis_b_i8"] for sample in typed]
            axis_text = (
                f"a_i8(min/med/max)={min(axis_a)}/{statistics.median(axis_a)}/{max(axis_a)} "
                f"b_i8(min/med/max)={min(axis_b)}/{statistics.median(axis_b)}/{max(axis_b)} "
            )
        print(
            f"  FED9 {packet_type} numeric: "
            f"n={len(typed)} "
            f"{axis_text}"
            f"le(min/med/max)={min(le_values)}/{statistics.median(le_values)}/{max(le_values)} "
            f"be(min/med/max)={min(be_values)}/{statistics.median(be_values)}/{max(be_values)} "
            f"delta_le={last['value_i16_le'] - first['value_i16_le']} "
            f"first={first['raw']} last={last['raw']}"
        )


def summarize_window(
    events: list[dict[str, Any]],
    start: dict[str, Any],
    end: dict[str, Any],
    prefix: str,
    run_dir: Path,
) -> list[dict[str, Any]]:
    start_time = start["t"]
    end_time = end["t"]
    step_id = start["key"].removeprefix(prefix + ":start:")
    window = [
        event
        for event in events
        if start_time <= event.get("t", 0) <= end_time
        and (
            event.get("kind") == "battery"
            or (event.get("kind") == "notify" and event.get("char") in {"FED5", "FED9"})
        )
    ]
    numeric_samples = [
        sample
        for event in window
        if (sample := fed9_numeric_sample(event, start_time, step_id, run_dir)) is not None
    ]

    print(f"\n{step_id}  duration={end_time - start_time:.2f}s")
    print(f"  note: {start.get('note', '')}")
    if not window:
        print("  no BLE events in this window")
        return numeric_samples

    fed9_counter = Counter(event["hex"] for event in window if event.get("char") == "FED9")
    battery_counter = Counter(event["hex"] for event in window if event.get("kind") == "battery")
    fed5_counter = Counter(event["hex"] for event in window if event.get("char") == "FED5")

    if fed9_counter:
        print("  FED9 unique:")
        for hex_value, count in fed9_counter.most_common(20):
            decoded = decode_fed9(bytes.fromhex(hex_value))
            print(f"    {hex_value:<12} x{count:<3} {compact_decode(decoded)}")
        print_numeric_stats(numeric_samples)
    if fed5_counter:
        print("  FED5 unique:")
        for hex_value, count in fed5_counter.most_common():
            print(f"    {hex_value:<12} x{count}")
    if battery_counter:
        print("  FED8 unique:")
        for hex_value, count in battery_counter.most_common():
            status = bytes.fromhex(hex_value)[1] if len(bytes.fromhex(hex_value)) > 1 else None
            power = "usb" if status == 1 else "battery" if status == 0 else "?"
            print(f"    {hex_value:<12} x{count:<3} {power}")
    return numeric_samples


def analyze_run(run_dir: Path) -> list[dict[str, Any]]:
    all_numeric_samples: list[dict[str, Any]] = []
    events = load_events(run_dir)
    print(f"Run: {run_dir}")

    prefixes = ["sensor", "physics", "passive", "fed9motion", "fed9angle"]
    starts = [
        event
        for event in events
        if event.get("kind") == "key"
        and any(event.get("key", "").startswith(f"{prefix}:start:") for prefix in prefixes)
    ]
    if not starts:
        raise SystemExit(
            "No sensor/physics/passive/fed9motion/fed9angle start markers found. "
            "Run looi_control_lab.py --sensor-test, --physics-test, --passive-test, "
            "--fed9-motion-test, or --fed9-angle-test first."
        )

    for start in starts:
        prefix = next(prefix for prefix in prefixes if start["key"].startswith(f"{prefix}:start:"))
        step_id = start["key"].removeprefix(f"{prefix}:start:")
        end = next(
            (
                event
                for event in events
                if event.get("kind") == "key"
                and event.get("key") == f"{prefix}:end:{step_id}"
                and event["t"] >= start["t"]
            ),
            None,
        )
        if end is None:
            print(f"\n{step_id}: missing {prefix}:end marker")
            continue
        all_numeric_samples.extend(summarize_window(events, start, end, prefix, run_dir))
    return all_numeric_samples


def write_csv(path: Path, samples: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = [
        "run",
        "step",
        "t",
        "t_rel",
        "type",
        "raw",
        "axis_a_i8",
        "axis_b_i8",
        "value_i16_le",
        "value_i16_be",
        "b1",
        "b2",
    ]
    with path.open("w", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(samples)
    print(f"\nCSV written: {path}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Summarize LOOI sensor/physics/FED9-motion test logs.")
    parser.add_argument("run_dirs", nargs="*", help="Log run directories. Defaults to latest looi_control_logs run.")
    parser.add_argument("--root", default="looi_control_logs", help="Logs root for latest run lookup.")
    parser.add_argument("--csv", dest="csv_path", help="Write FED9 02/0e numeric samples to CSV.")
    args = parser.parse_args()

    run_dirs = [Path(path) for path in args.run_dirs] if args.run_dirs else [latest_run(Path(args.root))]
    all_samples: list[dict[str, Any]] = []
    for index, run_dir in enumerate(run_dirs):
        if index:
            print("\n" + "=" * 80)
        all_samples.extend(analyze_run(run_dir))
    if args.csv_path:
        write_csv(Path(args.csv_path), all_samples)


if __name__ == "__main__":
    main()
