"""Stable identity independent of room names or a particular household."""
import re


def normalize_address(value):
    address = value.strip().replace('-', ':').upper()
    if re.fullmatch(r'(?:[0-9A-F]{2}:){5}[0-9A-F]{2}', address) is None:
        raise ValueError('Invalid Bluetooth MAC address')
    return address


def entity_prefix(model, address):
    return f'jomoo_{model}_{normalize_address(address).replace(":", "").lower()}'
