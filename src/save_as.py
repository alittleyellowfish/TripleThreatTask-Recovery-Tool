"""Export a verified repair without leaving a partially written destination."""

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
from stat import S_ISREG
from tempfile import NamedTemporaryFile

from repair import EditorError, RepairResult


SAVE_NAME = 'PBZSaveGame.sav'


class DestinationChanged(EditorError):
    pass


def file_stamp(path: Path):
    try:
        state = path.lstat()
    except FileNotFoundError:
        return None
    if not S_ISREG(state.st_mode):
        raise EditorError('同名目标不是普通文件。请选择其他文件夹。')
    return state.st_dev, state.st_ino, state.st_size, state.st_mtime_ns, state.st_ctime_ns


@dataclass(frozen=True)
class SaveDestination:
    path: Path
    stamp: tuple[int, ...] | None

    @property
    def game_directory(self):
        parts = tuple(part.casefold() for part in self.path.parent.parts)
        return parts[-5:-1] == ('projectpbz', 'saved', 'savegames', 'steam')


def plan_destination(folder: Path) -> SaveDestination:
    target = folder.resolve(strict=True) / SAVE_NAME
    return SaveDestination(target, file_stamp(target))


def export_save(result: RepairResult, destination: SaveDestination) -> Path:
    target = destination.path
    raw = result.path.read_bytes()
    if sha256(raw).hexdigest() != result.output_sha256:
        raise EditorError('生成的存档已发生变化。请重新拖入原存档修复。')
    if target == result.path.resolve():
        return target

    temporary = None
    try:
        with NamedTemporaryFile(dir=target.parent, prefix='.pbz-', suffix='.tmp', delete=False) as stream:
            temporary = Path(stream.name)
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        if sha256(temporary.read_bytes()).hexdigest() != result.output_sha256:
            raise EditorError('另存文件的回读校验失败。请选择其他文件夹重试。')
        if file_stamp(target) != destination.stamp:
            raise DestinationChanged('目标文件在另存过程中发生变化。请重新选择文件夹并确认。')
        if destination.stamp is None:
            # Windows rename fails when another process has already created the destination.
            temporary.rename(target)
        else:
            temporary.replace(target)
        return target
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
