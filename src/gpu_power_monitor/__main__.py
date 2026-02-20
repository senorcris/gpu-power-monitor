"""CLI entry point for gpu-power-monitor."""

import argparse
import json
import logging
import sys


def main():
    parser = argparse.ArgumentParser(
        prog="gpu-power-monitor",
        description="Monitor ASUS ROG RTX 5090 Astral LC 12V-2x6 connector power via IT8915FN",
    )

    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("-d", "--daemon", action="store_true",
                      help="Run as monitoring daemon (foreground)")
    mode.add_argument("-t", "--tui", action="store_true",
                      help="Launch TUI dashboard (default)")
    mode.add_argument("--probe", action="store_true",
                      help="Scan I2C buses and dump IT8915FN register data")
    mode.add_argument("--once", action="store_true",
                      help="Single snapshot as JSON to stdout")

    parser.add_argument("--bus", type=int, default=None,
                        help="Override I2C bus number")
    parser.add_argument("--address", type=lambda x: int(x, 0), default=None,
                        help="Override I2C address (e.g. 0x2B)")
    parser.add_argument("--register", type=lambda x: int(x, 0), default=None,
                        help="Override I2C register (e.g. 0x80)")
    parser.add_argument("-v", "--verbose", action="store_true",
                        help="Enable debug logging")

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.probe:
        from .i2c import probe_buses
        results = probe_buses()
        if not results:
            print("No NVIDIA I2C buses found.")
            sys.exit(1)
        for r in results:
            print(f"\nBus {r['bus']}: {r['name']}")
            print(f"  Address: 0x{r['address']:02X}")
            if r.get("error"):
                print(f"  Error: {r['error']}")
            elif r["found"]:
                print(f"  Raw data: {r['data']}")
                if r["pins"]:
                    for p in r["pins"]:
                        print(f"  {p['label']}: {p['voltage']:.3f}V  {p['current']:.3f}A")
            else:
                print("  No response at this address")

    elif args.once:
        from .daemon import run_once
        output = run_once(bus=args.bus, address=args.address, register=args.register)
        sys.stdout.write(output)

    elif args.daemon:
        from .daemon import run_daemon
        run_daemon(bus=args.bus, address=args.address, register=args.register)

    else:
        # Default: TUI mode
        from .tui.app import run_tui
        run_tui(bus=args.bus, address=args.address, register=args.register)


if __name__ == "__main__":
    main()
