from homeassistant.components.switch import SwitchEntity
from .core import SWITCHES
from .entity import JomooEntity
from homeassistant.helpers.entity import EntityCategory


async def async_setup_entry(hass, entry, async_add_entities):
    c = entry.runtime_data
    async_add_entities([JomooSwitch(c, k, v) for k, v in SWITCHES[c.model].items()] + [BluetoothReleaseSwitch(c), PersistentConnectionSwitch(c)])


class JomooSwitch(JomooEntity, SwitchEntity):
    domain = "switch"

    @property
    def is_on(self):
        return (self.coordinator.data or {}).get(self.key)

    async def async_turn_on(self, **kwargs):
        await self.coordinator.set_setting(self.key, True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.set_setting(self.key, False)


class BluetoothReleaseSwitch(JomooEntity, SwitchEntity):
    domain = "switch"
    _attr_icon = "mdi:bluetooth-off"

    def __init__(self, coordinator):
        super().__init__(coordinator, "bluetooth_release", "释放蓝牙给小程序")

    @property
    def available(self):
        return not self.coordinator.stopping

    @property
    def is_on(self):
        return self.coordinator.released

    async def async_turn_on(self, **kwargs):
        await self.coordinator.set_released(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.set_released(False)


class PersistentConnectionSwitch(JomooEntity, SwitchEntity):
    domain = "switch"
    _attr_icon = "mdi:bluetooth-connect"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, coordinator):
        super().__init__(coordinator, "persistent_connection", "保持蓝牙连接")

    @property
    def available(self):
        return not self.coordinator.stopping

    @property
    def is_on(self):
        return self.coordinator.persistent

    async def async_turn_on(self, **kwargs):
        await self.coordinator.set_persistent(True)

    async def async_turn_off(self, **kwargs):
        await self.coordinator.set_persistent(False)
