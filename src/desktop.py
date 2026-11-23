"""Connect the prototype-derived interface to the Windows save repair workflow."""

from __future__ import annotations

from base64 import b64encode
from datetime import datetime
import json
import os
from pathlib import Path
from threading import Lock, Thread

import webview

from game_location import SAVE_DIRECTORY, find_game_exe, is_game_exe
from repair import EditorError, QuestStatusError, repair_save
from save_as import DestinationChanged, export_save, plan_destination
from window_frame import WindowFrame


TITLE = '三面混沌任务恢复'


def slot_label(name: str | None) -> str | None:
    if name is None:
        return None
    for prefix, label, offset in (
        ('ManualSave', '手动档', 0), ('AutoSave', '自动档', 1), ('NightmareRun', '六十六天', 0),
    ):
        if name.startswith(prefix) and name[len(prefix):].isdigit():
            return f'{label} {int(name[len(prefix):]) + offset}'
    return name


def slot_details(slot: str, date: datetime) -> dict:
    return {'slot': slot_label(slot), 'time': date.strftime('%Y-%m-%d %H:%M:%S'),
            'timeISO': date.isoformat(timespec='seconds')}


class DesktopApp:
    def __init__(self, resources: Path, output_dir: Path, initial_files=()):
        self._operation = Lock()
        self._out = output_dir
        self._source = None
        self._game_exe = None
        self._result = None
        self._saved = None
        self._destination = None
        self._last_folder = output_dir
        self._maximized = False
        self._initial_files = tuple(initial_files)
        self._frame = None

        ui = resources / 'ui'
        html = (ui / 'index.html').read_text(encoding='utf-8')
        script = (ui / 'app.js').read_text(encoding='utf-8')
        for filename in ('title-heading.png', 'app-icon.png'):
            encoded = b64encode((ui / filename).read_bytes()).decode('ascii')
            html = html.replace(f'"{filename}"', f'"data:image/png;base64,{encoded}"')
        html = html.replace('<script src="app.js"></script>', f'<script>{script}</script>', 1)
        self.window = webview.create_window(TITLE, html=html, width=960, height=870, min_size=(360, 280),
                                            frameless=True, easy_drag=False, background_color='#f5efe8',
                                            text_select=True)
        self.window.expose(self.choose_save, self.locate_game, self.choose_destination, self.approve_overwrite,
                           self.cancel_overwrite, self.open_output, self.open_saved, self.copy_text,
                           self.window_action)
        self.window.events.loaded += self._on_loaded
        self.window.events.maximized += lambda: self._window_state(True)
        self.window.events.restored += lambda: self._window_state(False)
        self.window.events.closing += self._on_closing

    def _emit(self, kind, **data):
        event = json.dumps({'type': kind, **data}, ensure_ascii=True)
        self.window.run_js(f'window.updateRepairUI({event});')

    def _on_loaded(self):
        from System import Action

        def setup_window():
            if self._frame is None:
                self._frame = WindowFrame(self.window.native.Handle.ToInt64())
            surface = self.window.native.browser.webview.CoreWebView2
            surface.WebMessageReceived += self._native_drop

        self.window.native.Invoke(Action(setup_window))
        self._emit('ready')
        files, self._initial_files = self._initial_files, ()
        if files:
            self._accept(files)

    def _native_drop(self, _sender, message):
        if message.WebMessageAsJson != '"FilesDropped"':
            return
        items = message.AdditionalObjects
        # Match the files supplied with this message, including identical basenames.
        files = [str(item.Path) if hasattr(item, 'Path') else None for item in items] if items is not None else [None]
        if files:
            Thread(target=self._accept, args=(files,), daemon=True).start()

    def _window_state(self, maximized):
        self._maximized = maximized
        if self.window.events.loaded.is_set():
            self._emit('window', maximized=maximized)

    def _on_closing(self):
        return not self._operation.locked()

    def window_action(self, action):
        if action == 'minimize':
            self.window.minimize()
        elif action == 'maximize':
            if self._maximized:
                self.window.restore()
            else:
                self.window.maximize()
        elif action == 'close' and not self._operation.locked():
            self.window.destroy()

    def _error(self, title, message, *, detail=None, file=None, locate=False):
        self._emit('error', title=title, message=message, detail=detail, file=file, locate=locate)

    def _accept(self, files):
        if not self._operation.acquire(blocking=False):
            return
        try:
            self._process_files(files)
        finally:
            self._operation.release()

    def _choose(self, kind, directory, file_types=()):
        from System import Action

        selected = []

        def show():
            selected.append(self.window.create_file_dialog(kind, directory=str(directory), file_types=file_types))

        self.window.native.Invoke(Action(show))
        return selected[0]

    def choose_save(self):
        if not self._operation.acquire(blocking=False):
            return
        try:
            if self._source is not None:
                directory = self._source.parent
            else:
                game = find_game_exe()
                directory = game.parents[2] / SAVE_DIRECTORY if game else Path.home()
            files = self._choose(webview.FileDialog.OPEN, directory, ('影之刃零存档 (*.sav)',))
            if files:
                self._process_files(files)
        finally:
            self._operation.release()

    def _process_files(self, files):
        self._destination = self._saved = self._result = None
        if len(files) != 1:
            self._error('请一次拖入一个存档文件。', '请单独拖入 PBZSaveGame.sav，或点击拖放区重新选择。')
            return
        if not files[0]:
            self._error('无法读取拖入的文件路径', '请点击拖放区，从 Windows 文件窗口选择 PBZSaveGame.sav。')
            return
        source = Path(files[0])
        if source.suffix.casefold() != '.sav' or not source.is_file():
            self._error('识别失败', '请重新选择游戏存档目录中的 PBZSaveGame.sav。', file=source.name)
            return
        self._source = source.resolve()
        game_exe = self._game_exe
        if game_exe is None or not is_game_exe(game_exe):
            game_exe = find_game_exe(self._source)
        if game_exe is None:
            self._error('找不到游戏程序', '请选择游戏安装目录中的 platform\\steam\\PBZ.exe。',
                        file=source.name, locate=True)
            return
        self._repair(game_exe)

    def locate_game(self):
        if self._source is None or not self._operation.acquire(blocking=False):
            return
        try:
            paths = self._choose(webview.FileDialog.OPEN, self._source.parent, ('游戏程序 (*.exe)',))
            if not paths:
                return
            path = Path(paths[0])
            if not is_game_exe(path):
                self._error('游戏程序路径不正确', '请选择游戏安装目录中的 platform\\steam\\PBZ.exe。',
                            file=self._source.name, locate=True)
                return
            self._game_exe = path.resolve()
            self._repair(self._game_exe)
        finally:
            self._operation.release()

    def _repair(self, game_exe):
        phase = 'check'
        detail = None
        filename = self._source.name
        self._emit('progress', phase=phase, file=filename, detail=detail)

        def progress(next_phase, slot, date):
            nonlocal phase, detail
            phase, detail = next_phase, slot_details(slot, date)
            self._emit('progress', phase=phase, file=filename, detail=detail)

        try:
            self._result = repair_save(self._source, game_exe, self._out, on_progress=progress)
        except QuestStatusError as error:
            self._error('任务状态不符合修复条件', f'{error}请选择最新槽内任务为「失败」的存档。',
                        file=filename, detail=detail)
            return
        except (EditorError, OSError) as error:
            title, action = {
                'check': ('识别失败', '请检查文件来源，重新选择 PBZSaveGame.sav。'),
                'repair': ('修复失败', '请检查所选存档和游戏版本后重试。'),
                'verify': ('生成文件失败', '请检查程序所在目录的写入权限，或重新选择原存档。'),
            }[phase]
            if phase == 'verify' and isinstance(error, EditorError):
                title, action = '新存档回读校验失败', '请重新拖入原存档重试。'
            self._error(title, f'{error} {action}', file=filename, detail=detail,
                        locate=phase == 'check' and '密钥' in str(error))
            return

        result = self._result
        detail = slot_details(result.slot, result.saved_at)
        detail.update(refunded=result.refunded, path=str(result.path), continueSlot=slot_label(result.continue_slot))
        self._emit('success', detail=detail)

    def choose_destination(self):
        if self._result is None or not self._operation.acquire(blocking=False):
            return
        try:
            self._destination = None
            folders = self._choose(webview.FileDialog.FOLDER, self._last_folder)
            if not folders:
                return
            self._last_folder = Path(folders[0])
            try:
                destination = plan_destination(self._last_folder)
            except (EditorError, OSError) as error:
                self._save_error(error, self._last_folder)
                return
            if destination.stamp is not None and destination.path != self._result.path.resolve():
                self._destination = destination
                self._emit('overwrite', path=str(destination.path), game=destination.game_directory)
            else:
                self._export(destination)
        finally:
            self._operation.release()

    def cancel_overwrite(self):
        if self._operation.acquire(blocking=False):
            try:
                self._destination = None
            finally:
                self._operation.release()

    def approve_overwrite(self):
        if not self._operation.acquire(blocking=False):
            return
        try:
            destination, self._destination = self._destination, None
            if destination is not None and self._result is not None:
                self._export(destination)
        finally:
            self._operation.release()

    def _export(self, destination):
        self._emit('save', status='pending')
        try:
            saved = export_save(self._result, destination)
        except (EditorError, OSError) as error:
            self._save_error(error, destination.path)
        else:
            self._saved = saved
            self._emit('save', status='saved', path=str(saved))

    def _save_error(self, error, target):
        if isinstance(error, DestinationChanged):
            message = str(error)
        elif getattr(error, 'winerror', None) in (32, 33):
            message = '目标存档正在被占用。请退出游戏或关闭占用它的程序后重试。'
        elif isinstance(error, PermissionError):
            message = '当前目录没有写入权限。请选择其他文件夹。'
        elif isinstance(error, FileExistsError):
            message = '目标出现了新的同名文件。请重新选择文件夹并确认。'
        elif isinstance(error, FileNotFoundError):
            message = '生成文件或目标目录已移动。请重新修复存档或选择其他文件夹。'
        else:
            message = f'{error} 请检查目标文件夹后重试。'
        self._emit('save', status='failed', path=str(target), message=message)

    def open_output(self):
        if self._result:
            self._open_folder(self._result.path.parent)

    def open_saved(self):
        if self._saved:
            self._open_folder(self._saved.parent)

    def _open_folder(self, path):
        try:
            os.startfile(path)
        except OSError:
            self._emit('notice', title='无法打开文件夹', message=f'请检查该位置是否仍然存在。{path}')

    def copy_text(self, text):
        from System import Action
        from System.Windows.Forms import Clipboard

        if not isinstance(text, str) or not 0 < len(text) <= 32767:
            return False
        try:
            self.window.native.Invoke(Action(lambda: Clipboard.SetText(text)))
        except Exception:
            return False
        return True
