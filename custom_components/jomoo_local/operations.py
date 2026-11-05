"""Allowlisted physical actions and device feedback; no raw write entry point."""
from .core import combined_payload, f3_frame, require_idle

COMMON_ACTIONS = {
    "open_cover": "开盖", "close_cover": "关盖", "open_ring": "翻起座圈", "close_ring": "放下座圈",
    "flush_large": "大冲", "flush_small": "小冲", "bubble": "魔力泡",
}
ACTIONS = {
    "sq9650": {**COMMON_ACTIONS, "hibernate": "待机"},
    "zs800j": {**COMMON_ACTIONS, "self_clean": "自清洁模式", "nozzle_clean": "喷嘴清洁",
               "replace_nozzle": "更换喷嘴", "stop_clean": "停止清洁／维护"},
}


def action_done(model, action, s):
    if action in ("open_cover", "close_cover"):
        return s.get("cover_open") == (action == "open_cover") and s.get("cover_running") is False
    if action in ("open_ring", "close_ring"):
        return s.get("ring_open") == (action == "open_ring") and s.get("ring_running") is False
    if action in ("flush_large", "flush_small"):
        return s.get(action + "_running") is True
    if action == "bubble":
        return s.get("bubble_running") is True
    if action == "hibernate":
        return s.get("work_state") == 1
    if action == "self_clean":
        return s.get("self_clean_running") is True
    if action == "nozzle_clean":
        return s.get("work_state") == 3
    if action == "replace_nozzle":
        return s.get("work_state") == 131
    if action == "stop_clean":
        return s.get("work_state") in (1, 2) and s.get("self_clean_running") is False and s.get("auto_running") is False
    return False


def action_frame(model, action, state):
    if action not in ACTIONS[model]:
        raise ValueError("该型号不支持此操作")
    if action != "stop_clean":
        require_idle(model, state)
    if model == "sq9650":
        command, value = {"open_cover": (0x33, 1), "close_cover": (0x33, 0),
                          "open_ring": (0x34, 1), "close_ring": (0x34, 0),
                          "flush_large": (0x35, 2), "flush_small": (0x35, 1),
                          "bubble": (0x46, 1), "hibernate": (0x17, 1)}[action]
        raw = bytearray([0xfc, 0, 1, 0, 0, 0, command, value, 0xfc])
        raw[1] = sum(raw[2:-1]) & 255
        return bytes(raw)
    if action == "bubble":
        return f3_frame([0x1f, 0x20, 1])
    if action == "self_clean":
        return f3_frame([0x1f, 0x28, 0x80])
    command = {"open_cover": 19 if state["ring_open"] else 17, "close_cover": 16,
               "open_ring": 19, "close_ring": 17, "flush_large": 14, "flush_small": 15,
               "nozzle_clean": 9, "replace_nozzle": 22, "stop_clean": 0}[action]
    return f3_frame(combined_payload(state, command))


def working_label(model, s):
    if s.get("device_fault"):
        return "设备报告故障"
    for key, label in (("cover_running", "翻盖中"), ("ring_running", "翻圈中"),
                       ("flush_large_running", "大冲中"), ("flush_small_running", "小冲中"),
                       ("bubble_running", "发泡中"), ("self_clean_running", "自清洁中")):
        if s.get(key):
            return label
    work = s.get("work_state")
    if model == "sq9650":
        return {0: "就绪", 2: "就绪", 1: "待机", 16: "自清洁中", 17: "预湿润中", 31: "设备自检中"}.get(work, "运行中")
    if work in (1, 2):
        return "就绪"
    return {3: "喷嘴清洁中", 131: "更换喷嘴中", 16: "暖风中", 144: "暖风中"}.get(work, "清洗／运行中")
