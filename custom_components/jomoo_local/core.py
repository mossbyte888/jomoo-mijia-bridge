"""Model-specific JOMOO settings. No Home Assistant imports or motion commands."""
from __future__ import annotations

CHAR = "0000ffe1-0000-1000-8000-00805f9b34fb"
PROFILES = {
    "sq9650": {"name": "SQ9650"},
    "zs800j": {"name": "ZS800J"},
}
SWITCHES = {
    "sq9650": {"night_light": "夜灯", "light_sensor": "光感夜灯", "auto_flush": "自动冲刷", "auto_close_flush": "关盖冲厕",
               "foot_sensor": "脚感控制", "prewetting": "预湿润", "auto_bubble": "落座发泡"},
    "zs800j": {"light_sensor": "智能夜灯", "atmosphere_light": "氛围灯", "auto_flush": "自动冲刷", "auto_close_flush": "关盖冲厕",
               "auto_cover": "自动翻盖", "auto_small_flush": "自动小冲", "foot_sensor": "脚感控制",
               "uv_water": "水路UV杀菌", "prewetting": "预湿润", "auto_bubble": "落座发泡", "auto_temp": "四季温感"},
}
SELECT_LABELS = {"seat_temp_level": "座温", "water_temp_level": "水温", "air_temp": "风温", "wind_speed": "风速",
                 "cover_sensitivity": "翻盖模式", "foam_time": "刷圈发泡"}
SELECTS = {
    "sq9650": {"seat_temp_level": {"常温": 0, "中温": 3, "高温": 5}},
    "zs800j": {
        **{k: dict(zip(("常温", "最低", "偏低", "标准", "偏高", "最高"), range(6))) for k in ("seat_temp_level", "water_temp_level")},
        "air_temp": dict(zip(("常温", "偏低", "标准", "偏高", "最高"), range(5))),
        "wind_speed": {f"{i}档": i for i in range(1, 6)},
        "cover_sensitivity": {"短距档": 0, "灵敏档": 1},
        "foam_time": {"快速档": 3, "中速档": 6, "标准档": 9},
    },
}


def query(model):
    return bytes.fromhex("fc 12 01 00 00 00 11 00 fc" if model == "sq9650" else "f3 f4 08 92 00 e2 00 00 00 00 7c fc")


def unescape(raw):
    out = bytearray([0xfc]); i = 1
    while i < len(raw) - 1:
        b = raw[i]
        if b == 0xfd:
            i += 1
            if i >= len(raw) - 1 or raw[i] not in (1, 2):
                raise ValueError("Invalid FC escape")
            b = 0xfb + raw[i]
        out.append(b); i += 1
    out.append(0xfc)
    return out


def parse(model, raw):
    """Return a packet kind and fields; reject incomplete or corrupt data."""
    if model == "sq9650":
        if len(raw) < 9 or raw[0] != 0xfc or raw[-1] != 0xfc:
            raise ValueError("Incomplete FC frame")
        d = unescape(raw)
        if sum(d[2:-1]) & 255 != d[1]:
            raise ValueError("FC checksum")
        if d[6] != 0x30:
            return "other", {}
        if len(d) < 26:
            raise ValueError("Incomplete SQ9650 status")
        return "status", {
            "work_state": d[7] & 31, "seated": bool(d[11] & 128),
            "night_light": bool(d[16] & 64), "light_sensor": bool(d[16] & 128),
            "auto_flush": bool(d[17] & 128), "auto_close_flush": bool(d[13] & 16),
            "foot_sensor": bool(d[11] & 8), "prewetting": bool(d[13] & 4),
            "cover_open": bool(d[11] & 16), "ring_open": bool(d[11] & 32),
            "cover_running": bool(d[13] & 2), "ring_running": bool(d[13] & 1),
            "flush_large_running": (d[12] & 3) == 2, "flush_small_running": (d[12] & 3) == 1,
            "device_fault": bool(d[8] & 127 or d[9] & 183 or d[10] & 224),
            "seat_temp_level": (d[17] >> 3) & 7,
            "open_loop_bubble": bool(d[20] & 8), "auto_bubble": bool(d[20] & 16),
            "bubble_running": bool(d[20] & 32),
        }
    if model != "zs800j":
        raise ValueError("Unsupported model")
    d = raw
    if (len(d) < 8 or d[:2] != b"\xf3\xf4" or d[-1] != 0xfc or
            d[2] != len(d) - 4 or sum(d[2:-2]) & 255 != d[-2]):
        raise ValueError("F3F4 length/checksum")
    if d[3] != 0x21:
        return "other", {}
    if d[5] == 0xe2:
        if len(d) < 12:
            raise ValueError("Incomplete E2")
        # Use FA for shared fields; E2 adds gesture, night light and foam time.
        fields = {"gesture": bool(d[6] & 4), "night_light": bool(d[6] & 1)}
        if len(d) >= 13:
            fields["foam_time"] = d[10]
        return "e2", fields
    if d[5] == 0xea:
        if len(d) < 11:
            raise ValueError("Incomplete EA")
        return "ea", {"cover_sensitivity": (d[8] >> 4) & 1,
                      "cover_open": bool(d[6] & 8), "ring_open": bool(d[6] & 2),
                      "cover_running": bool(d[6] & 64), "ring_running": bool(d[6] & 32)}
    if d[5] == 0xfa:
        if len(d) < 16:
            raise ValueError("Incomplete FA")
        return "fa", {
            "water_temp_level": (d[6] >> 4) & 7, "auto_flush": bool(d[6] & 2),
            "auto_cover": bool(d[6] & 8), "unblock_running": bool(d[6] & 128),
            "seat_temp_level": d[7] & 7, "hip_nozzle": (d[7] >> 4) & 7,
            "power_save": bool(d[7] & 128), "light_sensor": bool(d[8] & 128),
            "hip_pressure": (d[8] >> 4) & 7, "air_temp": d[8] & 7,
            "woman_nozzle": d[9] & 15, "woman_pressure": d[9] >> 4,
            "auto_close_flush": bool(d[10] & 2), "wind_speed": (d[10] >> 4) & 7,
            "auto_deodorization": bool(d[10] & 1), "uv_water": bool(d[11] & 32),
            "flush_running": bool(d[10] & 12), "atmosphere_light": bool(d[11] & 16),
            "flush_small_running": bool(d[10] & 4), "flush_large_running": bool(d[10] & 8),
            "atmosphere_mode": d[11] >> 6, "auto_temp": bool(d[11] & 8),
            "bubble_running": bool(d[12] & 4), "auto_bubble": bool(d[12] & 8),
            "open_loop_bubble": bool(d[12] & 16), "prewetting": bool(d[12] & 32),
            "wide_wash": d[13] & 7,
            "foot_sensor": bool(d[13] & 32), "auto_small_flush": bool(d[13] & 16),
        }
    if d[5] == 0xe9:
        if len(d) < 14:
            raise ValueError("Incomplete E9")
        return "e9", {"seated": bool(d[6] & 128), "work_state": d[9],
                       "auto_running": bool(d[10] & 8),
                       "self_clean_running": bool(d[11] & 1),
                       "device_fault": bool(d[7] & 253 or d[8] & 35),
                       "temperature_fault": bool(d[7] & 0x3d or d[8] & 0x23)}
    return "other", {}


class FrameStream:
    """Reassemble notifications, with checksum-based resynchronization."""
    def __init__(self, model):
        self.model = model
        self.buffer = bytearray()

    def feed(self, data):
        self.buffer.extend(data)
        if len(self.buffer) > 4096:
            self.buffer.clear()
            raise ValueError("BLE frame buffer limit")
        frames = []
        prefix = b"\xfc" if self.model == "sq9650" else b"\xf3\xf4"
        while self.buffer:
            start = self.buffer.find(prefix)
            if start < 0:
                self.buffer[:] = self.buffer[-1:] if self.buffer[-1:] == prefix[:1] else b""
                break
            del self.buffer[:start]
            if self.model == "sq9650":
                end = self.buffer.find(0xfc, 1)
                if end < 0:
                    break
                size = end + 1
            else:
                if len(self.buffer) < 3:
                    break
                size = self.buffer[2] + 4
                if size < 8:
                    del self.buffer[0]; continue
                if len(self.buffer) < size:
                    break
            raw = bytes(self.buffer[:size])
            try:
                kind, state = parse(self.model, raw)
            except ValueError:
                del self.buffer[0]
                continue
            del self.buffer[:size]
            frames.append((kind, state))
        return frames


def validate_setting(model, key, value):
    if key in SWITCHES[model]:
        if type(value) is not bool:
            raise ValueError("Switch requires boolean")
    elif key in SELECTS[model]:
        if type(value) is not int or value not in SELECTS[model][key].values():
            raise ValueError("Unsupported setting level")
    else:
        raise ValueError("Setting unsupported on this model")


def require_idle(model, state):
    if state["seated"] or state["bubble_running"]:
        raise ValueError("有人着座或泡沫功能正在运行，请空闲后重试")
    if model == "sq9650":
        idle = state["work_state"] in (0, 2)
    else:
        idle = state["work_state"] in (1, 2) and not any(state[k] for k in ("auto_running", "flush_running", "unblock_running", "temperature_fault"))
    if not idle:
        raise ValueError("马桶正在运行或报告故障，请空闲后重试")
    if any(state.get(k) for k in ("cover_running", "ring_running", "flush_large_running", "flush_small_running", "self_clean_running", "device_fault")):
        raise ValueError("马桶有动作正在执行或报告故障，请空闲后重试")


def setting_frame(model, key, value, state):
    validate_setting(model, key, value)
    require_idle(model, state)
    if model == "sq9650":
        if key == "night_light" and state["light_sensor"]:
            raise ValueError("请先关闭光感夜灯，再设置普通夜灯")
        if key == "seat_temp_level":
            payload = [0x3c, value]
        else:
            cmd, sub = {"night_light": (0x41, 0), "light_sensor": (0x40, 2),
                        "auto_flush": (0x40, 5), "auto_close_flush": (0x40, 20),
                        "foot_sensor": (0x40, 14), "prewetting": (0x40, 18), "auto_bubble": (0x40, 12)}[key]
            payload = [cmd, sub, int(value)]
        frame = bytearray([0xfc, 0, 1, 0, 0, 0, *payload, 0xfc])
        frame[1] = sum(frame[2:-1]) & 255
        # All reviewed settings have values that need no FC escape.
        return bytes(frame)
    single_settings = {
        "atmosphere_light": (0x33, 0x20, 0x10), "auto_close_flush": (0x25, 1, 2),
        "foot_sensor": (0x24, 1, 2), "auto_small_flush": (0x25, 4, 8),
        "uv_water": (0x21, 0x40, 0x20), "prewetting": (0x30, 4, 0),
        "auto_bubble": (0x20, 2, 4),
    }
    if key == "cover_sensitivity":
        payload = [0x1f, 0x11 if value == 0 else 0x10, 0]
    elif key == "foam_time":
        payload = [0x1f, 0x20, 0x80, value]
    elif key in single_settings:
        sub, on, off = single_settings[key]
        payload = [0x1f, sub, on if value else off]
    else:
        # 0x02 toggles seasonal temperature. The transport checks the current
        # value before sending and verifies readback; it never retries a write.
        payload = combined_payload({**state, key: value}, 0x02 if key == "auto_temp" else 0x19)
    return f3_frame(payload)


def combined_payload(s, command):
    """Reviewed idle/control form, never personal washing or drying starts."""
    for k in ("hip_nozzle", "hip_pressure", "woman_nozzle", "woman_pressure", "wide_wash", "wind_speed"):
        if not 1 <= s[k] <= 5:
            raise ValueError(f"无法保留设备设置 {k}={s[k]}")
    return [command,
            s["water_temp_level"] << 4 | s["auto_cover"] << 3 | s["gesture"] << 2 | s["auto_flush"] << 1 | s["night_light"],
            s["power_save"] << 7 | s["hip_nozzle"] << 4 | s["seat_temp_level"],
            s["light_sensor"] << 7 | s["hip_pressure"] << 4 | s["air_temp"],
            s["wide_wash"] << 4, 0, s["wind_speed"] << 4, 0, 0, 0, 0, 0]


def f3_frame(payload):
    frame = bytearray([0xf3, 0xf4, 0, 0x92, 0x21, *payload, 0, 0xfc])
    frame[2] = len(frame) - 4
    frame[-2] = sum(frame[2:-2]) & 255
    return bytes(frame)


VOLATILE_FIELDS = {"seated", "work_state", "auto_running", "bubble_running", "flush_running", "unblock_running", "temperature_fault",
                   "cover_open", "ring_open", "cover_running", "ring_running", "flush_large_running", "flush_small_running", "self_clean_running", "device_fault"}


def verify_setting_changes(model, key, value, before, after):
    allowed = {key}
    if model == "zs800j" and key == "prewetting" and value is False:
        # User-observed model behavior: disabling prewetting disables seat foam.
        if after.get("auto_bubble") is not False:
            raise RuntimeError("预湿润已关闭，但尚未确认落座发泡联动关闭")
        allowed.add("auto_bubble")
    elif model == "zs800j" and key == "prewetting" and value is True and after.get("auto_bubble") is True:
        # Hardware readback also showed prewetting enabling seat foam. Permit this exact coupling, not other setting changes.
        allowed.add("auto_bubble")
    changed = [k for k in before if k not in allowed | VOLATILE_FIELDS and after.get(k) != before[k]]
    if changed:
        raise RuntimeError("写入后其他设置发生变化：" + ", ".join(changed))
