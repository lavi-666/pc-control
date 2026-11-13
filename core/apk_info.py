"""
PC Control — сведения о PC_Control.apk для обновления приложения из его настроек (GET /api/apk/info).

Источник истины — сам APK: версия читается из двоичного AndroidManifest.xml внутри архива
(небольшой разборщик формата AXML), а не из исходников android_app/ — в релизной установке их нет.
Результат кэшируется по времени изменения и размеру файла (sha256 считается один раз на сборку).
"""

from __future__ import annotations

import hashlib
import struct
import threading
import time
import zipfile
from pathlib import Path

# Идентификаторы атрибутов android:versionCode / android:versionName (android.R.attr)
_ATTR_VERSION_CODE = 0x0101021B
_ATTR_VERSION_NAME = 0x0101021C

_CHUNK_STRING_POOL = 0x0001
_CHUNK_XML = 0x0003
_CHUNK_RESOURCE_MAP = 0x0180
_CHUNK_START_ELEMENT = 0x0102

_TYPE_STRING = 0x03
_TYPE_INT_DEC = 0x10
_TYPE_INT_HEX = 0x11

_cache_lock = threading.Lock()
_cache: dict = {}


def _read_strings(buf: bytes, off: int) -> list:
    """Пул строк AXML (UTF-8 или UTF-16)."""
    _t, hsize, _size, count, _styles, flags, strings_start, _ = struct.unpack_from("<HHIIIIII", buf, off)
    utf8 = bool(flags & 0x100)
    offsets = struct.unpack_from("<%dI" % count, buf, off + hsize) if count else ()
    base = off + strings_start
    out = []
    for so in offsets:
        p = base + so
        if utf8:
            # длина в символах UTF-16, затем длина в байтах UTF-8 (каждая — 1 или 2 байта)
            n = buf[p]
            p += 2 if n & 0x80 else 1
            n = buf[p]
            if n & 0x80:
                n = ((n & 0x7F) << 8) | buf[p + 1]
                p += 2
            else:
                p += 1
            out.append(buf[p:p + n].decode("utf-8", errors="replace"))
        else:
            n = struct.unpack_from("<H", buf, p)[0]
            p += 2
            if n & 0x8000:
                n = ((n & 0x7FFF) << 16) | struct.unpack_from("<H", buf, p)[0]
                p += 2
            out.append(buf[p:p + n * 2].decode("utf-16-le", errors="replace"))
    return out


def parse_axml_manifest(buf: bytes) -> dict:
    """Возвращает {"package", "version_code", "version_name"} из двоичного AndroidManifest.xml.
    Бросает ValueError, если это не AXML или в нём нет элемента <manifest>."""
    if len(buf) < 8 or struct.unpack_from("<H", buf, 0)[0] != _CHUNK_XML:
        raise ValueError("not a binary AndroidManifest.xml")
    strings: list = []
    res_ids: tuple = ()
    off = struct.unpack_from("<H", buf, 2)[0]
    end = min(len(buf), struct.unpack_from("<I", buf, 4)[0] or len(buf))
    while off + 8 <= end:
        ctype, hsize, csize = struct.unpack_from("<HHI", buf, off)
        if csize < 8:
            break
        if ctype == _CHUNK_STRING_POOL:
            strings = _read_strings(buf, off)
        elif ctype == _CHUNK_RESOURCE_MAP:
            res_ids = struct.unpack_from("<%dI" % ((csize - hsize) // 4), buf, off + hsize)
        elif ctype == _CHUNK_START_ELEMENT:
            ext = off + hsize
            _ns, name_idx, attr_start, attr_size, attr_count = struct.unpack_from("<IIHHH", buf, ext)
            if 0 <= name_idx < len(strings) and strings[name_idx] == "manifest":
                info = {"package": "", "version_code": 0, "version_name": ""}
                for i in range(attr_count):
                    a = ext + attr_start + i * attr_size
                    _ans, aname, raw, _vsize, _r0, dtype, data = struct.unpack_from("<IIIHBBI", buf, a)
                    rid = res_ids[aname] if aname < len(res_ids) else 0
                    nm = strings[aname] if aname < len(strings) else ""
                    sval = strings[raw] if raw != 0xFFFFFFFF and raw < len(strings) else (
                        strings[data] if dtype == _TYPE_STRING and data < len(strings) else "")
                    if rid == _ATTR_VERSION_CODE or nm == "versionCode":
                        if dtype in (_TYPE_INT_DEC, _TYPE_INT_HEX):
                            info["version_code"] = int(data)
                        elif sval.strip().isdigit():
                            info["version_code"] = int(sval.strip())
                    elif rid == _ATTR_VERSION_NAME or nm == "versionName":
                        info["version_name"] = sval if sval else (str(data) if dtype == _TYPE_INT_DEC else "")
                    elif nm == "package":
                        info["package"] = sval
                return info
        off += csize
    raise ValueError("<manifest> element not found")


def read_apk_manifest(apk_path: Path) -> dict:
    with zipfile.ZipFile(apk_path) as z:
        return parse_axml_manifest(z.read("AndroidManifest.xml"))


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def get_apk_info(apk_path: Path) -> dict:
    """Сведения для GET /api/apk/info. Повторные запросы не перечитывают файл, пока он не изменится."""
    apk_path = Path(apk_path)
    try:
        st = apk_path.stat()
    except OSError:
        return {"available": False, "version_code": 0, "version_name": "", "size": 0, "sha256": "", "built_at": ""}
    key = (str(apk_path), st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get("info")
        if hit and hit[0] == key:
            return dict(hit[1])
    info = {"available": False, "version_code": 0, "version_name": "", "size": int(st.st_size),
            "sha256": "", "built_at": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(st.st_mtime)),
            "built_at_ts": int(st.st_mtime)}
    try:
        man = read_apk_manifest(apk_path)
        info.update({"version_code": int(man["version_code"]), "version_name": man["version_name"],
                     "package": man["package"], "sha256": _sha256(apk_path)})
        info["available"] = info["version_code"] > 0
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, struct.error, IndexError) as e:
        info["error"] = type(e).__name__
    with _cache_lock:
        _cache["info"] = (key, dict(info))
    return info
