"""@brief Command-line entry point for the application and hardware checks."""

import argparse


def main(argv=None):
    """@brief Load only the dependencies needed by the selected command."""
    parser = argparse.ArgumentParser(prog="python3 -m ai_box", description="泰山派 AI Box：AHT30 + ST7789")
    parser.add_argument(
        "command", nargs="?", default="run",
        choices=("run", "voice", "sensor", "screen", "led"),
        help="run: 菜单；voice: 语音助手；sensor/screen/led: 硬件检查",
    )
    args = parser.parse_args(argv)
    try:
        if args.command in ("sensor", "screen", "led"):
            from . import diagnostics

            getattr(diagnostics, "check_" + args.command)()
        else:
            from .app import main as run

            run(voice_only=args.command == "voice")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
