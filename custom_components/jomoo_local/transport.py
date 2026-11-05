"""BLE transactions over an injected persistent or standalone connection."""
import asyncio

from .core import CHAR, FrameStream, query, setting_frame, validate_setting, verify_setting_changes
from .operations import ACTIONS, action_frame, action_done

QUERY_RETRY_SECONDS = 2
READ_TIMEOUT_SECONDS = 8
ACTION_TIMEOUT_SECONDS = 15
# Do not send a status query back-to-back with a write-without-response command.
# Allow the BLE/UART bridge to consume one frame before sending the next.
# This spaces requests, never repeats writes.
COMMAND_SETTLE_SECONDS = 0.2


class CommandError(ValueError):
    """An operation failed, but a fresh device state is available."""
    def __init__(self, message, state):
        super().__init__(message)
        self.state = state


class SettingNotApplied(CommandError):
    """Complete fresh readback explicitly differs from an absolute target."""


class ToiletClient:
    def __init__(self, model, address, connection_factory=None):
        self.model, self.address = model, address
        self.connection_factory = connection_factory
        self.cooldowns = {}

    async def session(self, device, key=None, value=None, action=None):
        if action is not None and (action not in ACTIONS[self.model] or key is not None):
            raise ValueError("不支持的操作")
        if key is not None:
            validate_setting(self.model, key, value)
        if device is None or (device.name and not device.name.startswith("JOMOO_SMART_")):
            raise ValueError("没有发现目标九牧蓝牙设备，请核对地址和连接占用")
        from bleak import BleakClient
        connection = self.connection_factory(device) if self.connection_factory else BleakClient(device, timeout=15)
        async with connection as client:
            char = client.services.get_characteristic(CHAR)
            if char is None or not {"notify", "write-without-response"} <= set(char.properties):
                raise ValueError("FFE1 蓝牙服务不匹配")
            queue = asyncio.Queue()
            stream = FrameStream(self.model)

            def notified(_, data):
                try:
                    for packet in stream.feed(data):
                        queue.put_nowait(packet)
                except ValueError:
                    # Overflow discards the incomplete stream; read will time out.
                    pass

            async def read(expected=None, predicate=None, clear=True, timeout=None):
                if clear:
                    while not queue.empty():
                        queue.get_nowait()
                    stream.buffer.clear()
                await client.write_gatt_char(char, query(self.model), response=False)
                needed = {"status"} if self.model == "sq9650" else {"e2", "fa", "e9", "ea"}
                seen, state = set(), {}
                deadline = asyncio.get_running_loop().time() + (timeout if timeout is not None else READ_TIMEOUT_SECONDS)
                confirmed = False
                while True:
                    remaining = deadline - asyncio.get_running_loop().time()
                    if remaining <= 0:
                        if expected is not None and seen >= needed:
                            raise SettingNotApplied(f"设备已回复，但 {key} 未达到目标：期望 {expected}，实际 {state.get(key)}", state)
                        raise TimeoutError(f"未收到完整/匹配状态，已收到 {sorted(seen)}")
                    try:
                        kind, fields = await asyncio.wait_for(queue.get(), min(QUERY_RETRY_SECONDS, remaining))
                    except asyncio.TimeoutError:
                        # Missing optional cover feedback must not hide temperature
                        # and light state. Writes still require all four packets.
                        if self.model == "zs800j" and key is None and action is None and {"e2", "fa", "e9"} <= seen:
                            return state
                        # SQ9650 sometimes ignores the first query after connection.
                        # Retry only this read; never retry a setting write blindly.
                        if asyncio.get_running_loop().time() < deadline:
                            await client.write_gatt_char(char, query(self.model), response=False)
                        continue
                    if kind in needed:
                        seen.add(kind); state.update(fields)
                    if predicate is not None and predicate(state):
                        confirmed = True
                    if seen >= needed and (expected is None or state.get(key) == expected) and (predicate is None or confirmed):
                        return state

            await client.start_notify(char, notified)
            try:
                before = await read()
                if action is not None:
                    if action in ("open_cover", "close_cover", "open_ring", "close_ring", "stop_clean", "hibernate") and action_done(self.model, action, before):
                        return before
                    group = "flush" if action.startswith("flush_") else action
                    now = asyncio.get_running_loop().time()
                    if now < self.cooldowns.get(group, 0):
                        raise CommandError("操作冷却中，请稍后重试", before)
                    try:
                        frame = action_frame(self.model, action, before)
                    except ValueError as exc:
                        raise CommandError(str(exc), before) from exc
                    # Never resend a physical command, even if feedback is lost.
                    self.cooldowns[group] = now + (35 if group == "flush" else 30 if group == "bubble" else 3)
                    if self.model == "zs800j":
                        await asyncio.sleep(COMMAND_SETTLE_SECONDS)
                    await client.write_gatt_char(char, frame, response=False)
                    await asyncio.sleep(COMMAND_SETTLE_SECONDS)
                    try:
                        return await read(predicate=lambda s: action_done(self.model, action, s), clear=False, timeout=ACTION_TIMEOUT_SECONDS)
                    except TimeoutError as exc:
                        raise TimeoutError("指令已发送，但未确认设备动作；请查看现场，勿连续重复操作") from exc
                if key is None or before[key] == value:
                    return before
                try:
                    frame = setting_frame(self.model, key, value, before)
                except ValueError as exc:
                    raise CommandError(str(exc), before) from exc
                if self.model == "zs800j":
                    await asyncio.sleep(COMMAND_SETTLE_SECONDS)
                await client.write_gatt_char(char, frame, response=False)
                await asyncio.sleep(COMMAND_SETTLE_SECONDS)
                after = await read(value)
                try:
                    verify_setting_changes(self.model, key, value, before, after)
                except RuntimeError as exc:
                    raise CommandError(str(exc), after) from exc
                return after
            finally:
                if client.is_connected:
                    await client.stop_notify(char)
