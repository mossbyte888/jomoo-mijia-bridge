"""Generic mode templates and planning; no device or household configuration."""
from .core import SELECTS, SWITCHES

MODES = {"default": "默认模式", "eco": "省电模式"}
KEEP = "保持现状"


def fields(model):
    return {**{k: {KEEP: None, "开启": True, "关闭": False} for k in SWITCHES[model]},
            **{k: {KEEP: None, **options} for k, options in SELECTS[model].items()}}


def defaults(model):
    data = {mode: {key: KEEP for key in fields(model)} for mode in MODES}
    for key in ("seat_temp_level", "water_temp_level", "air_temp"):
        if key in data["eco"]:
            data["eco"][key] = "常温"
    if "auto_temp" in data["eco"]:
        data["eco"]["auto_temp"] = "关闭"
    return data


def validate(model, data):
    allowed = fields(model)
    if not isinstance(data, dict) or set(data) != set(MODES):
        raise ValueError("模式配置格式异常")
    for values in data.values():
        if not isinstance(values, dict) or set(values) != set(allowed):
            raise ValueError("模式配置项目不完整")
        if any(not isinstance(v, str) or v not in allowed[k] for k, v in values.items()):
            raise ValueError("模式配置中有不支持的档位")


def plan(model, values, state):
    """Resolve dependent settings before the first write, using fresh readback."""
    options = fields(model)
    target = {k: options[k][v] for k, v in values.items() if v != KEEP}
    if not target:
        return {}
    required = set(target)
    if model == "sq9650" and {"night_light", "light_sensor"} & required:
        required.add("light_sensor")
    if model == "zs800j" and {"prewetting", "auto_bubble"} & required:
        required.update(("prewetting", "auto_bubble"))
    missing = required - state.keys()
    if missing:
        raise ValueError("未读到完整设置：" + ", ".join(sorted(missing)))
    if model == "sq9650" and target.get("light_sensor", state.get("light_sensor")):
        target.pop("night_light", None)
    if model == "zs800j" and {"prewetting", "auto_bubble"} & target.keys():
        wet = target.get("prewetting", state["prewetting"])
        if not wet and target.get("auto_bubble") is True:
            raise ValueError("落座发泡需要开启预湿润")
        if "prewetting" in target:
            # Restore kept foam after enabling wetting; disabling wetting
            # necessarily disables foam on this model.
            target.setdefault("auto_bubble", state["auto_bubble"] if wet else False)
    # Disable seasonal control before fixed temperatures; wetting before foam;
    # disable the SQ light sensor before setting its ordinary night light.
    priority = {"auto_temp": 0, "light_sensor": 1, "prewetting": 2, "auto_bubble": 3}
    return dict(sorted(target.items(), key=lambda item: priority.get(item[0], 4)))
