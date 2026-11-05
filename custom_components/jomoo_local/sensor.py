from homeassistant.components.sensor import SensorEntity
from .entity import JomooEntity
from .operations import working_label


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities(JomooStatus(c, key, label) for key, label in (
        ("work_state", "工作状态"), ("cover_open", "盖板状态"), ("ring_open", "座圈状态"), ("seated", "着座状态"), ("bluetooth_connection", "蓝牙连接状态")))


class JomooStatus(JomooEntity, SensorEntity):
    domain = "sensor"

    @property
    def available(self):
        if self.key == "bluetooth_connection":
            return not self.coordinator.stopping
        return super().available

    @property
    def native_value(self):
        if self.key == "bluetooth_connection":
            if self.coordinator.released:
                return "已释放给手机"
            client = self.coordinator._ble_client
            if client is not None and client.is_connected:
                return "已连接"
            return "等待指令（按需连接）" if not self.coordinator.persistent else "未连接"
        s = self.coordinator.data or {}
        if self.key not in s:
            return None
        if self.key == "work_state":
            return working_label(self.coordinator.model, s)
        if self.key == "seated":
            return "有人着座" if s[self.key] else "未着座"
        return "打开" if s[self.key] else "关闭"
