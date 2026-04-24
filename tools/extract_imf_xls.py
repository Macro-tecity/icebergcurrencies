import json
import math
import re
import struct
from pathlib import Path


FREESECT = 0xFFFFFFFF
ENDOFCHAIN = 0xFFFFFFFE
FATSECT = 0xFFFFFFFD
DIFSECT = 0xFFFFFFFC


def _u16(data, off):
    return struct.unpack_from("<H", data, off)[0]


def _u32(data, off):
    return struct.unpack_from("<I", data, off)[0]


def _i32(data, off):
    return struct.unpack_from("<i", data, off)[0]


def _f64(data, off):
    return struct.unpack_from("<d", data, off)[0]


def _decode_utf16_name(raw):
    text = raw.decode("utf-16le", errors="ignore")
    return text.split("\x00", 1)[0]


class CompoundFile:
    def __init__(self, path):
        self.path = Path(path)
        self.data = self.path.read_bytes()
        if self.data[:8] != b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1":
            raise ValueError(f"{path} is not an OLE compound file")
        self.sector_size = 1 << _u16(self.data, 30)
        self.mini_sector_size = 1 << _u16(self.data, 32)
        self.first_dir_sector = _u32(self.data, 48)
        self.mini_stream_cutoff = _u32(self.data, 56)
        self.first_mini_fat_sector = _u32(self.data, 60)
        self.num_mini_fat_sectors = _u32(self.data, 64)
        self.first_difat_sector = _u32(self.data, 68)
        self.num_difat_sectors = _u32(self.data, 72)
        self.fat = self._load_fat()
        self.entries = self._load_directory()
        self.root = self.entries[0]
        self.mini_fat = self._load_mini_fat()
        self.mini_stream = self._read_fat_stream(self.root["start"], self.root["size"])

    def _sector_offset(self, sid):
        return 512 + sid * self.sector_size

    def _read_sector(self, sid):
        off = self._sector_offset(sid)
        return self.data[off : off + self.sector_size]

    def _load_fat(self):
        difat = [_u32(self.data, 76 + i * 4) for i in range(109)]
        sid = self.first_difat_sector
        for _ in range(self.num_difat_sectors):
            if sid in (FREESECT, ENDOFCHAIN):
                break
            sec = self._read_sector(sid)
            count = self.sector_size // 4 - 1
            difat.extend(_u32(sec, i * 4) for i in range(count))
            sid = _u32(sec, count * 4)
        fat = []
        for fat_sid in difat:
            if fat_sid in (FREESECT, ENDOFCHAIN, FATSECT, DIFSECT):
                continue
            sec = self._read_sector(fat_sid)
            fat.extend(_u32(sec, i) for i in range(0, self.sector_size, 4))
        return fat

    def _read_fat_stream(self, start, size=None):
        out = bytearray()
        sid = start
        seen = set()
        while sid not in (FREESECT, ENDOFCHAIN) and sid not in seen:
            seen.add(sid)
            out.extend(self._read_sector(sid))
            sid = self.fat[sid]
        return bytes(out[:size] if size is not None else out)

    def _load_directory(self):
        raw = self._read_fat_stream(self.first_dir_sector)
        entries = []
        for off in range(0, len(raw), 128):
            item = raw[off : off + 128]
            if len(item) < 128:
                continue
            name_len = _u16(item, 64)
            name = _decode_utf16_name(item[: max(0, name_len - 2)]) if name_len else ""
            obj_type = item[66]
            if obj_type == 0:
                continue
            size = _u32(item, 120)
            entries.append({"name": name, "type": obj_type, "start": _u32(item, 116), "size": size})
        return entries

    def _load_mini_fat(self):
        if self.first_mini_fat_sector in (FREESECT, ENDOFCHAIN):
            return []
        raw = self._read_fat_stream(self.first_mini_fat_sector, self.num_mini_fat_sectors * self.sector_size)
        return [_u32(raw, i) for i in range(0, len(raw), 4)]

    def _read_mini_stream(self, start, size):
        out = bytearray()
        sid = start
        seen = set()
        while sid not in (FREESECT, ENDOFCHAIN) and sid not in seen:
            seen.add(sid)
            off = sid * self.mini_sector_size
            out.extend(self.mini_stream[off : off + self.mini_sector_size])
            sid = self.mini_fat[sid]
        return bytes(out[:size])

    def open_stream(self, names):
        wanted = {n.lower() for n in names}
        for entry in self.entries:
            if entry["name"].lower() in wanted:
                if entry["size"] < self.mini_stream_cutoff:
                    return self._read_mini_stream(entry["start"], entry["size"])
                return self._read_fat_stream(entry["start"], entry["size"])
        raise KeyError(f"No stream named one of {names}")


def _read_unicode_string(buf, off, chars):
    opts = buf[off]
    off += 1
    is_16 = opts & 0x01
    has_ext = opts & 0x04
    has_rich = opts & 0x08
    rich_runs = _u16(buf, off) if has_rich else 0
    off += 2 if has_rich else 0
    ext_size = _u32(buf, off) if has_ext else 0
    off += 4 if has_ext else 0
    byte_len = chars * (2 if is_16 else 1)
    raw = buf[off : off + byte_len]
    text = raw.decode("utf-16le" if is_16 else "latin1", errors="ignore")
    off += byte_len + rich_runs * 4 + ext_size
    return text, off


def _parse_sst(data):
    strings = []
    records = []
    i = 0
    while i + 4 <= len(data):
        rt = _u16(data, i)
        ln = _u16(data, i + 2)
        payload = data[i + 4 : i + 4 + ln]
        if rt in (0x00FC, 0x003C):
            records.append(payload)
        i += 4 + ln
    if not records:
        return strings
    # Most IMF exports keep SST strings inside a single record. The continuation
    # fallback below joins payloads, which is sufficient for these simple labels.
    payload = b"".join(records)
    pos = 8
    while pos + 3 <= len(payload):
        chars = _u16(payload, pos)
        pos += 2
        try:
            text, pos = _read_unicode_string(payload, pos, chars)
        except Exception:
            break
        strings.append(text)
    return strings


def _rk_value(raw):
    mult_100 = raw & 0x01
    is_int = raw & 0x02
    value_bits = raw & 0xFFFFFFFC
    if is_int:
        if value_bits & 0x80000000:
            value_bits -= 0x100000000
        val = value_bits >> 2
    else:
        packed = struct.pack("<II", 0, value_bits)
        val = struct.unpack("<d", packed)[0]
    return val / 100 if mult_100 else val


def _cell_key(row, col):
    return (int(row), int(col))


def parse_biff_workbook(path):
    cf = CompoundFile(path)
    wb = cf.open_stream(["Workbook", "Book"])
    records = []
    pos = 0
    while pos + 4 <= len(wb):
        rt = _u16(wb, pos)
        ln = _u16(wb, pos + 2)
        payload = wb[pos + 4 : pos + 4 + ln]
        records.append((pos, rt, payload))
        pos += 4 + ln

    sst = _parse_sst(wb)
    sheets = []
    for _, rt, p in records:
        if rt == 0x0085 and len(p) >= 8:
            bof = _u32(p, 0)
            name_len = p[6]
            flags = p[7]
            raw = p[8 : 8 + name_len * (2 if flags & 0x01 else 1)]
            name = raw.decode("utf-16le" if flags & 0x01 else "latin1", errors="ignore")
            sheets.append({"name": name, "offset": bof, "cells": {}})

    by_offset = {s["offset"]: s for s in sheets}
    sheet_offsets = sorted(by_offset)
    current = None
    for rec_off, rt, p in records:
        if rec_off in by_offset:
            current = by_offset[rec_off]
        if current is None:
            continue
        cells = current["cells"]
        if rt == 0x0203 and len(p) >= 14:  # NUMBER
            cells[_cell_key(_u16(p, 0), _u16(p, 2))] = _f64(p, 6)
        elif rt == 0x00FD and len(p) >= 10:  # LABELSST
            idx = _u32(p, 6)
            cells[_cell_key(_u16(p, 0), _u16(p, 2))] = sst[idx] if idx < len(sst) else ""
        elif rt == 0x0204 and len(p) >= 8:  # LABEL
            row, col = _u16(p, 0), _u16(p, 2)
            chars = _u16(p, 6)
            text, _ = _read_unicode_string(p, 8, chars)
            cells[_cell_key(row, col)] = text
        elif rt == 0x027E and len(p) >= 10:  # RK
            cells[_cell_key(_u16(p, 0), _u16(p, 2))] = _rk_value(_u32(p, 6))
        elif rt == 0x00BD and len(p) >= 6:  # MULRK
            row, first_col = _u16(p, 0), _u16(p, 2)
            last_col = _u16(p, len(p) - 2)
            off = 4
            for col in range(first_col, last_col + 1):
                if off + 6 > len(p):
                    break
                cells[_cell_key(row, col)] = _rk_value(_u32(p, off + 2))
                off += 6
        elif rt == 0x0006 and len(p) >= 14:  # FORMULA cached result
            row, col = _u16(p, 0), _u16(p, 2)
            raw = p[6:14]
            if raw[6:] == b"\xff\xff":
                continue
            val = struct.unpack("<d", raw)[0]
            if math.isfinite(val):
                cells[_cell_key(row, col)] = val
    return sheets


def _clean_label(value):
    value = str(value or "").strip()
    value = value.replace("\u0160", "")
    value = re.sub(r"\s+", " ", value)
    return value


def normalize_imf_export(path, country_code):
    sheets = parse_biff_workbook(path)
    indicators = []
    for sheet in sheets:
        cells = sheet["cells"]
        rows = {}
        for (r, c), v in cells.items():
            rows.setdefault(r, {})[c] = v
        title = _clean_label(rows.get(0, {}).get(0))
        if not title:
            continue
        year_cols = {}
        for c, value in rows.get(0, {}).items():
            if c == 0:
                continue
            if isinstance(value, (int, float)) and 1900 <= int(value) <= 2100 and abs(value - int(value)) < 1e-9:
                year_cols[c] = int(value)
        if len(year_cols) < 2:
            continue
        data_row = None
        estimate_start_after = None
        for c, value in rows.get(0, {}).items():
            if _clean_label(value).lower() == "estimates start after":
                raw_est = rows.get(2, {}).get(c)
                if isinstance(raw_est, (int, float)) and math.isfinite(raw_est):
                    estimate_start_after = int(raw_est)
                break
        for r in sorted(rows):
            label = _clean_label(rows[r].get(0))
            if label == country_code:
                data_row = rows[r]
                break
        if data_row is None:
            # Some exports use the readable country name in col A.
            for r in sorted(rows):
                label = _clean_label(rows[r].get(0))
                if label and not label.startswith("IMF") and r > 0:
                    data_row = rows[r]
                    break
        if data_row is None:
            continue
        series = []
        for c, year in sorted(year_cols.items(), key=lambda x: x[1]):
            val = data_row.get(c)
            if isinstance(val, str):
                try:
                    val = float(val.replace(",", ""))
                except Exception:
                    val = None
            if isinstance(val, (int, float)) and math.isfinite(val):
                series.append({"year": year, "value": val})
        if len(series) >= 2:
            unit = ""
            if "(" in title and title.endswith(")"):
                unit = title[title.rfind("(") + 1 : -1]
            indicators.append(
                {
                    "code": sheet["name"],
                    "indicator": title,
                    "unit": unit,
                    "estimate_start_after": estimate_start_after,
                    "series": series,
                }
            )
    return {"country": country_code, "source_file": str(path), "indicators": indicators}


def main():
    root = Path(__file__).resolve().parents[1]
    data_dir = root / "data"
    out_dir = root / "out"
    out_dir.mkdir(exist_ok=True)
    exports = {
        "Australia": data_dir / "imf-dm-export-20260423_aus.xls",
        "Canada": data_dir / "imf-dm-export-20260423_can.xls",
    }
    payload = {country: normalize_imf_export(path, country) for country, path in exports.items()}
    (out_dir / "imf_country_profiles.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")
    for country, obj in payload.items():
        print(country, len(obj["indicators"]), obj["indicators"][:3])


if __name__ == "__main__":
    main()
