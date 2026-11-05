#!/usr/bin/env python3
"""Generate a generic allowlisted Mi Home router and native HA dashboard."""
import argparse
import importlib
import json
from pathlib import Path
import re
import sys
import types

ROOT = Path(__file__).resolve().parents[1]
package = types.ModuleType('jomoo_generator')
package.__path__ = [str(ROOT / 'custom_components/jomoo_local')]
sys.modules[package.__name__] = package
core = importlib.import_module('jomoo_generator.core')
ops = importlib.import_module('jomoo_generator.operations')
identity = importlib.import_module('jomoo_generator.identity')
presets = importlib.import_module('jomoo_generator.preset_config')


def parse_device(value):
    try:
        alias, model, address = value.split('=', 2)
        if not re.fullmatch(r'[a-z][a-z0-9_]*', alias) or model not in core.PROFILES:
            raise ValueError
        return alias, model, identity.normalize_address(address)
    except ValueError as exc:
        raise argparse.ArgumentTypeError('设备格式：别名=型号=MAC；别名用小写字母、数字、下划线') from exc


def build(devices, gateway_event, include_actions=False):
    if not re.fullmatch(r'event\.[a-z0-9_]+', gateway_event):
        raise ValueError('网关实体必须是 event.xxx')
    if len({d[0] for d in devices}) != len(devices):
        raise ValueError('设备别名不能重复')
    if len({d[2] for d in devices}) != len(devices):
        raise ValueError('设备蓝牙地址不能重复')
    if not devices:
        raise ValueError('至少配置一台设备')
    routes, rows, settings_cards, action_cards = {}, [], [], []
    mode_cards = {mode: [] for mode in presets.MODES}
    mode_targets = {mode: [] for mode in presets.MODES}
    for alias, model, address in devices:
        prefix = identity.entity_prefix(model, address)
        title = f'{core.PROFILES[model]["name"]} · {alias}'
        entities = [{'entity': f'sensor.{prefix}_work_state', 'name': '工作状态'}]
        for key, label in {**core.SWITCHES[model], 'bluetooth_release': '释放蓝牙给小程序'}.items():
            entity = f'switch.{prefix}_{key}'
            entities.append({'entity': entity, 'name': label})
            for suffix, action, word in [('on', 'switch.turn_on', '开启'), ('off', 'switch.turn_off', '关闭')]:
                name = f'jomoo_{alias}_{key}_{suffix}'
                routes[name] = {'action': action, 'entity': entity}
                rows.append(f'| {title} · {label}{word} | `{name}` |')
        for key, options in core.SELECTS[model].items():
            entity = f'select.{prefix}_{key}'
            entities.append({'entity': entity, 'name': core.SELECT_LABELS[key]})
            for option, value in options.items():
                name = f'jomoo_{alias}_{key}_{value}'
                routes[name] = {'action': 'select.select_option', 'entity': entity, 'option': option}
                rows.append(f'| {title} · {core.SELECT_LABELS[key]} {option} | `{name}` |')
        for mode, label in presets.MODES.items():
            button = f'button.{prefix}_apply_{mode}'
            mode_targets[mode].append(button)
            entities.append({'entity': button, 'name': f'应用{label}'})
            name = f'jomoo_{alias}_mode_{mode}'
            routes[name] = {'action': 'button.press', 'entity': button}
            rows.append(f'| {title} · 应用{label} | `{name}` |')
            editors = [{'entity': f'select.{prefix}_preset_{mode}_{key}',
                        'name': core.SWITCHES[model].get(key, core.SELECT_LABELS.get(key, key))}
                       for key in presets.fields(model)]
            editors.append({'entity': button, 'name': f'应用{label}（本台）'})
            mode_cards[mode].append({'type': 'entities', 'title': title, 'show_header_toggle': False, 'entities': editors})
        settings_cards.append({'type': 'entities', 'title': title, 'show_header_toggle': False, 'entities': entities})
        actions = [{'entity': f'sensor.{prefix}_{key}', 'name': label} for key, label in
                   [('cover_open', '盖板状态'), ('ring_open', '座圈状态'), ('seated', '着座状态')]]
        for key, label in ops.ACTIONS[model].items():
            entity = f'button.{prefix}_{key}'
            actions.append({'entity': entity, 'name': label})
            if include_actions:
                name = f'jomoo_{alias}_{key}_press'
                routes[name] = {'action': 'button.press', 'entity': entity}
                rows.append(f'| {title} · 立即执行：{label} | `{name}` |')
        action_cards.append({'type': 'entities', 'title': title, 'show_header_toggle': False, 'entities': actions})
    for mode, label in presets.MODES.items():
        name = f'jomoo_mode_{mode}'
        routes[name] = {'action': 'button.press', 'entity': mode_targets[mode]}
        rows.insert(0 if mode == 'default' else 1, f'| 全部已配置马桶 · 应用{label} | `{name}` |')
    automation = {
        'id': 'jomoo_virtual_event_router', 'alias': '九牧智联桥：米家虚拟事件',
        'description': '只接收事件表中的名称；忽略恢复的历史状态与过期事件。',
        'triggers': [{'trigger': 'state', 'entity_id': gateway_event}],
        'variables': {
            'routes': routes,
            'event_name': "{{ trigger.to_state.attributes.get('事件名称', '') if trigger.to_state is not none else '' }}",
            'route': '{{ routes.get(event_name, {}) }}',
        },
        'conditions': [{'condition': 'template', 'value_template':
            "{{ trigger.from_state is not none and trigger.from_state.state not in ['unknown', 'unavailable'] and trigger.to_state is not none and trigger.to_state.state != trigger.from_state.state and event_name in routes and as_datetime(trigger.to_state.state, none) is not none and 0 <= (as_timestamp(now()) - as_timestamp(trigger.to_state.state, 0)) < 30 }}"}],
        'actions': [{'choose': [{'conditions': "{{ route.action == 'select.select_option' }}", 'sequence': [
            {'action': 'select.select_option', 'target': {'entity_id': '{{ route.entity }}'}, 'data': {'option': '{{ route.option }}'}}
        ]}], 'default': [{'action': '{{ route.action }}', 'target': {'entity_id': '{{ route.entity }}'}}]}],
        'mode': 'parallel', 'max': 20, 'max_exceeded': 'warning',
    }
    dashboard = {'title': '九牧智联桥', 'views': [
        {'title': '设置', 'path': 'settings', 'icon': 'mdi:toilet', 'cards': settings_cards},
        {'title': '操作', 'path': 'actions', 'icon': 'mdi:gesture-tap', 'cards': [
            {'type': 'markdown', 'content': '操作按钮会立即执行机械动作。请先确认设备空闲；超时后查看现场，不要连续重试。'}, *action_cards]},
    ]}
    for mode, label in presets.MODES.items():
        dashboard['views'].append({'title': f'{label}配置', 'path': f'preset-{mode}', 'icon': 'mdi:tune', 'cards': [
            {'type': 'markdown', 'content': f'## {label}配置\n修改自动保存，**不会立即控制马桶**。点击应用或运行米家模式事件才生效。“保持现状”不主动修改该项；设备联动仍然有效。默认模式初始全部保持现状；省电模式初始将温度设为常温并关闭 ZS800J 四季温感。请先编辑自己的目标。'},
            *mode_cards[mode],
            {'type': 'button', 'name': f'全部应用{label}', 'icon': 'mdi:play-circle-outline',
             'tap_action': {'action': 'perform-action', 'perform_action': 'button.press', 'target': {'entity_id': mode_targets[mode]}}},
        ]})
    table = '# 米家事件名称\n\n手机米家「产生虚拟事件」中直接填写下表名称，不加引号或方括号。\n\n'
    table += '模式使用方法见 [自定义模式教程](../docs/自定义模式.md)。`jomoo_mode_default` 应用全部设备默认模式，`jomoo_mode_eco` 应用全部设备省电模式；单台事件跟随生成时的别名。\n\n'
    table += '“释放蓝牙”开启后，HA 暂停控制；关闭后重新连接。\n\n'
    table += '| 操作 | 事件名称 |\n| --- | --- |\n' + '\n'.join(rows) + '\n'
    return automation, dashboard, table


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--device', type=parse_device, action='append', required=True, help='可重复：别名=型号=MAC')
    parser.add_argument('--gateway-event', required=True, help='Xiaomi Home 网关的 event 实体 ID')
    parser.add_argument('--include-actions', action='store_true', help='将立即执行的机械动作也接入米家事件')
    parser.add_argument('--output', type=Path, default=Path('output'))
    args = parser.parse_args()
    try:
        automation, dashboard, table = build(args.device, args.gateway_event, args.include_actions)
    except ValueError as exc:
        parser.error(str(exc))
    args.output.mkdir(parents=True, exist_ok=True)
    for name, value in [('automation.yaml', automation), ('dashboard.yaml', dashboard)]:
        (args.output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    (args.output / '米家事件名称.md').write_text(table, encoding='utf-8')
    print(f'已生成 {len(automation["variables"]["routes"])} 条事件及控制面板：{args.output}')


if __name__ == '__main__':
    main()
