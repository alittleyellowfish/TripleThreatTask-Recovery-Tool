"""Locate a local Phantom Blade Zero Steam installation."""

import os
from pathlib import Path
import re


GAME_EXE = Path('platform/steam/PBZ.exe')
SAVE_DIRECTORY = Path('ProjectPBZ/Saved/SaveGames/Steam')
_LIBRARY_PATH = re.compile(r'^\s*"path"[ \t]+"((?:\\.|[^"\\])*)"', re.MULTILINE | re.IGNORECASE)


def is_game_exe(path: Path) -> bool:
    return tuple(part.casefold() for part in path.parts[-3:]) == ('platform', 'steam', 'pbz.exe') and path.is_file()


def _steam_libraries():
    roots = []
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r'Software\Valve\Steam') as key:
            install, _ = winreg.QueryValueEx(key, 'SteamPath')
            if isinstance(install, str) and install:
                roots.append(Path(install))
    except (ImportError, OSError):
        pass

    program_files = os.environ.get('ProgramFiles(x86)') or os.environ.get('ProgramFiles')
    if program_files:
        roots.append(Path(program_files) / 'Steam')

    for install in dict.fromkeys(roots):
        yield install
        try:
            libraries = (install / 'steamapps/libraryfolders.vdf').read_text(encoding='utf-8-sig')
        except (OSError, UnicodeError):
            continue
        for path in _LIBRARY_PATH.findall(libraries):
            yield Path(re.sub(r'\\(["\\])', r'\1', path))


def find_game_exe(save_path: Path | None = None) -> Path | None:
    if save_path is not None:
        for folder in save_path.resolve().parents:
            candidate = folder / GAME_EXE
            if candidate.is_file():
                return candidate

    for library in _steam_libraries():
        candidate = library / 'steamapps/common/PBZ' / GAME_EXE
        if candidate.is_file():
            return candidate
    return None
