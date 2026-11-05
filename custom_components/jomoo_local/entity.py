from homeassistant.helpers.update_coordinator import CoordinatorEntity
from .const import DOMAIN
from .core import PROFILES
from .identity import entity_prefix


class JomooEntity(CoordinatorEntity):
    _attr_has_entity_name = True

    def __init__(self, coordinator, key, name):
        super().__init__(coordinator)
        self.key = key
        self._attr_name = name
        self._attr_unique_id = f"{coordinator.address}_{key}"
        # Stable names make event routing independent of UI translations.
        self.entity_id = f"{self.domain}.{entity_prefix(coordinator.model, coordinator.address)}_{key}"
        profile = PROFILES[coordinator.model]
        self._attr_device_info = {"identifiers": {(DOMAIN, coordinator.address)}, "name": coordinator.config_entry.title, "manufacturer": "九牧", "model": profile["name"]}

    @property
    def available(self):
        if not self.coordinator.persistent:
            return not self.coordinator.released and not self.coordinator.stopping
        return not self.coordinator.released and super().available and self.key in (self.coordinator.data or {})

    @property
    def extra_state_attributes(self):
        return {"连接策略": "长连接" if self.coordinator.persistent else "按需连接",
                "上次读取时间": self.coordinator.last_read,
                "上次错误": self.coordinator.last_error,
                "状态说明": "最近一次设备读回；按需连接时不自动更新"}
