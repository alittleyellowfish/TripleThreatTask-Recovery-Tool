"""Windows application and command-line entry point."""

import argparse
from pathlib import Path
import sys

from game_location import find_game_exe
from repair import EditorError, repair_save


RESOURCE_DIR = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
APP_DIR = Path(sys.executable if getattr(sys, 'frozen', False) else __file__).resolve().parent


def cli_repair(args):
    parser = argparse.ArgumentParser(description='三面混沌任务恢复')
    parser.add_argument('--repair', required=True, type=Path, metavar='SAVE')
    parser.add_argument('--game-exe', type=Path)
    parser.add_argument('--output-dir', type=Path, default=APP_DIR)
    params = parser.parse_args(args)
    try:
        game = params.game_exe or find_game_exe(params.repair)
        if game is None:
            raise EditorError('找不到游戏程序，请通过 --game-exe 指定。')
        result = repair_save(params.repair, game, params.output_dir)
    except (EditorError, OSError) as error:
        if sys.stderr:
            print(error, file=sys.stderr)
        return 1
    if sys.stdout:
        print(f'{result.slot} | 返还容器 {int(result.refunded)} | {result.path}')
    return 0


def main():
    args = sys.argv[1:]
    if args and args[0] == '--repair':
        return cli_repair(args)

    import webview
    from desktop import DesktopApp

    app = DesktopApp(RESOURCE_DIR, APP_DIR, args)
    webview.start(gui='edgechromium', private_mode=True, icon=str(RESOURCE_DIR / 'ui' / 'app-icon.ico'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
