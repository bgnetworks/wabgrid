

import logging
import os
import queue
import warnings
from collections import OrderedDict
from importlib import import_module

import attr

from ..factory import target_factory
from .common import ManagedResource
from .base import SerialPort






@attr.s(eq=False)
class USBResource(ManagedResource):
    #manager_cls = UdevManager

    match = attr.ib(factory=dict, validator=attr.validators.instance_of(dict), hash=False)
    device = attr.ib(default=None, hash=False)
    suggest = attr.ib(default=False, hash=False, repr=False)

    def __attrs_post_init__(self):
        self.timeout = 5.0
        self.log = logging.getLogger('USBResource')
        self.match.setdefault('SUBSYSTEM', 'usb')
        super().__attrs_post_init__()

    def filter_match(self, device):  # pylint: disable=unused-argument,no-self-use
        return True

    def suggest_match(self, device):
        meta = OrderedDict()
        suggestions = []

        if self.device.device_node:
            meta['device node'] = self.device.device_node
        if list(self.device.tags):
            meta['udev tags'] = ', '.join(self.device.tags)
        if self.device.properties.get('ID_VENDOR'):
            meta['vendor'] = self.device.properties.get('ID_VENDOR')
        if self.device.properties.get('ID_VENDOR_FROM_DATABASE'):
            meta['vendor (DB)'] = self.device.properties.get('ID_VENDOR_FROM_DATABASE')
        if self.device.properties.get('ID_MODEL'):
            meta['model'] = self.device.properties.get('ID_MODEL')
        if self.device.properties.get('ID_MODEL_FROM_DATABASE'):
            meta['model (DB)'] = self.device.properties.get('ID_MODEL_FROM_DATABASE')
        if self.device.properties.get('ID_REVISION'):
            meta['revision'] = self.device.properties.get('ID_REVISION')

        path = self.device.properties.get('ID_PATH')
        if path:
            suggestions.append({'ID_PATH': path})
        elif self.match.get('@SUBSYSTEM', None) == 'usb':
            path = self._get_usb_device().properties.get('ID_PATH')
            if path:
                suggestions.append({'@ID_PATH': path})

        serial = self.device.properties.get('ID_SERIAL_SHORT')
        if serial:
            suggestions.append({'ID_SERIAL_SHORT': serial})
        elif self.match.get('@SUBSYSTEM', None) == 'usb':
            serial = self._get_usb_device().properties.get('ID_SERIAL_SHORT')
            if serial:
                suggestions.append({'@ID_SERIAL_SHORT': serial})

        return meta, suggestions

    def try_match(self, device):
        if self.device is None:  # new device
            def match_single(dev, key, value):
                if dev.properties.get(key) == value:
                    return True
                if dev.attributes.get(key) and dev.attributes.asstring(key) == value:
                    return True
                if getattr(dev, key, None) == value:
                    return True
                return False

            def match_ancestors(key, value):
                for ancestor in device.ancestors:
                    if match_single(ancestor, key, value):
                        return True
                return False

            for k, v in self.match.items():
                if k.startswith('@'):
                    if not match_ancestors(k[1:], v):
                        return False
                else:
                    if not match_single(device, k, v):
                        return False

            if not self.filter_match(device):
                return False
        else:  # update
            if self.device.sys_path != device.sys_path:
                return False

        self.log.debug(" found match: %s", self)

        if self.suggest and device.action in [None, 'add']:
            self.device = device
            self.suggest(self, *self.suggest_match(device))
            self.device = None
            return False

        if device.action in [None, 'add']:
            if self.avail:
                warnings.warn(f"udev device {device} is already available")
            self.device = device
        elif device.action in ['change', 'move']:
            self.device = device
        elif device.action in ['unbind', 'remove']:
            self.device = None

        self.avail = self.device is not None
        self.update()

        return True

    def update(self):
        pass

    @property
    def busnum(self):
        device = self._get_usb_device()
        if device:
            return int(device.properties.get('BUSNUM'))

        return None

    @property
    def devnum(self):
        device = self._get_usb_device()
        if device:
            return int(device.properties.get('DEVNUM'))

        return None

    def _get_usb_device(self):
        device = self.device
        if self.device is not None and (self.device.subsystem != 'usb'
                                        or self.device.device_type != 'usb_device'):
            device = self.device.find_parent('usb', 'usb_device')
        return device

    @property
    def path(self):
        device = self._get_usb_device()
        if device:
            return str(device.sys_name)

        return None

    @property
    def vendor_id(self):
        device = self._get_usb_device()
        if device:
            return int(device.properties.get('ID_VENDOR_ID'), 16)

        return None

    @property
    def model_id(self):
        device = self._get_usb_device()
        if device:
            return int(device.properties.get('ID_MODEL_ID'), 16)

        return None

    def read_attr(self, attribute):
        """read uncached attribute value from sysfs

        pyudev currently supports only cached access to attributes, so we read
        directly from sysfs.
        """
        # FIXME update pyudev to support udev_device_set_sysattr_value(dev,
        # attr, None) to clear the cache
        if self.device is not None:
            with open(os.path.join(self.device.sys_path, attribute), 'rb') as f:
                return f.read().rstrip(b'\n') # drop trailing newlines

        return None


@target_factory.reg_resource
@attr.s(eq=False)
class USBSerialPort(USBResource, SerialPort):
    def __attrs_post_init__(self):
        self.match['SUBSYSTEM'] = 'tty'
        self.match['@SUBSYSTEM'] = 'usb'
        if self.port:
            warnings.warn(
                "USBSerialPort: The port attribute will be overwritten by udev.\n"
                "Please use udev matching as described in http://labgrid.readthedocs.io/en/latest/configuration.html#udev-matching"  # pylint: disable=line-too-long
            )
        super().__attrs_post_init__()

    def update(self):
        super().update()
        if self.device is not None:
            self.port = self.device.device_node
        else:
            self.port = None