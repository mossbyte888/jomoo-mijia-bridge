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
        return not self.coordinator.released and super().available and self.key in (self.coordinator.data or {})
