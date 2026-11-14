"""! @brief Command-line entry point for the application and hardware checks."""

import argparse


def main(argv=None):
    """! @brief Load only the dependencies needed by the selected command.
    @param argv Command-line arguments; None uses the process arguments.
    """
    parser = argparse.ArgumentParser(prog="python3 -m ai_box", description="泰山派 AI Box：语音助手与显示屏")
    parser.add_argument(
        "command", nargs="?", default="run",
        choices=("run", "mipi", "voice"),
        help="run/mipi: 触摸菜单；voice: 语音助手",
    )
    args = parser.parse_args(argv)
    try:
        from .mipi import main as run_mipi

        run_mipi(voice_only=args.command == "voice")
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
