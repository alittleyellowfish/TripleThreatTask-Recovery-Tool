"""PBZSContainer and LosslessJSON adapted from MIT-licensed PBZ-Editor.
See native/PBZ-Editor-LICENSE.txt.
"""
from __future__ import annotations

import json
import os
import struct
import zlib
from typing import Any

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

class EditorError(ValueError):
    """The input save remains untouched."""

MAX_SLOT_BYTES = 64 * 1024 * 1024
MAX_FILE_BYTES = 256 * 1024 * 1024

def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(",", ":"))
class PBZSContainer:
    """Strict parser for the observed version 3, sealed-directory container."""
    def __init__(self, key: bytes, codec: OodleCodec | None = None, allow_unknown_version=False):
        if len(key) != 32:
            raise EditorError("存档密钥长度错误。")
        self.key, self.codec = key, codec
        self.allow_unknown_version = allow_unknown_version

    def unseal(self, block: bytes) -> bytes:
        if len(block) < 36 or block[:8] != b"PBZS\x01\x01\x00\x00":
            raise EditorError("存档加密块头无效。")
        try:
            return AESGCM(self.key).decrypt(block[8:20], block[36:] + block[20:36], None)
        except Exception as exc:
            raise EditorError("存档完整性校验失败：文件损坏、版本不匹配或密钥不正确。") from exc

    def seal(self, clear: bytes) -> bytes:
        nonce = os.urandom(12)
        result = AESGCM(self.key).encrypt(nonce, clear, None)
        return b"PBZS\x01\x01\x00\x00" + nonce + result[-16:] + result[:-16]

    def _decompress(self, data: bytes, algorithm: int, size: int) -> bytes:
        if algorithm == 0:
            raw = data
        elif algorithm == 1:
            try:
                dec = zlib.decompressobj()
                raw = dec.decompress(data, size + 1)
                if len(raw) > size or dec.unconsumed_tail or not dec.eof or dec.unused_data:
                    raise ValueError("zlib length/stream boundary mismatch")
            except zlib.error as exc:
                raise EditorError("zlib 解压失败。") from exc
        elif algorithm == 2:
            if self.codec is None:
                raise EditorError("此存档需要 Oodle 解码库。")
            raw = self.codec.decompress(data, size)
        else:
            raise EditorError(f"未知压缩算法：{algorithm}。")
        if len(raw) != size:
            raise EditorError("存档槽的实际大小与目录不符。")
        return raw

    def decode(self, data: bytes) -> list[dict]:
        if not 12 <= len(data) <= MAX_FILE_BYTES or data[:4] != b"PBZS":
            raise EditorError("这不是支持的 PBZS 存档文件。")
        version, flags, count, directory_size = struct.unpack_from("<BBHI", data, 4)
        if (version != 3 and not self.allow_unknown_version) or flags != 1 or not 1 <= count <= 4096:
            raise EditorError("暂不支持此 PBZS 容器版本或标志。")
        if not 36 <= directory_size <= len(data) - 12:
            raise EditorError("存档目录长度无效。")
        directory = self.unseal(data[12:12 + directory_size])
        if directory[:12] != data[:12]:
            raise EditorError("存档头副本校验失败。")
        cursor, end, names, entries = 12, 0, set(), []
        for _ in range(count):
            if cursor + 2 > len(directory):
                raise EditorError("存档目录截断。")
            name_size = struct.unpack_from("<H", directory, cursor)[0]
            cursor += 2
            if not 1 <= name_size <= 4096 or cursor + name_size + 14 > len(directory):
                raise EditorError("存档槽名或目录边界无效。")
            try:
                name = directory[cursor:cursor + name_size].decode("utf8")
            except UnicodeDecodeError as exc:
                raise EditorError("存档槽名编码无效。") from exc
            cursor += name_size
            algorithm, flag, size, offset, block_size = struct.unpack_from("<BBIII", directory, cursor)
            cursor += 14
            if name in names or algorithm not in (0, 1, 2) or flag != 1:
                raise EditorError("重复存档槽或不支持的压缩/加密标志。")
            if size > MAX_SLOT_BYTES or offset != end or block_size < 36 or 12 + directory_size + offset + block_size > len(data):
                raise EditorError("存档槽范围或解压大小无效。")
            block = data[12 + directory_size + offset:12 + directory_size + offset + block_size]
            raw = self._decompress(self.unseal(block), algorithm, size)
            try:
                value = json.loads(raw)
            except (ValueError, UnicodeDecodeError) as exc:
                raise EditorError(f"存档槽 {name} 中的 JSON 无效。") from exc
            if not isinstance(value, dict):
                raise EditorError("存档槽必须包含 JSON 对象。")
            names.add(name)
            entries.append({"name": name, "algorithm": algorithm, "flag": flag, "raw": raw, "json": value, "block": block})
            end = offset + block_size
        if cursor != len(directory) or 12 + directory_size + end != len(data):
            raise EditorError("存档目录或数据存在未使用的尾部字节。")
        return entries

    def encode(self, entries: list[dict], replacements: dict[str, bytes], compression: str = "preserve") -> bytes:
        if compression not in ("preserve", "zlib", "none"):
            raise EditorError("未知压缩选项。")
        if set(replacements) - {e["name"] for e in entries}:
            raise EditorError("修改包含不存在的存档槽。")
        rows, chunks, offset = [], [], 0
        for entry in entries:
            name = entry["name"].encode("utf8")
            algorithm, raw, block = entry["algorithm"], entry["raw"], entry["block"]
            if entry["name"] in replacements:
                raw = replacements[entry["name"]]
                if len(raw) > MAX_SLOT_BYTES:
                    raise EditorError("修改后的存档槽过大。")
                json.loads(raw)
                if compression == "zlib":
                    algorithm = 1
                elif compression == "none":
                    algorithm = 0
                if algorithm == 0:
                    compressed = raw
                elif algorithm == 1:
                    compressed = zlib.compress(raw)
                else:
                    if self.codec is None:
                        raise EditorError("重新压缩需要 Oodle 库。")
                    compressed = self.codec.compress(raw)
                block = self.seal(compressed)
            rows.append(struct.pack("<H", len(name)) + name + struct.pack("<BBIII", algorithm, 1, len(raw), offset, len(block)))
            chunks.append(block)
            offset += len(block)
        directory_size = 12 + sum(map(len, rows)) + 36
        header = b"PBZS" + struct.pack("<BBHI", 3, 1, len(entries), directory_size)
        result = header + self.seal(header + b"".join(rows)) + b"".join(chunks)
        if len(result) > MAX_FILE_BYTES:
            raise EditorError("修改后的存档过大。")
        return result


class _Node:
    def __init__(self, start: int, end: int, value: Any, children=None):
        self.start, self.end, self.value, self.children = start, end, value, children


class LosslessJSON:
    """Patch selected JSON members while keeping every unrelated literal intact."""
    def __init__(self, raw: bytes):
        self.text = raw.decode("utf8")
        self.decoder = json.JSONDecoder()
        self._parse()

    def _space(self, i):
        while i < len(self.text) and self.text[i] in " \r\n\t":
            i += 1
        return i

    def _value(self, i):
        i = self._space(i)
        start = i
        if self.text[i] == "{":
            i += 1
            children, value = {}, {}
            i = self._space(i)
            while self.text[i] != "}":
                key_start = i
                key, i = self.decoder.raw_decode(self.text, i)
                if not isinstance(key, str) or key in children:
                    raise EditorError("JSON 含重复或无效对象键。")
                i = self._space(i)
                if self.text[i] != ":":
                    raise EditorError("JSON 对象缺少冒号。")
                child, i = self._value(i + 1)
                children[key] = (key_start, child)
                value[key] = child.value
                i = self._space(i)
                if self.text[i] == "}":
                    break
                if self.text[i] != ",":
                    raise EditorError("JSON 对象分隔符无效。")
                i = self._space(i + 1)
            return _Node(start, i + 1, value, children), i + 1
        if self.text[i] == "[":
            children, value = [], []
            i = self._space(i + 1)
            while self.text[i] != "]":
                child, i = self._value(i)
                children.append(child)
                value.append(child.value)
                i = self._space(i)
                if self.text[i] == "]":
                    break
                if self.text[i] != ",":
                    raise EditorError("JSON 数组分隔符无效。")
                i = self._space(i + 1)
            return _Node(start, i + 1, value, children), i + 1
        value, end = self.decoder.raw_decode(self.text, i)
        return _Node(start, end, value), end

    def _parse(self):
        try:
            self.root, end = self._value(0)
            if self._space(end) != len(self.text):
                raise EditorError("JSON 末尾包含额外数据。")
        except (IndexError, json.JSONDecodeError) as exc:
            raise EditorError("存档 JSON 结构无效。") from exc

    @property
    def value(self):
        return self.root.value

    def node(self, path):
        node = self.root
        for key in path:
            if isinstance(node.children, dict):
                node = node.children[key][1]
            else:
                node = node.children[key]
        return node

    def _patch(self, start, end, text):
        self.text = self.text[:start] + text + self.text[end:]
        self._parse()

    def set(self, path, value):
        parent = self.node(path[:-1])
        key = path[-1]
        if isinstance(parent.children, dict) and key not in parent.children:
            prefix = "," if parent.children else ""
            self._patch(parent.end - 1, parent.end - 1, prefix + _json(key) + ":" + _json(value))
        else:
            target = self.node(path)
            if target.value != value:
                self._patch(target.start, target.end, _json(value))

    def set_raw(self, path, raw_text):
        """Set a subtree using valid JSON text without normalizing its literals."""
        json.loads(raw_text)
        parent = self.node(path[:-1])
        key = path[-1]
        if isinstance(parent.children, dict) and key not in parent.children:
            prefix = "," if parent.children else ""
            self._patch(parent.end - 1, parent.end - 1, prefix + _json(key) + ":" + raw_text)
        else:
            target = self.node(path)
            if self.text[target.start:target.end] != raw_text:
                self._patch(target.start, target.end, raw_text)

    def remove(self, path):
        parent = self.node(path[:-1])
        key = path[-1]
        if not isinstance(parent.children, dict) or key not in parent.children:
            return
        keys = list(parent.children)
        index = keys.index(key)
        key_start, target = parent.children[key]
        if index + 1 < len(keys):
            end = parent.children[keys[index + 1]][0]
            start = key_start
        elif index:
            previous = parent.children[keys[index - 1]][1]
            start, end = previous.end, target.end
        else:
            start, end = key_start, target.end
        self._patch(start, end, "")

    def bytes(self):
        return self.text.encode("utf8")



