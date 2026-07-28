from __future__ import annotations

import argparse

from .server import EngineServer


def main() -> None:
    parser = argparse.ArgumentParser(description="Motor local de Transcriptor")
    parser.add_argument("command", choices=["serve"], help="Modo de ejecución")
    args = parser.parse_args()
    if args.command == "serve":
        EngineServer().serve()


if __name__ == "__main__":
    main()
