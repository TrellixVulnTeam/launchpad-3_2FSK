# Copyright 2008 Canonical Ltd.  All rights reserved.
"""Tests of the HWDB submissions parser."""

import bz2
from cStringIO import StringIO
from datetime import datetime
import logging
import os
import pytz
from unittest import TestCase, TestLoader

from zope.component import getUtility
from zope.testing.loghandler import Handler

from canonical.config import config
from canonical.launchpad.interfaces.hwdb import (
    HWBus, HWSubmissionFormat, HWSubmissionProcessingStatus,
    IHWDeviceDriverLinkSet, IHWDeviceSet, IHWDriverSet,
    IHWSubmissionDeviceSet, IHWSubmissionSet, IHWVendorIDSet,
    IHWVendorNameSet)
from canonical.librarian.ftests.harness import fillLibrarianFile
from canonical.launchpad.scripts.hwdbsubmissions import (
    HALDevice, PCI_CLASS_BRIDGE, PCI_CLASS_SERIALBUS_CONTROLLER,
    PCI_CLASS_STORAGE, PCI_SUBCLASS_BRIDGE_CARDBUS, PCI_SUBCLASS_BRIDGE_PCI,
    PCI_SUBCLASS_SERIALBUS_USB, PCI_SUBCLASS_STORAGE_SATA, SubmissionParser,
    process_pending_submissions)
from canonical.launchpad.webapp.errorlog import ErrorReportingUtility
from canonical.testing import BaseLayer, LaunchpadZopelessLayer


class TestCaseHWDB(TestCase):
    """Common base class for HWDB processing tests."""

    layer = BaseLayer

    UDI_COMPUTER = '/org/freedesktop/Hal/devices/computer'
    UDI_SATA_CONTROLLER = '/org/freedesktop/Hal/devices/pci_8086_27c5'
    UDI_SATA_CONTROLLER_SCSI = ('/org/freedesktop/Hal/devices/'
                               'pci_8086_27c5_scsi_host')
    UDI_SATA_DISK = ('org/freedesktop/Hal/devices/'
                     'pci_8086_27c5_scsi_host_scsi_device_lun0')
    UDI_USB_CONTROLLER_PCI_SIDE = '/org/freedesktop/Hal/devices/pci_8086_27cc'
    UDI_USB_CONTROLLER_USB_SIDE = ('/org/freedesktop/Hal/devices/'
                                   'usb_device_0_0_0000_00_1d_7')
    UDI_USB_CONTROLLER_USB_SIDE_RAW = ('/org/freedesktop/Hal/devices/'
                                   'usb_device_0_0_0000_00_1d_7_usbraw')
    UDI_USB_STORAGE = '/org/freedesktop/Hal/devices/usb_device_1307_163_07'
    UDI_USB_STORAGE_IF0 = ('/org/freedesktop/Hal/devices/'
                           'usb_device_1307_163_07_if0')
    UDI_USB_STORAGE_SCSI_HOST = ('/org/freedesktop/Hal/devices/'
                                 'usb_device_1307_163_07_if0scsi_host')
    UDI_USB_STORAGE_SCSI_DEVICE = ('/org/freedesktop/Hal/devices/'
                                   'usb_device_1307_163_07_if0'
                                   'scsi_host_scsi_device_lun0')
    UDI_USB_HUB = '/org/freedesktop/Hal/devices/usb_device_409_5a_noserial'
    UDI_USB_HUB_IF0 = ('/org/freedesktop/Hal/devices/'
                       'usb_dev_409_5a_noserial_if0')
    UDI_PCI_PCI_BRIDGE = '/org/freedesktop/Hal/devices/pci_8086_2448'
    UDI_PCI_PCCARD_BRIDGE = '/org/freedesktop/Hal/devices/pci_1217_7134'
    UDI_PCCARD_DEVICE = '/org/freedesktop/Hal/devices/pci_9004_6075'

    UDI_SCSI_DISK = '/org/freedesktop/Hal/devices/scsi_disk'

    PCI_VENDOR_ID_INTEL = 0x8086
    PCI_PROD_ID_PCI_PCCARD_BRIDGE = 0x7134
    PCI_PROD_ID_PCCARD_DEVICE = 0x6075
    PCI_PROD_ID_USB_CONTROLLER = 0x27cc

    USB_VENDOR_ID_NEC = 0x0409
    USB_PROD_ID_NEC_HUB = 0x005a

    USB_VENDOR_ID_USBEST = 0x1307
    USB_PROD_ID_USBBEST_MEMSTICK = 0x0163

    KERNEL_VERSION = '2.6.24-19-generic'
    KERNEL_PACKAGE = 'linux-image-' + KERNEL_VERSION

    def setUp(self):
        """Setup the test environment."""
        self.log = logging.getLogger('test_hwdb_submission_parser')
        self.log.setLevel(logging.INFO)
        self.handler = Handler(self)
        self.handler.add(self.log.name)

    def assertWarningMessage(self, submission_key, log_message):
        """Search for message in the log entries for submission_key.

        :raise: AssertionError if no log message exists that starts with
            "Parsing submission <submission_key>:" and that contains
            the text passed as the parameter message.
        """
        expected_message = 'Parsing submission %s: %s' % (
            submission_key, log_message)

        for record in self.handler.records:
            if record.levelno != logging.WARNING:
                continue
            candidate = record.getMessage()
            if candidate == expected_message:
                return
        raise AssertionError('No log message found: %s' % expected_message)


class TestHWDBSubmissionProcessing(TestCaseHWDB):
    """Tests for processing of HWDB submissions."""

    def testBuildDeviceList(self):
        """Test the creation of list HALDevice instances for a submission."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {},
                },
            {
                'id': 2,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.parent': (self.UDI_COMPUTER, 'str')
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        self.assertEqual(len(parser.hal_devices), len(devices),
                         'Numbers of devices in parser.hal_devices and in '
                         'sample data are different')
        root_device = parser.hal_devices[self.UDI_COMPUTER]
        self.assertEqual(root_device.id, 1,
                         'Unexpected value of root device ID.')
        self.assertEqual(root_device.udi, self.UDI_COMPUTER,
                         'Unexpected value of root device UDI.')
        self.assertEqual(root_device.properties,
                         devices[0]['properties'],
                         'Unexpected properties of root device.')
        child_device = parser.hal_devices[self.UDI_SATA_CONTROLLER]
        self.assertEqual(child_device.id, 2,
                         'Unexpected value of child device ID.')
        self.assertEqual(child_device.udi, self.UDI_SATA_CONTROLLER,
                         'Unexpected value of child device UDI.')
        self.assertEqual(child_device.properties,
                         devices[1]['properties'],
                         'Unexpected properties of child device.')

        parent = parser.hal_devices[self.UDI_COMPUTER]
        child = parser.hal_devices[self.UDI_SATA_CONTROLLER]
        self.assertEqual(parent.children, [child],
                         'Child missing in parent.children.')
        self.assertEqual(child.parent, parent,
                         'Invalid value of child.parent.')

    def testKernelPackageName(self):
        """Test of SubmissionParser.getKernelPackageName.

        Regular case.
        """
        parser = SubmissionParser(self.log)
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {
                    'system.kernel.version': (self.KERNEL_VERSION, 'str'),
                    },
                },
            ]
        parser.parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            'software': {
                'packages': {
                    self.KERNEL_PACKAGE: {},
                    },
                },
            }
        parser.buildDeviceList(parser.parsed_data)
        kernel_package = parser.getKernelPackageName()
        self.assertEqual(kernel_package, self.KERNEL_PACKAGE,
            'Unexpected result of SubmissionParser.getKernelPackageName. '
            'Expected linux-image-2.6.24-19-generic, got %r' % kernel_package)

        self.assertEqual(len(self.handler.records), 0,
            'One or more warning messages were logged by '
            'getKernelPackageName, where zero was expected.')

    def testKernelPackageNameInconsistent(self):
        """Test of SubmissionParser.getKernelPackageName.

        Test a name inconsistency.
        """
        parser = SubmissionParser(self.log)
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {
                    'system.kernel.version': (self.KERNEL_VERSION, 'str'),
                    },
                },
            ]
        parser.parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            'software': {
                'packages': {
                    'linux-image-from-obscure-external-source': {},
                    },
                },
            }
        parser.submission_key = 'Test of inconsistent kernel package name'
        parser.buildDeviceList(parser.parsed_data)
        kernel_package = parser.getKernelPackageName()
        self.assertEqual(kernel_package, None,
            'Unexpected result of SubmissionParser.getKernelPackageName. '
            'Expected None, got %r' % kernel_package)
        self.assertWarningMessage(parser.submission_key,
            'Inconsistent kernel version data: According to HAL the '
            'kernel is 2.6.24-19-generic, but the submission does not '
            'know about a kernel package linux-image-2.6.24-19-generic')
        # The warning appears only once per submission, even if the
        # SubmissionParser.getKernelPackageName is called more than once.
        num_warnings = len(self.handler.records)
        parser.getKernelPackageName()
        self.assertEqual(num_warnings, len(self.handler.records),
            'Warning for missing HAL property system.kernel.version '
            'repeated.')

    def testKernelPackageNameNoHALData(self):
        """Test of SubmissionParser.getKernelPackageName.

        Test without HAL property system.kernel.version.
        """
        parser = SubmissionParser(self.log)
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {},
                },
            ]
        parser.parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            'software': {
                'packages': {
                    'linux-image-from-obscure-external-source': {},
                    },
                },
            }
        parser.submission_key = 'Test: missing property system.kernel.version'
        parser.buildDeviceList(parser.parsed_data)
        kernel_package = parser.getKernelPackageName()
        self.assertEqual(kernel_package, None,
            'Unexpected result of SubmissionParser.getKernelPackageName. '
            'Expected None, got %r' % kernel_package)
        self.assertWarningMessage(parser.submission_key,
            'Submission does not provide property system.kernel.version '
            'for /org/freedesktop/Hal/devices/computer.')
        # The warning appears only once per submission, even if the
        # SubmissionParser.getKernelPackageName is called more than once.
        num_warnings = len(self.handler.records)
        parser.getKernelPackageName()
        self.assertEqual(num_warnings, len(self.handler.records),
            'Warning for missing HAL property system.kernel.version '
            'repeated.')

    def testHALDeviceConstructor(self):
        """Test of the HALDevice constructor."""
        properties = {
            'info.bus': ('scsi', 'str'),
            }
        parser = SubmissionParser(self.log)
        device = HALDevice(1, '/some/udi/path', properties, parser)

        self.assertEqual(device.id, 1, 'Unexpected device ID')
        self.assertEqual(device.udi, '/some/udi/path',
                         'Unexpected device UDI.')
        self.assertEqual(device.properties, properties,
                         'Unexpected device properties.')
        self.assertEqual(device.parser, parser,
                         'Unexpected device parser.')

    def testHALDeviceGetProperty(self):
        """Test of HALDevice.getProperty."""
        properties = {
            'info.bus': ('scsi', 'str'),
            }
        parser = SubmissionParser(self.log)
        device = HALDevice(1, '/some/udi/path', properties, parser)

        # HALDevice.getProperty returns the value of a HAL property.
        # Note that the property type is _not_ returned
        self.assertEqual(device.getProperty('info.bus'), 'scsi',
            'Unexpected result of calling HALDevice.getProperty.')
        # If a property of the given name does not exist, None is returned.
        self.assertEqual(device.getProperty('does-not-exist'), None,
            'Unexpected result of calling HALDevice.getProperty for a '
            'non-existing property.')

    def testHALDeviceParentUDI(self):
        """Test of HALDevice.parent_udi."""
        properties = {
            'info.bus': ('scsi', 'str'),
            'info.parent': ('/another/udi', 'str'),
            }
        parser = SubmissionParser(self.log)
        device = HALDevice(1, '/some/udi/path', properties, parser)
        self.assertEqual(device.parent_udi, '/another/udi',
                         'Unexpected value of HALDevice.parent_udi.')

        properties = {
            'info.bus': ('scsi', 'str'),
            }
        parser = SubmissionParser(self.log)
        device = HALDevice(1, '/some/udi/path', properties, parser)
        self.assertEqual(device.parent_udi, None,
                         'Unexpected value of HALDevice.parent_udi, '
                         'when no parent information available.')

    def testHalDeviceRawBus(self):
        """test of HALDevice.raw_bus."""
        properties = {
            'info.bus': ('scsi', 'str'),
            'info.parent': ('/another/udi', 'str'),
            }
        parser = SubmissionParser(self.log)
        device = HALDevice(1, '/some/udi/path', properties, parser)
        self.assertEqual(device.raw_bus, 'scsi',
                         'Unexpected value of HALDevice.raw_bus for '
                         'HAL property info.bus.')

        properties = {
            'info.subsystem': ('scsi', 'str'),
            'info.parent': ('/another/udi', 'str'),
            }
        parser = SubmissionParser(self.log)
        device = HALDevice(1, '/some/udi/path', properties, parser)
        self.assertEqual(device.raw_bus, 'scsi',
                         'Unexpected value of HALDevice.raw_bus for '
                         'HAL property info.bus.')


    def testHALDeviceGetRealBus(self):
        """Test of HALDevice.real_bus, generic case.

        For most buses as "seen" by HAL, HALDevice.real_bus returns a
        unique HWBus value.
        """
        for hal_bus, real_bus in (('usb_device', HWBus.USB),
                                  ('pcmcia', HWBus.PCMCIA),
                                  ('ide', HWBus.IDE),
                                  ('serio', HWBus.SERIAL),
                                 ):
            UDI_TEST_DEVICE = '/org/freedesktop/Hal/devices/test_device'
            devices = [
                {
                    'id': 1,
                    'udi': UDI_TEST_DEVICE,
                    'properties': {
                        'info.bus': (hal_bus, 'str'),
                        },
                    },
                ]
            parsed_data = {
                'hardware': {
                    'hal': {
                        'devices': devices,
                        },
                    },
                }
            parser = SubmissionParser(self.log)
            parser.buildDeviceList(parsed_data)
            test_device = parser.hal_devices[UDI_TEST_DEVICE]
            test_bus = test_device.real_bus
            self.assertEqual(test_bus, real_bus,
                             'Unexpected result of HALDevice.real_bus for '
                             'HAL bus %s: %s.' % (hal_bus, test_bus.title))

    def testHALDeviceGetRealBusSystem(self):
        """Test of HALDevice.real_bus, for the tested machine itself."""

        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {
                    'info.bus': ('unknown', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        test_device = parser.hal_devices[self.UDI_COMPUTER]
        test_bus = test_device.real_bus
        self.assertEqual(test_bus, HWBus.SYSTEM,
                         'Unexpected result of HALDevice.real_bus for '
                         'a system: %s' % test_bus.title)

    def testHALDeviceGetRealBusScsiUsb(self):
        """Test of HALDevice.real_bus for info.bus=='scsi' and a USB device.

        Memory sticks, card readers and USB->IDE/SATA adapters use SCSI
        emulation; HALDevice.real_bus treats these devices as "black boxes",
        and thus returns None.
        """
        devices = [
            # The main node of the USB storage device.
            {
                'id': 1,
                'udi': self.UDI_USB_STORAGE,
                'properties': {
                    'info.bus': ('usb_device', 'str'),
                    },
                },
            # The storage interface of the USB device.
            {
                'id': 2,
                'udi': self.UDI_USB_STORAGE_IF0,
                'properties': {
                    'info.bus': ('usb', 'str'),
                    'info.parent': (self.UDI_USB_STORAGE, 'str'),
                    },
                },
            # The fake SCSI host of the storage device. Note that HAL does
            # _not_ provide the info.bus property.
            {
                'id': 3,
                'udi': self.UDI_USB_STORAGE_SCSI_HOST,
                'properties': {
                    'info.parent': (self.UDI_USB_STORAGE_IF0, 'str'),
                    },
                },
            # The fake SCSI disk.
            {
                'id': 3,
                'udi': self.UDI_USB_STORAGE_SCSI_DEVICE,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'info.parent': (self.UDI_USB_STORAGE_SCSI_HOST, 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)

        usb_fake_scsi_disk = parser.hal_devices[
            self.UDI_USB_STORAGE_SCSI_DEVICE]
        self.assertEqual(usb_fake_scsi_disk.real_bus, None,
            'Unexpected result of HALDevice.real_bus for the fake SCSI '
            'disk HAL node of a USB storage device bus.')

    def testHALDeviceGetRealBusScsiPci(self):
        """Test of HALDevice.real_bus for info.bus=='scsi'.

        Many non-SCSI devices support the SCSI command, and the Linux
        kernel can treat them like SCSI devices. The real bus of these
        devices can be found by looking at the PCI class and subclass
        of the host controller of the possibly fake SCSI device.
        The real bus of these device can be IDE, ATA, SATA or SCSI.
        """
        devices = [
            # The PCI host controller.
            {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    'pci.device_class': (PCI_CLASS_STORAGE, 'int'),
                    'pci.device_subclass': (PCI_SUBCLASS_STORAGE_SATA,
                                            'int'),
                    },
                },
            # The fake SCSI host of the storage device. Note that HAL does
            # _not_ provide the info.bus property.
            {
                'id': 2,
                'udi': self.UDI_SATA_CONTROLLER_SCSI,
                'properties': {
                    'info.parent': (self.UDI_SATA_CONTROLLER, 'str'),
                    },
                },
            # The (possibly fake) SCSI disk.
            {
                'id': 3,
                'udi': self.UDI_SATA_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'info.parent': (self.UDI_SATA_CONTROLLER_SCSI, 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }

        pci_subclass_bus = (
            (0, HWBus.SCSI),
            (1, HWBus.IDE),
            (2, HWBus.FLOPPY),
            (3, HWBus.IPI),
            (4, None), # subclass RAID is ignored.
            (5, HWBus.ATA),
            (6, HWBus.SATA),
            (7, HWBus.SAS),
            )

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)

        for device_subclass, expected_bus in pci_subclass_bus:
            devices[0]['properties']['pci.device_subclass'] = (
                device_subclass, 'int')
            fake_scsi_disk = parser.hal_devices[self.UDI_SATA_DISK]
            found_bus = fake_scsi_disk.real_bus
            self.assertEqual(found_bus, expected_bus,
                'Unexpected result of HWDevice.real_bus for PCI storage '
                'class device, subclass %i: %r.' % (device_subclass,
                                                    found_bus))

    def testHALDeviceGetRealBusScsiDeviceWithoutGrandparent(self):
        """Test of HALDevice.real_bus for a device without a grandparent."""
        devices = [
            # A SCSI host conrtoller.
            {
                'id': 2,
                'udi': self.UDI_SATA_CONTROLLER_SCSI,
                'properties': {},
                },
            # A SCSI disk.
            {
                'id': 3,
                'udi': self.UDI_SCSI_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'info.parent': (self.UDI_SATA_CONTROLLER_SCSI, 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.submission_key = 'Test SCSI disk without a grandparent'
        parser.buildDeviceList(parsed_data)
        scsi_disk = parser.hal_devices[self.UDI_SCSI_DISK]
        bus = scsi_disk.real_bus
        self.assertEqual(bus, None,
            'Unexpected result of HALDevice.real_bus for a SCSI device '
            'without a grandparent. Expected None, got %r' % bus)
        self.assertWarningMessage(parser.submission_key,
            'Found SCSI device without a grandparent: %s.'
             % self.UDI_SCSI_DISK)

    def testHALDeviceGetRealBusScsiDeviceWithoutParent(self):
        """Test of HALDevice.real_bus for a device without a parent."""
        devices = [
            {
                'id': 3,
                'udi': self.UDI_SCSI_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.submission_key = 'Test SCSI disk without a parent'
        parser.buildDeviceList(parsed_data)
        scsi_disk = parser.hal_devices[self.UDI_SCSI_DISK]
        bus = scsi_disk.real_bus
        self.assertEqual(bus, None,
            'Unexpected result of HALDevice.real_bus for a SCSI device '
            'without a parent. Expected None, got %r' % bus)
        self.assertWarningMessage(parser.submission_key,
            'Found SCSI device without a parent: %s.'
             % self.UDI_SCSI_DISK)

    def testHALDeviceGetRealBusScsiDeviceWithBogusPciGrandparent(self):
        """Test of HALDevice.real_bus for a device with a bogus grandparent.

        The PCI device class must be PCI_CLASS_STORAGE.
        """
        devices = [
            # The PCI host controller. The PCI device class is invalid.
            {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    'pci.device_class': (-1, 'int'),
                    'pci.device_subclass': (PCI_SUBCLASS_STORAGE_SATA, 'int'),
                    },
                },
            # The fake SCSI host of the storage device. Note that HAL does
            # _not_ provide the info.bus property.
            {
                'id': 2,
                'udi': self.UDI_SATA_CONTROLLER_SCSI,
                'properties': {
                    'info.parent': (self.UDI_SATA_CONTROLLER, 'str'),
                    },
                },
            # The (possibly fake) SCSI disk.
            {
                'id': 3,
                'udi': self.UDI_SATA_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'info.parent': (self.UDI_SATA_CONTROLLER_SCSI, 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.submission_key = (
            'Test SCSI disk with invalid controller device class')
        parser.buildDeviceList(parsed_data)
        scsi_disk = parser.hal_devices[self.UDI_SATA_DISK]
        bus = scsi_disk.real_bus
        self.assertEqual(bus, None,
            'Unexpected result of HALDevice.real_bus for a SCSI device '
            'without a parent. Expected None, got %r' % bus)
        self.assertWarningMessage(parser.submission_key,
            'A (possibly fake) SCSI device %s is connected to PCI device '
            '%s that has the PCI device class -1; expected class 1 (storage).'
             % (self.UDI_SATA_DISK, self.UDI_SATA_CONTROLLER))

    def testHALDeviceGetRealBusPci(self):
        """Test of HALDevice.real_bus for info.bus=='pci'.

        If info.bus == 'pci', we may have a real PCI device or a PCCard.
        """
        # possible parent device for the tested device,
        parent_devices = [
            # The host itself.
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {
                    'info.bus': ('unknown', 'str'),
                    },
                },
            # A PCI->PCI bridge.
            {
                'id': 2,
                'udi': self.UDI_PCI_PCI_BRIDGE,
                'properties': {
                    'info.parent': (self.UDI_COMPUTER, 'str'),
                    'info.bus': ('pci', 'str'),
                    'pci.device_class': (PCI_CLASS_BRIDGE, 'int'),
                    'pci.device_subclass': (PCI_SUBCLASS_BRIDGE_PCI, 'int'),
                    },
                },
            # A PCI->PCCard bridge.
            {
                'id': 3,
                'udi': self.UDI_PCI_PCCARD_BRIDGE,
                'properties': {
                    'info.parent': (self.UDI_PCI_PCI_BRIDGE, 'str'),
                    'info.bus': ('pci', 'str'),
                    'pci.device_class': (PCI_CLASS_BRIDGE, 'int'),
                    'pci.device_subclass': (PCI_SUBCLASS_BRIDGE_CARDBUS,
                                            'int'),
                    },
                },
        ]
        tested_device = {
            'id': 4,
            'udi': self.UDI_PCCARD_DEVICE,
            'properties': {
                'info.bus': ('pci', 'str'),
                },
            }
        parsed_data = {
            'hardware': {
                'hal': {},
                },
            }
        expected_result_for_parent_device = {
            self.UDI_COMPUTER: HWBus.PCI,
            self.UDI_PCI_PCI_BRIDGE: HWBus.PCI,
            self.UDI_PCI_PCCARD_BRIDGE: HWBus.PCCARD,
            }

        parser = SubmissionParser(self.log)

        for parent_device in parent_devices:
            devices = parent_devices[:]
            tested_device['properties']['info.parent'] = (
                parent_device['udi'], 'str')
            devices.append(tested_device)
            parsed_data['hardware']['hal']['devices'] = devices
            parser.buildDeviceList(parsed_data)
            tested_hal_device = parser.hal_devices[self.UDI_PCCARD_DEVICE]
            found_bus = tested_hal_device.real_bus
            expected_bus = expected_result_for_parent_device[
                parent_device['udi']]
            self.assertEqual(found_bus, expected_bus,
                             'Unexpected result of HWDevice.real_bus for a '
                             'PCI or PCCard device: Expected %r, got %r.'
                             % (expected_bus, found_bus))

    def testHALDeviceGetRealBusUnknown(self):
        """Test of HALDevice.real_bus for unknown values of info.bus."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_PCCARD_DEVICE,
                'properties': {
                    'info.bus': ('nonsense', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }

        parser = SubmissionParser(self.log)
        parser.submission_key = 'Test of unknown bus name'
        parser.buildDeviceList(parsed_data)
        found_bus = parser.hal_devices[self.UDI_PCCARD_DEVICE].real_bus
        self.assertEqual(found_bus, None,
                         'Unexpected result of HWDevice.real_bus for an '
                         'unknown bus name: Expected None, got %r.'
                         % found_bus)
        self.assertWarningMessage(
            parser.submission_key,
            "Unknown bus 'nonsense' for device " + self.UDI_PCCARD_DEVICE)

    def testHALDeviceRealDeviceRegularBus(self):
        """Test of HALDevice.is_real_device: regular info.bus property.

        See below for exceptions, if info.bus == 'usb_device' or if
        info.bus == 'usb'.
        """
        # If a HAL device has the property info.bus, it is considered
        # to be a real device.
        devices = [
            {
                'id': 1,
                'udi': self.UDI_USB_CONTROLLER_PCI_SIDE,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    'pci.device_class': (PCI_CLASS_SERIALBUS_CONTROLLER,
                                         'int'),
                    'pci.device_subclass': (PCI_SUBCLASS_SERIALBUS_USB,
                                            'int'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        device = parser.hal_devices[self.UDI_USB_CONTROLLER_PCI_SIDE]
        self.failUnless(device.is_real_device,
                        'Device with info.bus property not treated as a '
                        'real device')

    def testHALDeviceRealDeviceNoBus(self):
        """Test of HALDevice.is_real_device: No info.bus property."""
        UDI_HAL_STORAGE_DEVICE = '/org/freedesktop/Hal/devices/storage...'
        devices = [
            {
                'id': 1,
                'udi': UDI_HAL_STORAGE_DEVICE,
                'properties': {},
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        device = parser.hal_devices[UDI_HAL_STORAGE_DEVICE]
        self.failIf(device.is_real_device,
                    'Device without info.bus property treated as a '
                    'real device')

    def testHALDeviceRealDeviceHALBusValueIgnored(self):
        """Test of HALDevice.is_real_device: ignored values of info.bus.

        A HAL device is considered to not be a real device, if its
        info.bus proerty is 'usb' or 'ssb'.
        """
        UDI_SSB = '/org/freedesktop/Hal/devices/ssb__null__0'
        devices = [
            {
                'id': 1,
                'udi': self.UDI_USB_HUB_IF0,
                'properties': {
                    'info.bus': ('usb', 'str'),
                    },
                },
            {
                'id': 2,
                'udi': UDI_SSB,
                'properties': {
                    'info.bus': ('ssb', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }

        properties = devices[0]['properties']
        parser = SubmissionParser(self.log)

        parser.buildDeviceList(parsed_data)
        device = parser.hal_devices[self.UDI_USB_HUB_IF0]
        self.failIf(device.is_real_device,
                    'Device with info.bus=usb treated as a real device')
        device = parser.hal_devices[UDI_SSB]
        self.failIf(device.is_real_device,
                    'Device with info.bus=ssb treated as a real device')

    def testHALDeviceRealDeviceScsiDevicesPciController(self):
        """Test of HALDevice.is_real_device: info.bus == 'scsi'.

        The (fake or real) SCSI device is connected to a PCI controller.
        Though the real bus may not be SCSI, all devices for the busses
        SCSI, IDE, ATA, SATA, SAS are treated as real devices.
        """
        devices = [
            # The PCI host controller.
            {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    'pci.device_class': (PCI_CLASS_STORAGE, 'int'),
                    'pci.device_subclass': (PCI_SUBCLASS_STORAGE_SATA, 'int'),
                    },
                },
            # The (possibly fake) SCSI host of the storage device.
            {
                'id': 3,
                'udi': self.UDI_SATA_CONTROLLER_SCSI,
                'properties': {
                    'info.parent': (self.UDI_SATA_CONTROLLER,
                                    'str'),
                    },
                },
            # The (possibly fake) SCSI disk.
            {
                'id': 3,
                'udi': self.UDI_SATA_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'info.parent': (self.UDI_SATA_CONTROLLER_SCSI, 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }

        pci_subclass_bus = (
            (0, True), # a real SCSI controller
            (1, True), # an IDE device
            (4, False), # subclass RAID is ignored.
            (5, True), # an ATA device
            (6, True), # a SATA device
            (7, True), # a SAS device
            )

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)

        for device_subclass, expected_is_real in pci_subclass_bus:
            devices[0]['properties']['pci.device_subclass'] = (
                device_subclass, 'int')
            scsi_device = parser.hal_devices[self.UDI_SATA_DISK]
            found_is_real = scsi_device.is_real_device
            self.assertEqual(found_is_real, expected_is_real,
                'Unexpected result of HWDevice.is_real_device for a HAL SCSI '
                'connected to PCI controller, subclass %i: %r'
                % (device_subclass, found_is_real))

    def testHALDeviceRealDeviceScsiDeviceUsbStorage(self):
        """Test of HALDevice.is_real_device: info.bus == 'scsi'.

        USB storage devices are treated as SCSI devices by HAL;
        we do not consider them to be real devices.
        """
        devices = [
            # The main node of the USB storage device.
            {
                'id': 1,
                'udi': self.UDI_USB_STORAGE,
                'properties': {
                    'info.bus': ('usb_device', 'str'),
                    },
                },
            # The storage interface of the USB device.
            {
                'id': 2,
                'udi': self.UDI_USB_STORAGE_IF0,
                'properties': {
                    'info.bus': ('usb', 'str'),
                    'info.parent': (self.UDI_USB_STORAGE, 'str'),
                    },
                },
            # The fake SCSI host of the storage device. Note that HAL does
            # _not_ provide the info.bus property.
            {
                'id': 3,
                'udi': self.UDI_USB_STORAGE_SCSI_HOST,
                'properties': {
                    'info.parent': (self.UDI_USB_STORAGE_IF0, 'str'),
                    },
                },
            # The fake SCSI disk.
            {
                'id': 3,
                'udi': self.UDI_USB_STORAGE_SCSI_DEVICE,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'info.parent': (self.UDI_USB_STORAGE_SCSI_HOST, 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)

        scsi_device = parser.hal_devices[self.UDI_USB_STORAGE_SCSI_DEVICE]
        self.failIf(scsi_device.is_real_device,
            'Unexpected result of HWDevice.is_real_device for a HAL SCSI '
            'device as a subdevice of a USB storage device.')

    def testHALDeviceRealDeviceRootDevice(self):
        """Test of HALDevice.is_real_device for the root node."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {},
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        device = parser.hal_devices[self.UDI_COMPUTER]
        self.failUnless(device.is_real_device,
                        'Root device not treated as a real device')

    def testHALDeviceRealChildren(self):
        """Test of HALDevice.getRealChildren."""
        # An excerpt of a real world HAL device tree. We have three "real"
        # devices, and two "unreal" devices (ID 3 and 4)
        #
        # the host itself. Treated as a real device.
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {}
                },
            # A PCI->USB bridge.
            {
                'id': 2,
                'udi': self.UDI_USB_CONTROLLER_PCI_SIDE,
                'properties': {
                    'info.parent': (self.UDI_COMPUTER, 'str'),
                    'info.bus': ('pci', 'str'),
                    'pci.device_class': (PCI_CLASS_SERIALBUS_CONTROLLER,
                                         'int'),
                    'pci.device_subclass': (PCI_SUBCLASS_SERIALBUS_USB,
                                            'int'),
                 }
            },
            # The "output aspect" of the PCI->USB bridge. Not a real
            # device.
            {
                'id': 3,
                'udi': self.UDI_USB_CONTROLLER_USB_SIDE,
                'properties': {
                    'info.parent': (self.UDI_USB_CONTROLLER_PCI_SIDE, 'str'),
                    'info.bus': ('usb_device', 'str'),
                    'usb_device.vendor_id': (0, 'int'),
                    'usb_device.product_id': (0, 'int'),
                    },
                },
            # The HAL node for raw USB data access of the bridge. Not a
            # real device.
            {
                'id': 4,
                'udi': self.UDI_USB_CONTROLLER_USB_SIDE_RAW,
                'properties': {
                    'info.parent': (self.UDI_USB_CONTROLLER_USB_SIDE, 'str'),
                    },
                },
            # The HAL node of a USB device connected to the bridge.
            {
                'id': 5,
                'udi': self.UDI_USB_HUB,
                'properties': {
                    'info.parent': (self.UDI_USB_CONTROLLER_USB_SIDE, 'str'),
                    'info.bus': ('usb_device', 'str'),
                    'usb_device.vendor_id': (self.USB_VENDOR_ID_NEC, 'int'),
                    'usb_device.product_id': (self.USB_PROD_ID_NEC_HUB,
                                              'int'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)

        # The PCI-USB bridge is a child of the system.
        root_device = parser.hal_devices[self.UDI_COMPUTER]
        pci_usb_bridge = parser.hal_devices[self.UDI_USB_CONTROLLER_PCI_SIDE]
        self.assertEqual(root_device.getRealChildren(), [pci_usb_bridge],
                         'Unexpected list of real children of the root '
                         'device')

        # The "output aspect" of the PCI->USB bridge and the node for
        # raw USB access do not appear as childs of the PCI->USB bridge,
        # but the node for the USB device is considered to be a child
        # of the bridge.

        usb_device = parser.hal_devices[self.UDI_USB_HUB]
        self.assertEqual(pci_usb_bridge.getRealChildren(), [usb_device],
                         'Unexpected list of real children of the PCI-> '
                         'USB bridge')

    def testHasReliableDataRegularCase(self):
        """Test of HALDevice.has_reliable_data, regular case."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        device = parser.hal_devices[self.UDI_SATA_CONTROLLER]
        self.failUnless(device.has_reliable_data,
                        'Regular device treated as not having reliable data.')

    def testHasReliableDataNotProcessible(self):
        """Test of HALDevice.has_reliable_data, no reliable data."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {},
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        properties = devices[0]['properties']
        for bus in ('pnp', 'platform', 'ieee1394', 'pcmcia'):
            properties['info.bus'] = (bus, 'str')
            parser.buildDeviceList(parsed_data)
            device = parser.hal_devices[self.UDI_SATA_CONTROLLER]
            self.failIf(device.has_reliable_data,
                'Device with bus=%s treated as having reliable data.' % bus)

    def testHALDeviceVendorFromInfoVendor(self):
        """Test of HALDevice.vendor, regular case.

        The value is copied from info.vendor, if available."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    'info.vendor': ('Intel Corporation', 'str'),
                    'pci.vendor': ('should not be used', 'str'),
                    }
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_vendor = parser.hal_devices[self.UDI_SATA_CONTROLLER].vendor
        self.assertEqual(found_vendor, 'Intel Corporation',
                         'Unexpected result of HWDevice.vendor. '
                         'Expected Intel Corporation, got %r.'
                         % found_vendor)

    def testHALDeviceVendorFromBusVendor(self):
        """Test of HALDevice.vendor, value copied from ${bus}.vendor.

        If the property info.vendor does not exist, ${bus}.vendor
        is tried.
        """
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    'pci.vendor': ('Intel Corporation', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_vendor = parser.hal_devices[self.UDI_SATA_CONTROLLER].vendor
        self.assertEqual(found_vendor, 'Intel Corporation',
                         'Unexpected result of HWDevice.vendor, '
                         'if info.vendor does not exist. '
                         'Expected Intel Corporation, got %r.'
                         % found_vendor)

    def testHALDeviceVendorScsi(self):
        """Test of HALDevice.vendor for SCSI devices: regular case."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SCSI_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'scsi.vendor': ('SEAGATE', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_vendor = parser.hal_devices[self.UDI_SCSI_DISK].vendor
        self.assertEqual(found_vendor, 'SEAGATE',
                         'Unexpected result of HWDevice.vendor '
                         'for SCSI device. Expected SEAGATE, got %r.'
                         % found_vendor)

    def testHALDeviceVendorScsiAta(self):
        """Test of HALDevice.vendor for SCSI devices: fake IDE/SATA disks."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SCSI_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'scsi.vendor': ('ATA', 'str'),
                    'scsi.model': ('Hitachi HTS54161', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_vendor = parser.hal_devices[self.UDI_SCSI_DISK].vendor
        self.assertEqual(found_vendor, 'Hitachi',
                         'Unexpected result of HWDevice.vendor, for fake '
                         'SCSI device. Expected Hitachi, got %r.'
                         % found_vendor)

    def testHALDeviceVendorSystem(self):
        """Test of HALDevice.vendor for the machine itself."""
        # HAL does not provide info.vendor for the root UDI
        # /org/freedesktop/Hal/devices/computer, hence HALDevice.vendor
        # reads the vendor name from system.vendor
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {
                    'info.bus': ('unknown', 'str'),
                    'system.hardware.vendor': ('FUJITSU SIEMENS', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_vendor = parser.hal_devices[self.UDI_COMPUTER].vendor
        self.assertEqual(found_vendor, 'FUJITSU SIEMENS',
                         'Unexpected result of HWDevice.vendor for a '
                         'system. Expected FUJITSU SIEMENS, got %r.'
                         % found_vendor)

    def testHALDeviceProductFromInfoProduct(self):
        """Test of HALDevice.product, regular case.

        The value is copied from info.product, if available."""
        # The product name is copied from the HAL property info.product,
        # if it is avaliable.
        devices = [
             {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    'info.product': ('82801GBM/GHM SATA AHCI Controller',
                                     'str'),
                    'pci.product': ('should not be used', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_product = parser.hal_devices[self.UDI_SATA_CONTROLLER].product
        self.assertEqual(found_product, '82801GBM/GHM SATA AHCI Controller',
                         'Unexpected result of HWDevice.product. '
                         'Expected 82801GBM/GHM SATA AHCI Controller, got %r.'
                         % found_product)

    def testHALDeviceProductFromBusProduct(self):
        """Test of HALDevice.product, value copied from ${bus}.product.

        If the property info.product does not exist, ${bus}.product
        """
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    'pci.product': ('82801GBM/GHM SATA AHCI Controller',
                                    'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_product = parser.hal_devices[self.UDI_SATA_CONTROLLER].product
        self.assertEqual(found_product, '82801GBM/GHM SATA AHCI Controller',
                         'Unexpected result of HWDevice.product, '
                         'if info.product does not exist. '
                         'Expected 82801GBM/GHM SATA AHCI Controller, got %r.'
                         % found_product)

    def testHALDeviceProductScsi(self):
        """Test of HALDevice.product for SCSI devices: regular case."""
        # The name of SCSI device is copied from the property scsi.model.
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SCSI_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'scsi.vendor': ('SEAGATE', 'str'),
                    'scsi.model': ('ST36530N', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_product = parser.hal_devices[self.UDI_SCSI_DISK].product
        self.assertEqual(found_product, 'ST36530N',
                         'Unexpected result of HWDevice.product '
                         'for SCSI device. Expected ST36530N, got %r.'
                         % found_product)

    def testHALDeviceProductScsiAta(self):
        """Test of HALDevice.product for SCSI devices: fake IDE/SATA disks."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SCSI_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'scsi.vendor': ('ATA', 'str'),
                    'scsi.model': ('Hitachi HTS54161', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_product = parser.hal_devices[self.UDI_SCSI_DISK].product
        self.assertEqual(found_product, 'HTS54161',
                         'Unexpected result of HWDevice.product, for fake '
                         'SCSI device. Expected HTS54161, got %r.'
                         % found_product)

    def testHALDeviceProductSystem(self):
        """Test of HALDevice.product for the machine itself."""
        # HAL sets info.product to "Computer" for the root UDI
        # /org/freedesktop/Hal/devices/computer, hence HALDevice.product
        # reads the product name from system.product.
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {
                    'info.bus': ('unknown', 'str'),
                    'system.hardware.product': ('LIFEBOOK E8210', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_product = parser.hal_devices[self.UDI_COMPUTER].product
        self.assertEqual(found_product, 'LIFEBOOK E8210',
                         'Unexpected result of HWDevice.product, '
                         'if info.product does not exist. '
                         'Expected LIFEBOOK E8210, got %r.'
                         % found_product)

    def testHALDeviceVendorId(self):
        """Test of HALDevice.vendor_id.

        Many buses have a numerical vendor ID. Except for the special
        cases tested below, HWDevice.vendor_id returns the HAL property
        ${bus}.vendor_id.
        """
        devices = [
             {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    'pci.vendor_id': (self.PCI_VENDOR_ID_INTEL, 'int'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_vendor_id = parser.hal_devices[
            self.UDI_SATA_CONTROLLER].vendor_id
        self.assertEqual(found_vendor_id, self.PCI_VENDOR_ID_INTEL,
                         'Unexpected result of HWDevice.vendor_id. '
                         'Expected 0x8086, got 0x%x.'
                         % found_vendor_id)

    def testHALDeviceVendorIdScsi(self):
        """Test of HALDevice.vendor_id for SCSI devices.

        The SCSI specification does not know about a vendor ID,
        we use the vendor string as returned by INQUIRY command
        as the ID.
        """
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SCSI_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'scsi.vendor': ('SEAGATE', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_vendor_id = parser.hal_devices[self.UDI_SCSI_DISK].vendor_id
        self.assertEqual(found_vendor_id, 'SEAGATE',
                         'Unexpected result of HWDevice.vendor_id for a. '
                         'SCSI device. Expected SEAGATE, got %r.'
                         % found_vendor_id)

    def testHALDeviceVendorIdScsiAta(self):
        """Test of HALDevice.vendor_id for SCSI devices: fake IDE/SATA disks.
        """
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SCSI_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'scsi.vendor': ('ATA', 'str'),
                    'scsi.model': ('Hitachi HTS54161', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_vendor_id = parser.hal_devices[self.UDI_SCSI_DISK].vendor_id
        self.assertEqual(found_vendor_id, 'Hitachi',
                         'Unexpected result of HWDevice.vendor_id for a. '
                         'fake SCSI device. Expected Hitachi, got %r.'
                         % found_vendor_id)

    def testHALDeviceVendorIdSystem(self):
        """Test of HALDevice.vendor_id for the machine itself."""
        # HAL does not provide the property info.vendor_id for the
        # root UDI /org/freedesktop/Hal/devices/computer. We use
        # HALDevice.vendor instead.
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {
                    'info.bus': ('unknown', 'str'),
                    'system.hardware.vendor': ('FUJITSU SIEMENS', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_vendor_id = parser.hal_devices[self.UDI_COMPUTER].vendor_id
        self.assertEqual(found_vendor_id, 'FUJITSU SIEMENS',
                         'Unexpected result of HWDevice.vendor_id for a '
                         'system. Expected FUJITSU SIEMENS, got %r.'
                         % found_vendor_id)

    def testHALDeviceProductId(self):
        """Test of HALDevice.product_id.

        Many buses have a numerical product ID. Except for the special
        cases tested below, HWDevice.product_id returns the HAL property
        ${bus}.product_id.
        """
        devices = [
             {
                'id': 1,
                'udi': self.UDI_SATA_CONTROLLER,
                'properties': {
                    'info.bus': ('pci', 'str'),
                    'pci.product_id': (0x27c5, 'int'),
                    },
                },
             ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_product_id = parser.hal_devices[
            self.UDI_SATA_CONTROLLER].product_id
        self.assertEqual(found_product_id, 0x27c5,
                         'Unexpected result of HWDevice.product_id. '
                         'Expected 0x27c5, got 0x%x.'
                         % found_product_id)

    def testHALDeviceProductIdScsi(self):
        """Test of HALDevice.product_id for SCSI devices.

        The SCSI specification does not know about a product ID,
        we use the product string as returned by INQUIRY command
        as the ID.
        """
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SCSI_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'scsi.vendor': ('SEAGATE', 'str'),
                    'scsi.model': ('ST36530N', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_product_id = parser.hal_devices[self.UDI_SCSI_DISK].product_id
        self.assertEqual(found_product_id, 'ST36530N',
                         'Unexpected result of HWDevice.product_id for a. '
                         'SCSI device. Expected ST35630N, got %r.'
                         % found_product_id)

    def testHALDeviceProductIdScsiAta(self):
        """Test of HALDevice.product_id for SCSI devices: fake IDE/SATA disks.
        """
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SCSI_DISK,
                'properties': {
                    'info.bus': ('scsi', 'str'),
                    'scsi.vendor': ('ATA', 'str'),
                    'scsi.model': ('Hitachi HTS54161', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_product_id = parser.hal_devices[self.UDI_SCSI_DISK].product_id
        self.assertEqual(found_product_id, 'HTS54161',
                         'Unexpected result of HWDevice.product_id for a. '
                         'fake SCSI device. Expected HTS54161, got %r.'
                         % found_product_id)

    def testHALDeviceProductIdSystem(self):
        """Test of HALDevice.product_id for the machine itself."""
        # HAL does not provide info.product_id for the root UDI
        # /org/freedesktop/Hal/devices/computer. We use
        # HALDevice.product instead.
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {
                    'info.bus': ('unknown', 'str'),
                    'system.hardware.product': ('LIFEBOOK E8210', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_product_id = parser.hal_devices[self.UDI_COMPUTER].product_id
        self.assertEqual(found_product_id, 'LIFEBOOK E8210',
                         'Unexpected result of HWDevice.product_id for a '
                         'system. Expected LIFEBOOK E8210, got %r.'
                         % found_product_id)

    def testVendorIDForDB(self):
        """Test of HALDevice.vendor_id_for_db."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SATA_DISK,
                'properties': {},
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        properties = devices[0]['properties']
        parser = SubmissionParser(self.log)
        # SCSI vendor names have a length of exactly 8 bytes; we use
        # this format for HWDevice.bus_product_id too.
        testdata = (('pci', (0x123, 'int'), '0x0123'),
                    ('usb_device', (0x234, 'int'), '0x0234'),
                    ('scsi', ('SEAGATE', 'str'), 'SEAGATE '),
                    )
        for bus, vendor_id, expected_vendor_id in testdata:
            properties['info.bus'] = (bus, 'str')
            if bus == 'scsi':
                properties['%s.vendor' % bus] = vendor_id
            else:
                properties['%s.vendor_id' % bus] = vendor_id
            parser.buildDeviceList(parsed_data)
            found_vendor_id = parser.hal_devices[
                self.UDI_SATA_DISK].vendor_id_for_db
            self.assertEqual(found_vendor_id, expected_vendor_id,
                'Unexpected result of HWDevice.vendor_id_for_db for bus '
                '"%s". Expected %r, got %r.'
                % (bus, expected_vendor_id, found_vendor_id))

    def testVendorIDForDBSystem(self):
        """Test of HALDevice.vendor_id_for_db."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {
                    'system.hardware.vendor': ('FUJITSU SIEMENS', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_vendor_id = parser.hal_devices[
            self.UDI_COMPUTER].vendor_id_for_db
        self.assertEqual(found_vendor_id, 'FUJITSU SIEMENS',
            'Unexpected result of HWDevice.vendor_id_for_db for system. '
            'Expected FUJITSU SIEMENS, got %r.' % found_vendor_id)

    def testProductIDForDB(self):
        """Test of HALDevice.product_id_for_db."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_SATA_DISK,
                'properties': {},
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        properties = devices[0]['properties']
        parser = SubmissionParser(self.log)
        # SCSI product names (called "model" in the SCSI specifications)
        # have a length of exactly 16 bytes; we use this format for
        # HWDevice.bus_product_id too.
        testdata = (('pci', (0x123, 'int'), '0x0123'),
                    ('usb_device', (0x234, 'int'), '0x0234'),
                    ('scsi', ('ST1234567890', 'str'), 'ST1234567890    '),
                   )
        for bus, product_id, expected_product_id in testdata:
            properties['info.bus'] = (bus, 'str')
            if bus == 'scsi':
                properties['%s.model' % bus] = product_id
            else:
                properties['%s.product_id' % bus] = product_id
            parser.buildDeviceList(parsed_data)
            found_product_id = parser.hal_devices[
                self.UDI_SATA_DISK].product_id_for_db
            self.assertEqual(found_product_id, expected_product_id,
                'Unexpected result of HWDevice.product_id_for_db for bus '
                '"%s". Expected %r, got %r.'
                % (bus, expected_product_id, found_product_id))

    def testProductIDForDBSystem(self):
        """Test of HALDevice.product_id_for_db."""
        devices = [
            {
                'id': 1,
                'udi': self.UDI_COMPUTER,
                'properties': {
                    'system.hardware.product': ('E8210', 'str'),
                    },
                },
            ]
        parsed_data = {
            'hardware': {
                'hal': {
                    'devices': devices,
                    },
                },
            }
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(parsed_data)
        found_product_id = parser.hal_devices[
            self.UDI_COMPUTER].product_id_for_db
        self.assertEqual(found_product_id, 'E8210',
            'Unexpected result of HWDevice.product_id_for_db for system. '
            'Expected FUJITSU SIEMENS, got %r.' % found_product_id)


class TestHALDeviceUSBDevices(TestCaseHWDB):
    """Tests for HALDevice.is_real_device: USB devices."""

    def setUp(self):
        """Setup the test environment."""
        super(TestHALDeviceUSBDevices, self).setUp()
        self.usb_controller_pci_side = {
            'id': 1,
            'udi': self.UDI_USB_CONTROLLER_PCI_SIDE,
            'properties': {
                'info.bus': ('pci', 'str'),
                'pci.device_class': (PCI_CLASS_SERIALBUS_CONTROLLER, 'int'),
                'pci.device_subclass': (PCI_SUBCLASS_SERIALBUS_USB, 'int'),
                },
            }
        self.usb_controller_usb_side = {
            'id': 2,
            'udi': self.UDI_USB_CONTROLLER_USB_SIDE,
            'properties': {
                'info.parent': (self.UDI_USB_CONTROLLER_PCI_SIDE, 'str'),
                'info.bus': ('usb_device', 'str'),
                'usb_device.vendor_id': (0, 'int'),
                'usb_device.product_id': (0, 'int'),
                },
            }
        self.usb_storage_device = {
            'id': 3,
            'udi': self.UDI_USB_STORAGE,
            'properties': {
                'info.parent': (self.UDI_USB_CONTROLLER_USB_SIDE, 'str'),
                'info.bus': ('usb_device', 'str'),
                'usb_device.vendor_id': (self.USB_VENDOR_ID_USBEST, 'int'),
                'usb_device.product_id': (self.USB_PROD_ID_USBBEST_MEMSTICK,
                                          'int'),
                },
            }
        self.parsed_data = {
            'hardware': {
                'hal': {
                    'devices': [
                        self.usb_controller_pci_side,
                        self.usb_controller_usb_side,
                        self.usb_storage_device,
                        ],
                    },
                },
            }

    def testUSBDeviceRegularCase(self):
        """Test of HALDevice.is_real_device: info.bus == 'usb_device'."""
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(self.parsed_data)
        device = parser.hal_devices[self.UDI_USB_STORAGE]
        self.failUnless(device.is_real_device,
                        'Regular USB Device not treated as a real device.')

    def testUSBHostController(self):
        """Test of HALDevice.is_real_device: info.bus == 'usb_device'.

        Special case: vendor ID and product ID of the device are zero;
        the parent device is a PCI/USB host controller.
        """

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(self.parsed_data)
        device = parser.hal_devices[self.UDI_USB_CONTROLLER_USB_SIDE]
        self.failIf(device.is_real_device,
                    'USB Device with vendor/product ID 0:0 property '
                    'treated as a real device.')

    def testUSBHostControllerInvalidParentClass(self):
        """Test of HALDevice.is_real_device: info.bus == 'usb_device'.

        Special case: vendor ID and product ID of the device are zero;
        the parent device cannot be identified as a PCI/USB host
        controller: Wrong PCI device class of the parent device.
        """
        parent_properties = self.usb_controller_pci_side['properties']
        parent_properties['pci.device_class'] = (PCI_CLASS_STORAGE, 'int')
        parser = SubmissionParser(self.log)
        parser.submission_key = 'USB device test 1'
        parser.buildDeviceList(self.parsed_data)
        device = parser.hal_devices[self.UDI_USB_CONTROLLER_USB_SIDE]
        self.failIf(device.is_real_device,
                    'USB Device with vendor/product ID 0:0 property '
                    'treated as a real device.')
        self.assertWarningMessage(
            parser.submission_key,
            'USB device found with vendor ID==0, product ID==0, where the '
            'parent device does not look like a USB host controller: '
            + self.UDI_USB_CONTROLLER_USB_SIDE)

    def testUSBHostControllerInvalidParentSubClass(self):
        """Test of HALDevice.is_real_device: info.bus == 'usb_device'.

        Special case: vendor ID and product ID of the device are zero;
        the parent device cannot be identified as a PCI/USB host
        controller: Wrong PCI device subclass of the parent device.
        """
        parent_properties = self.usb_controller_pci_side['properties']
        parent_properties['pci.device_subclass'] = (1, 'int')
        parser = SubmissionParser(self.log)
        parser.submission_key = 'USB device test 2'
        parser.buildDeviceList(self.parsed_data)
        device = parser.hal_devices[self.UDI_USB_CONTROLLER_USB_SIDE]
        self.failIf(device.is_real_device,
                    'USB Device with vendor/product ID 0:0 property '
                    'treated as a real device.')
        self.assertWarningMessage(
            parser.submission_key,
            'USB device found with vendor ID==0, product ID==0, where the '
            'parent device does not look like a USB host controller: '
            +  self.UDI_USB_CONTROLLER_USB_SIDE)

    def testUSBHostControllerUnexpectedParentBus(self):
        """Test of HALDevice.is_real_device: info.bus == 'usb_device'.

        Special case: vendor ID and product ID of the device are zero;
        the parent device cannot be identified as a PCI/USB host
        controller: Wrong bus of the parent device.
        """
        parent_properties = self.usb_controller_pci_side['properties']
        parent_properties['info.bus'] = ('not pci', 'str')
        parser = SubmissionParser(self.log)
        parser.submission_key = 'USB device test 3'
        parser.buildDeviceList(self.parsed_data)
        device = parser.hal_devices[self.UDI_USB_CONTROLLER_USB_SIDE]
        self.failIf(device.is_real_device,
                    'USB Device with vendor/product ID 0:0 property '
                    'treated as a real device.')
        self.assertWarningMessage(
            parser.submission_key,
            'USB device found with vendor ID==0, product ID==0, where the '
            'parent device does not look like a USB host controller: '
            + self.UDI_USB_CONTROLLER_USB_SIDE)

        # All other devices which have an info.bus property return True
        # for HALDevice.is_real_device. The USB host controller in the
        # test data is an example.
        device = parser.hal_devices[self.UDI_USB_CONTROLLER_PCI_SIDE]
        self.failUnless(device.is_real_device,
                        'Device with existing info.bus property not treated '
                        'as a real device.')


class TestHWDBSubmissionTablePopulation(TestCaseHWDB):
    """Tests of the HWDB popoluation with submitted data."""

    layer = LaunchpadZopelessLayer

    HAL_COMPUTER = {
        'id': 1,
        'udi': TestCaseHWDB.UDI_COMPUTER,
        'properties': {
            'system.hardware.vendor': ('Lenovo', 'str'),
            'system.hardware.product': ('T41', 'str'),
            'system.kernel.version': (TestCaseHWDB.KERNEL_VERSION, 'str'),
            },
        }

    HAL_PCI_PCCARD_BRIDGE = {
        'id': 2,
        'udi': TestCaseHWDB.UDI_PCI_PCCARD_BRIDGE,
        'properties': {
            'info.bus': ('pci', 'str'),
            'info.linux.driver': ('yenta_cardbus', 'str'),
            'info.parent': (TestCaseHWDB.UDI_COMPUTER, 'str'),
            'info.product': ('OZ711MP1/MS1 MemoryCardBus Controller', 'str'),
            'pci.device_class': (PCI_CLASS_BRIDGE, 'int'),
            'pci.device_subclass': (PCI_SUBCLASS_BRIDGE_CARDBUS, 'int'),
            'pci.vendor_id': (TestCaseHWDB.PCI_VENDOR_ID_INTEL, 'int'),
            'pci.product_id': (TestCaseHWDB.PCI_PROD_ID_PCI_PCCARD_BRIDGE,
                               'int'),
            },
        }

    HAL_PCCARD_DEVICE = {
        'id': 3,
        'udi': TestCaseHWDB.UDI_PCCARD_DEVICE,
        'properties': {
            'info.bus': ('pci', 'str'),
            'info.parent': (TestCaseHWDB.UDI_PCI_PCCARD_BRIDGE, 'str'),
            'info.product': ('ISL3890/ISL3886', 'str'),
            'pci.device_class': (PCI_CLASS_SERIALBUS_CONTROLLER, 'int'),
            'pci.device_subclass': (PCI_SUBCLASS_SERIALBUS_USB, 'int'),
            'pci.vendor_id': (TestCaseHWDB.PCI_VENDOR_ID_INTEL, 'int'),
            'pci.product_id': (TestCaseHWDB.PCI_PROD_ID_PCCARD_DEVICE, 'int'),
            },
        }

    HAL_USB_CONTROLLER_PCI_SIDE = {
        'id': 4,
        'udi': TestCaseHWDB.UDI_USB_CONTROLLER_PCI_SIDE,
        'properties': {
            'info.bus': ('pci', 'str'),
            'info.linux.driver': ('ehci_hcd', 'str'),
            'info.parent': (TestCaseHWDB.UDI_COMPUTER, 'str'),
            'info.product': ('82801G (ICH7 Family) USB2 EHCI Controller',
                             'str'),
            'pci.device_class': (PCI_CLASS_SERIALBUS_CONTROLLER, 'int'),
            'pci.device_subclass': (PCI_SUBCLASS_SERIALBUS_USB, 'int'),
            'pci.vendor_id': (TestCaseHWDB.PCI_VENDOR_ID_INTEL, 'int'),
            'pci.product_id': (TestCaseHWDB.PCI_PROD_ID_USB_CONTROLLER,
                               'int'),
            },
        }

    HAL_USB_CONTROLLER_USB_SIDE = {
        'id': 5,
        'udi': TestCaseHWDB.UDI_USB_CONTROLLER_USB_SIDE,
        'properties': {
            'info.bus': ('usb_device', 'str'),
            'info.linux.driver': ('usb', 'str'),
            'info.parent': (TestCaseHWDB.UDI_USB_CONTROLLER_PCI_SIDE, 'str'),
            'info.product': ('EHCI Host Controller', 'str'),
            'usb_device.vendor_id': (0, 'int'),
            'usb_device.product_id': (0, 'int'),
            },
        }

    HAL_USB_STORAGE_DEVICE = {
        'id': 6,
        'udi': TestCaseHWDB.UDI_USB_STORAGE,
        'properties': {
            'info.bus': ('usb_device', 'str'),
            'info.linux.driver': ('usb', 'str'),
            'info.parent': (TestCaseHWDB.UDI_USB_CONTROLLER_USB_SIDE, 'str'),
            'info.product': ('USB Mass Storage Device', 'str'),
            'usb_device.vendor_id': (TestCaseHWDB.USB_VENDOR_ID_USBEST,
                                     'int'),
            'usb_device.product_id': (
                TestCaseHWDB.USB_PROD_ID_USBBEST_MEMSTICK, 'int'),
            },
        }

    parsed_data = {
        'hardware': {
            'hal': {},
            },
        'software': {
            'packages': {
                TestCaseHWDB.KERNEL_PACKAGE: {},
                },
            },
        }

    def setUp(self):
        """Setup the test environment."""
        self.log = logging.getLogger('test_hwdb_submission_parser')
        self.log.setLevel(logging.INFO)
        self.handler = Handler(self)
        self.handler.add(self.log.name)
        self.layer.switchDbUser('hwdb-submission-processor')

    def getLogData(self):
        messages = [record.getMessage() for record in self.handler.records]
        return '\n'.join(messages)

    def setHALDevices(self, devices):
        self.parsed_data['hardware']['hal']['devices'] = devices

    def testGetDriverNoDriverInfo(self):
        """Test of HALDevice.getDriver()."""
        devices = [
            self.HAL_COMPUTER,
            ]
        self.setHALDevices(devices)
        parser = SubmissionParser(self.log)
        parser.buildDeviceList(self.parsed_data)
        device = parser.hal_devices[self.UDI_COMPUTER]
        self.assertEqual(device.getDriver(), None,
            'HALDevice.getDriver found a driver where none is expected.')

    def testGetDriverWithDriverInfo(self):
        """Test of HALDevice.getDriver()."""
        devices = [
            self.HAL_COMPUTER,
            self.HAL_PCI_PCCARD_BRIDGE,
            ]
        self.setHALDevices(devices)
        parser = SubmissionParser(self.log)
        parser.parsed_data = self.parsed_data
        parser.buildDeviceList(self.parsed_data)
        device = parser.hal_devices[self.UDI_PCI_PCCARD_BRIDGE]
        driver = device.getDriver()
        self.assertNotEqual(driver, None,
            'HALDevice.getDriver did not find a driver where one '
            'is expected.')
        self.assertEqual(driver.name, 'yenta_cardbus',
            'Unexpected result for driver.name. Got %r, expected '
            'yenta_cardbus.' % driver.name)
        self.assertEqual(driver.package_name, self.KERNEL_PACKAGE,
            'Unexpected result for driver.package_name. Got %r, expected '
            'linux-image-2.6.24-19-generic' % driver.name)

    def testEnsureVendorIDVendorNameExistsRegularCase(self):
        """Test of ensureVendorIDVendorNameExists(self), regular case."""
        devices = [
            self.HAL_COMPUTER,
            ]
        self.setHALDevices(devices)
        parser = SubmissionParser(self.log)
        parser.parsed_data = self.parsed_data
        parser.buildDeviceList(self.parsed_data)

        # The database does not know yet about the vendor name
        # 'Lenovo'...
        vendor_name_set = getUtility(IHWVendorNameSet)
        vendor_name = vendor_name_set.getByName('Lenovo')
        self.assertEqual(vendor_name, None,
                         'Expected None looking up vendor name "Lenovo" in '
                         'HWVendorName, got %r.' % vendor_name)

        # ...as well as the vendor ID (which is identical to the vendor
        # name for systems).
        vendor_id_set = getUtility(IHWVendorIDSet)
        vendor_id = vendor_id_set.getByBusAndVendorID(HWBus.SYSTEM, 'Lenovo')
        self.assertEqual(vendor_id, None,
                         'Expected None looking up vendor ID "Lenovo" in '
                         'HWVendorID, got %r.' % vendor_id)

        # HALDevice.ensureVendorIDVendorNameExists() creates these
        # records.
        hal_system = parser.hal_devices[self.UDI_COMPUTER]
        hal_system.ensureVendorIDVendorNameExists()

        vendor_name = vendor_name_set.getByName('Lenovo')
        self.assertEqual(vendor_name.name, 'Lenovo',
                         'Expected to find vendor name "Lenovo" in '
                         'HWVendorName, got %r.' % vendor_name.name)

        vendor_id = vendor_id_set.getByBusAndVendorID(HWBus.SYSTEM, 'Lenovo')
        self.assertEqual(vendor_id.vendor_id_for_bus, 'Lenovo',
                         'Expected "Lenovo" as vendor_id_for_bus, '
                         'got %r.' % vendor_id.vendor_id_for_bus)
        self.assertEqual(vendor_id.bus, HWBus.SYSTEM,
                         'Expected HWBUS.SYSTEM as bus, got %s.'
                         % vendor_id.bus.title)

    def runTestEnsureVendorIDVendorNameExistsVendorNameUnknown(
        self, devices, test_bus, test_vendor_id, test_udi):
        """Test of ensureVendorIDVendorNameExists(self), special case.

        A HWVendorID record is not created by
        HALDevice.ensureVendorIDVendorNameExists for certain buses.
        """
        self.setHALDevices(devices)
        parser = SubmissionParser(self.log)
        parser.parsed_data = self.parsed_data
        parser.buildDeviceList(self.parsed_data)

        hal_device = parser.hal_devices[test_udi]
        hal_device.ensureVendorIDVendorNameExists()

        vendor_id_set = getUtility(IHWVendorIDSet)
        vendor_id = vendor_id_set.getByBusAndVendorID(
            test_bus, test_vendor_id)
        self.assertEqual(vendor_id, None,
            'Expected None looking up vendor ID %s for bus %s in HWVendorID, '
            'got %r.' % (test_vendor_id, test_bus.title, vendor_id))

    def testEnsureVendorIDVendorNameExistsVendorPCI(self):
        """Test of ensureVendorIDVendorNameExists(self), PCI bus."""
        devices = [
            self.HAL_COMPUTER,
            self.HAL_PCI_PCCARD_BRIDGE
            ]
        self.runTestEnsureVendorIDVendorNameExistsVendorNameUnknown(
            devices, HWBus.PCI, '0x8086', self.UDI_PCI_PCCARD_BRIDGE)

    def testEnsureVendorIDVendorNameExistsVendorPCCARD(self):
        """Test of ensureVendorIDVendorNameExists(self), PCCARD bus."""
        devices = [
            self.HAL_COMPUTER,
            self.HAL_PCI_PCCARD_BRIDGE,
            self.HAL_PCCARD_DEVICE,
            ]
        self.runTestEnsureVendorIDVendorNameExistsVendorNameUnknown(
            devices, HWBus.PCCARD, '0x8086', self.UDI_PCCARD_DEVICE)

    def testEnsureVendorIDVendorNameExistVendorUSB(self):
        """Test of ensureVendorIDVendorNameExists(self), USB bus."""
        devices = [
            self.HAL_COMPUTER,
            self.HAL_USB_CONTROLLER_PCI_SIDE,
            self.HAL_USB_CONTROLLER_USB_SIDE,
            self.HAL_USB_STORAGE_DEVICE,
            ]
        self.runTestEnsureVendorIDVendorNameExistsVendorNameUnknown(
            devices, HWBus.USB, '0x1307', self.UDI_USB_STORAGE)

    def testCreateDBDataForSimpleDevice(self):
        """Test of HALDevice.createDBData.

        Test for a HAL device without driver data.
        """
        devices = [
            self.HAL_COMPUTER,
            ]
        self.setHALDevices(devices)

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(self.parsed_data)

        submission_set = getUtility(IHWSubmissionSet)
        submission = submission_set.getBySubmissionKey('test_submission_id_1')

        hal_device = parser.hal_devices[self.UDI_COMPUTER]
        hal_device.createDBData(submission, None)

        # HALDevice.createDBData created a HWDevice record.
        vendor_id_set = getUtility(IHWVendorIDSet)
        vendor_id = vendor_id_set.getByBusAndVendorID(HWBus.SYSTEM, 'Lenovo')
        hw_device_set = getUtility(IHWDeviceSet)
        hw_device = hw_device_set.getByDeviceID(
            hal_device.real_bus, hal_device.vendor_id,
            hal_device.product_id)
        self.assertEqual(hw_device.bus_vendor, vendor_id,
            'Expected vendor ID (HWBus.SYSTEM, Lenovo) as the vendor ID, '
            'got %s %r' % (hw_device.bus_vendor.bus,
                           hw_device.bus_vendor.vendor_name.name))
        self.assertEqual(hw_device.bus_product_id, 'T41',
            'Expected product ID T41, got %r.' % hw_device.bus_product_id)
        self.assertEqual(hw_device.name, 'T41',
            'Expected device name T41, got %r.' % hw_device.name)

        # One HWDeviceDriverLink record is created...
        device_driver_link_set = getUtility(IHWDeviceDriverLinkSet)
        device_driver_link = device_driver_link_set.getByDeviceAndDriver(
            hw_device, None)
        self.assertEqual(device_driver_link.device, hw_device,
            'Expected HWDevice record for Lenovo T41 in HWDeviceDriverLink, '
            'got %s %r'
            % (device_driver_link.device.bus_vendor.bus,
               device_driver_link.device.bus_vendor.vendor_name.name))
        self.assertEqual(device_driver_link.driver, None,
            'Expected None as driver in HWDeviceDriverLink')

        # ...and one HWSubmissionDevice record linking the HWDeviceSriverLink
        # to the submission.
        submission_device_set = getUtility(IHWSubmissionDeviceSet)
        submission_devices = submission_device_set.getDevices(submission)
        self.assertEqual(len(list(submission_devices)), 1,
            'Unexpected number of submission devices: %i, expected 1.'
            % len(list(submission_devices)))
        submission_device = submission_devices[0]
        self.assertEqual(
            submission_device.device_driver_link, device_driver_link,
            'Invalid device_driver_link field in HWSubmissionDevice.')
        self.assertEqual(
            submission_device.parent, None,
            'Invalid parent field in HWSubmissionDevice.')
        self.assertEqual(
            submission_device.hal_device_id, 1,
            'Invalid haL-device_id field in HWSubmissionDevice.')

    def testCreateDBDataForDeviceWithOneDriver(self):
        """Test of HALDevice.createDBData.

        Test of a HAL device with one driver.
        """
        devices = [
            self.HAL_COMPUTER,
            self.HAL_PCI_PCCARD_BRIDGE,
            ]
        self.setHALDevices(devices)

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(self.parsed_data)
        parser.parsed_data = self.parsed_data

        submission_set = getUtility(IHWSubmissionSet)
        submission = submission_set.getBySubmissionKey('test_submission_id_1')

        hal_root_device = parser.hal_devices[self.UDI_COMPUTER]
        hal_root_device.createDBData(submission, None)

        # We now have a HWDevice record for the PCCard bridge...
        device_set = getUtility(IHWDeviceSet)
        pccard_bridge = device_set.getByDeviceID(
            HWBus.PCI, '0x%04x' % self.PCI_VENDOR_ID_INTEL,
            '0x%04x' % self.PCI_PROD_ID_PCI_PCCARD_BRIDGE)

        # ...and a HWDriver record for the yenta_cardbus driver.
        driver_set = getUtility(IHWDriverSet)
        yenta_driver = driver_set.getByPackageAndName(
            self.KERNEL_PACKAGE, 'yenta_cardbus')
        self.assertEqual(
            yenta_driver.name, 'yenta_cardbus',
            'Unexpected driver name: %r' % yenta_driver.name)
        self.assertEqual(
            yenta_driver.package_name, self.KERNEL_PACKAGE,
            'Unexpected package name: %r' % yenta_driver.package_name)

        # The PCCard bridge has one HWDeviceDriverLink record without
        # an associated driver...
        device_driver_link_set = getUtility(IHWDeviceDriverLinkSet)
        pccard_link_no_driver = device_driver_link_set.getByDeviceAndDriver(
            pccard_bridge, None)
        self.assertEqual(
            pccard_link_no_driver.device, pccard_bridge,
            'Unexpected value of pccard_link_no_driver.device')
        self.assertEqual(
            pccard_link_no_driver.driver, None,
            'Unexpected value of pccard_link_no_driver.driver')

        # ...and another one with the yenta driver.
        pccard_link_yenta = device_driver_link_set.getByDeviceAndDriver(
            pccard_bridge, yenta_driver)
        self.assertEqual(
            pccard_link_yenta.device, pccard_bridge,
            'Unexpected value of pccard_dd_link_yenta.device')
        self.assertEqual(
            pccard_link_yenta.driver, yenta_driver,
            'Unexpected value of pccard_dd_link_yenta.driver')

        # Finally, we have three HWSubmissionDevice records for this
        # submission: one for the computer itself, and two referring
        # to the HWDeviceDriverLink records for the PCCard bridge.

        submission_device_set = getUtility(IHWSubmissionDeviceSet)
        submission_devices = submission_device_set.getDevices(submission)
        (submitted_pccard_bridge_no_driver,
         submitted_pccard_bridge_yenta,
         submitted_system) = submission_devices

        self.assertEqual(
            submitted_pccard_bridge_no_driver.device_driver_link,
            pccard_link_no_driver,
            'Unexpected value of HWSubmissionDevice.device_driver_link for '
            'first submitted device')
        self.assertEqual(
            submitted_pccard_bridge_yenta.device_driver_link,
            pccard_link_yenta,
            'Unexpected value of HWSubmissionDevice.device_driver_link for '
            'second submitted device')

        # The parent field of the HWSubmisionDevice record represents
        # the device hiearchy.
        self.assertEqual(
            submitted_system.parent, None,
            'Unexpected value of HWSubmissionDevice.parent for the root '
            'node.')
        self.assertEqual(
            submitted_pccard_bridge_no_driver.parent, submitted_system,
            'Unexpected value of HWSubmissionDevice.parent for the '
            'PCCard bridge node without a driver.')
        self.assertEqual(
            submitted_pccard_bridge_yenta.parent,
            submitted_pccard_bridge_no_driver,
            'Unexpected value of HWSubmissionDevice.parent for the '
            'PCCard bridge node with the yenta driver.')

        # HWSubmissionDevice.hal_device_id stores the ID of the device
        # as defined in the submitted data.
        self.assertEqual(submitted_pccard_bridge_no_driver.hal_device_id, 2,
            'Unexpected value of HWSubmissionDevice.hal_device_id for the '
            'PCCard bridge node without a driver.')
        self.assertEqual(submitted_pccard_bridge_yenta.hal_device_id, 2,
            'Unexpected value of HWSubmissionDevice.hal_device_id for the '
            'PCCard bridge node with the yenta driver.')

    def testCreateDBDataForDeviceWithTwoDrivers(self):
        """Test of HALDevice.createDBData.

        Test for a HAL device with two drivers.
        """
        devices = [
            self.HAL_COMPUTER,
            self.HAL_USB_CONTROLLER_PCI_SIDE,
            self.HAL_USB_CONTROLLER_USB_SIDE
            ]
        self.setHALDevices(devices)

        parser = SubmissionParser(self.log)
        parser.buildDeviceList(self.parsed_data)
        parser.parsed_data = self.parsed_data

        submission_set = getUtility(IHWSubmissionSet)
        submission = submission_set.getBySubmissionKey('test_submission_id_1')

        hal_root_device = parser.hal_devices[self.UDI_COMPUTER]
        hal_root_device.createDBData(submission, None)

        # The USB controller has a HWDevice record.
        device_set = getUtility(IHWDeviceSet)
        usb_controller = device_set.getByDeviceID(
            HWBus.PCI, '0x%04x' % self.PCI_VENDOR_ID_INTEL,
            '0x%04x' % self.PCI_PROD_ID_USB_CONTROLLER)

        # HWDriver records for the ehci_hcd and the usb driver were
        # created...
        driver_set = getUtility(IHWDriverSet)
        ehci_hcd_driver = driver_set.getByPackageAndName(
            self.KERNEL_PACKAGE, 'ehci_hcd')
        usb_driver = driver_set.getByPackageAndName(
            self.KERNEL_PACKAGE, 'usb')

        # ...as well as HWDeviceDriverLink records.
        device_driver_link_set = getUtility(IHWDeviceDriverLinkSet)
        usb_ctrl_link_no_driver = device_driver_link_set.getByDeviceAndDriver(
            usb_controller, None)
        usb_ctrl_link_ehci_hcd = device_driver_link_set.getByDeviceAndDriver(
            usb_controller, ehci_hcd_driver)
        usb_ctrl_link_usb = device_driver_link_set.getByDeviceAndDriver(
            usb_controller, usb_driver)

        # Three HWDeviceDriverLink records exist for the USB controller.
        submission_device_set = getUtility(IHWSubmissionDeviceSet)
        submission_devices = submission_device_set.getDevices(submission)
        (submitted_usb_controller_no_driver,
         submitted_usb_controller_ehci_hcd,
         submitted_usb_controller_usb,
         submitted_system) = submission_devices

        # The first record is for the controller without a driver...
        self.assertEqual(
            submitted_usb_controller_no_driver.device_driver_link,
            usb_ctrl_link_no_driver,
            'Unexpected value for '
            'submitted_usb_controller_no_driver.device_driver_link')

        # ...the second record for the controller and the ehci_hcd
        # driver...
        self.assertEqual(
            submitted_usb_controller_ehci_hcd.device_driver_link,
            usb_ctrl_link_ehci_hcd,
            'Unexpected value for '
            'submitted_usb_controller_ehci_hcd.device_driver_link')

        # ...and the third record is for the controller and the usb
        # driver.
        self.assertEqual(
            submitted_usb_controller_usb.device_driver_link,
            usb_ctrl_link_usb,
            'Unexpected value for '
            'submitted_usb_controller_usb.device_driver_link')

        # The first and second HWSubmissionDevice record are related to
        # the submitted HAL device node with the ID 4...
        self.assertEqual(
            submitted_usb_controller_no_driver.hal_device_id, 4,
            'Unexpected value for '
            'submitted_usb_controller_no_driver.hal_device_id')
        self.assertEqual(
            submitted_usb_controller_ehci_hcd.hal_device_id, 4,
            'Unexpected value for '
            'submitted_usb_controller_ehci_hcd.hal_device_id')

        # ...and the third HWSubmissionDevice record is related to
        # the submitted HAL device node with the ID 5.
        self.assertEqual(
            submitted_usb_controller_usb.hal_device_id, 5,
            'Unexpected value for '
            'submitted_usb_controller_usb.hal_device_id')

    def createSubmissionData(self, data, compress, submission_key):
        """Create a submission."""
        if compress:
            data = bz2.compress(data)
        self.layer.switchDbUser('launchpad')
        submission = getUtility(IHWSubmissionSet).createSubmission(
            date_created=datetime(2007, 9, 9, tzinfo=pytz.timezone('UTC')),
            format=HWSubmissionFormat.VERSION_1,
            private=False,
            contactable=False,
            submission_key=submission_key,
            emailaddress=u'test@canonical.com',
            distroarchseries=None,
            raw_submission=StringIO(data),
            filename='hwinfo.xml',
            filesize=len(data),
            system_fingerprint='A Machine Name')
        # We want to access library file later: ensure that it is
        # properly stored.
        self.layer.txn.commit()
        self.layer.switchDbUser('hwdb-submission-processor')
        return submission

    def getSampleData(self, filename):
        """Return the submission data of a short valid submission."""
        sample_data_path = os.path.join(
            config.root, 'lib', 'canonical', 'launchpad', 'scripts',
            'tests', 'simple_valid_hwdb_submission.xml')
        return open(sample_data_path).read()

    def assertSampleDeviceCreated(
        self, bus, vendor_id, product_id, driver_name, submission):
        """Assert that data for the device exists in HWDB tables."""
        device_set = getUtility(IHWDeviceSet)
        device = getUtility(IHWDeviceSet).getByDeviceID(
            bus, vendor_id, product_id)
        self.assertNotEqual(
            device, None,
            'No entry in HWDevice found for bus %s, vendor %s, product %s'
            % (bus, vendor_id, product_id))
        # We have one device_driver_link entry without a driver for
        # each device...
        device_driver_link_set = getUtility(IHWDeviceDriverLinkSet)
        device_driver_link = device_driver_link_set.getByDeviceAndDriver(
            device, None)
        self.assertNotEqual(
            device_driver_link, None,
            'No driverless entry in HWDeviceDriverLink for bus %s, '
            'vendor %s, product %s'
            % (bus, vendor_id, product_id))
        #...and an associated HWSubmissionDevice record.
        submission_devices = getUtility(IHWSubmissionDeviceSet).getDevices(
            submission)
        device_driver_links_in_submission = [
            submission_device.device_driver_link
            for submission_device in submission_devices]
        self.failUnless(
            device_driver_link in device_driver_links_in_submission,
            'No entry in HWSubmissionDevice for bus %s, '
            'vendor %s, product %s, submission %s'
            % (bus, vendor_id, product_id, submission.submission_key))
        # If the submitted data mentioned a driver for this device,
        # we have also a HWDeviceDriverLink record for the (device,
        # driver) tuple.
        if driver_name is not None:
            driver = getUtility(IHWDriverSet).getByPackageAndName(
                self.KERNEL_PACKAGE, driver_name)
            self.assertNotEqual(
                driver, None,
                'No HWDriver record found for package %s, driver %s'
                % (self.KERNEL_PACKAGE, driver_name))
            device_driver_link = device_driver_link_set.getByDeviceAndDriver(
                device, driver)
            self.assertNotEqual(
                device_driver_link, None,
                'No entry in HWDeviceDriverLink for bus %s, '
                'vendor %s, product %s, driver %s'
                % (bus, vendor_id, product_id, driver_name))
            self.failUnless(
                device_driver_link in device_driver_links_in_submission,
                'No entry in HWSubmissionDevice for bus %s, '
                'vendor %s, product %s, driver %s, submission %s'
                % (bus, vendor_id, product_id, driver_name,
                   submission.submission_key))

    def assertAllSampleDevicesCreated(self, submission):
        """Assert that the devices from the sample submission are processed.

        The test data contains two devices: A system and a PCI device.
        The system has no associated drivers; the PCI device is
        associated with the ahci driver.
        """
        for bus, vendor_id, product_id, driver in (
            (HWBus.SYSTEM, 'FUJITSU SIEMENS', 'LIFEBOOK E8210', None),
            (HWBus.PCI, '0x8086', '0x27c5', 'ahci'),
            ):
            self.assertSampleDeviceCreated(
                bus, vendor_id, product_id, driver, submission)

    def testProcessSubmissionValidData(self):
        """Test of SubmissionParser.processSubmission().

        Regular case: Process valid compressed submission data.
        """
        submission_key = 'submission-1'
        submission_data = self.getSampleData(
            'simple_valid_hwdb_submission.xml')
        submission = self.createSubmissionData(
            submission_data, False, submission_key)
        parser = SubmissionParser(self.log)
        result = parser.processSubmission(submission)
        self.failUnless(result,
                        'Simple valid uncompressed submission could not be '
                        'processed. Logged errors:\n%s'
                        % self.getLogData())
        self.assertAllSampleDevicesCreated(submission)

    def testProcessSubmissionValidBzip2CompressedData(self):
        """Test of SubmissionParser.processSubmission().

        Regular case: Process valid compressed submission data.
        """
        submission_key = 'submission-2'
        submission_data = self.getSampleData(
            'simple_valid_hwdb_submission.xml')
        submission = self.createSubmissionData(
            submission_data, True, submission_key)
        parser = SubmissionParser(self.log)
        result = parser.processSubmission(submission)
        self.failUnless(result,
                        'Simple valid compressed submission could not be '
                        'processed. Logged errors:\n%s'
                        % self.getLogData())
        self.assertAllSampleDevicesCreated(submission)

    def testProcessSubmissionInvalidData(self):
        """Test of SubmissionParser.processSubmission().

        If a submission contains formally invalid data, it is rejected.
        """
        submission_key = 'submission-3'
        submission_data = """<?xml version="1.0" ?>
        <foo>
           This does not pass the RelaxNG validation.
        </foo>
        """
        submission = self.createSubmissionData(
            submission_data, True, submission_key)
        parser = SubmissionParser(self.log)
        result = parser.processSubmission(submission)
        self.failIf(result, 'Formally invalid submission treated as valid.')

    def testProcessSubmissionInconsistentData(self):
        """Test of SubmissionParser.processSubmission().

        If a submission contains inconsistent data, it is rejected.
        """
        submission_key = 'submission-4'
        submission_data = self.getSampleData(
            'simple_valid_hwdb_submission.xml')

        # The property "info.parent" of a HAL device node must
        # reference another existing device.
        submission_data = submission_data.replace(
            """<property name="info.parent" type="str">
          /org/freedesktop/Hal/devices/computer
        </property>""",
            """<property name="info.parent" type="str">
          /nonsense/udi
        </property>""")

        submission = self.createSubmissionData(
            submission_data, True, submission_key)
        parser = SubmissionParser(self.log)
        result = parser.processSubmission(submission)
        self.failIf(
            result, 'Submission with inconsistent data treated as valid.')

    def testProcessSubmissionRealData(self):
        """Test of SubmissionParser.processSubmission().

        Test with data from a real submission.
        """
        submission_data = self.getSampleData('real_hwdb_submission.xml.bz2')
        submission_key = 'submission-5'
        submission = self.createSubmissionData(
            submission_data, False, submission_key)
        parser = SubmissionParser(self.log)
        result = parser.processSubmission(submission)
        self.failUnless(
            result,
            'Real submission data not processed. Logged errors:\n%s'
            % self.getLogData())

    def testPendingSubmissionProcessing(self):
        """Test of process_pending_submissions().

        Run process_pending_submissions with three submissions; one
        of the submisisons contains invalid data.
        """
        # We have already one submisson in the DB sample data;
        # let's fill the associated Librarian file with some
        # test data.
        submission_set = getUtility(IHWSubmissionSet)
        submission = submission_set.getBySubmissionKey(
            'test_submission_id_1')
        submission_data = self.getSampleData(
            'simple_valid_hwdb_submission.xml')
        fillLibrarianFile(submission.raw_submission.id, submission_data)

        submission_data = self.getSampleData('real_hwdb_submission.xml.bz2')
        submission_key = 'submission-6'
        self.createSubmissionData(submission_data, False, submission_key)

        submission_key = 'submission-7'
        submission_data = """<?xml version="1.0" ?>
        <foo>
           This does not pass the RelaxNG validation.
        </foo>
        """
        self.createSubmissionData(submission_data, False, submission_key)
        process_pending_submissions(self.layer.txn, self.log)

        valid_submissions = submission_set.getByStatus(
            HWSubmissionProcessingStatus.PROCESSED)
        valid_submission_keys = [
            submission.submission_key for submission in valid_submissions]
        self.assertEqual(
            valid_submission_keys,
            [u'test_submission_id_1', u'submission-6'],
            'Unexpected set of valid submissions: %r' % valid_submission_keys)

        invalid_submissions = submission_set.getByStatus(
            HWSubmissionProcessingStatus.INVALID)
        invalid_submission_keys = [
            submission.submission_key for submission in invalid_submissions]
        self.assertEqual(
            invalid_submission_keys, [u'submission-7'],
            'Unexpected set of invalid submissions: %r'
            % invalid_submission_keys)

        new_submissions = submission_set.getByStatus(
            HWSubmissionProcessingStatus.SUBMITTED)
        new_submission_keys = [
            submission.submission_key for submission in new_submissions]
        self.assertEqual(
            new_submission_keys, [],
            'Unexpected set of new submissions: %r' % new_submission_keys)

        messages = [record.getMessage() for record in self.handler.records]
        messages = '\n'.join(messages)
        self.assertEqual(
            messages,
            "Parsing submission submission-7: root node is not '<system>'\n"
            "Processed 2 valid and 1 invalid HWDB submissions",
            'Unexpected log messages: %r' % messages)

    def testOopsLogging(self):
        """Test if OOPSes are properly logged."""
        def processSubmission(self, submission):
            x = 1
            x = x / 0
        process_submission_regular = SubmissionParser.processSubmission
        SubmissionParser.processSubmission = processSubmission

        process_pending_submissions(self.layer.txn, self.log)

        error_utility = ErrorReportingUtility()
        error_report = error_utility.getLastOopsReport()
        fp = StringIO()
        error_report.write(fp)
        error_text = fp.getvalue()
        self.failUnless(
            error_text.find('Exception-Type: ZeroDivisionError') >= 0,
            'Expected Exception type not found in OOPS report:\n%s'
            % error_text)

        expected_explanation = (
            'error-explanation=Exception while processing HWDB '
            'submission test_submission_id_1')
        self.failUnless(
            error_text.find(expected_explanation) >= 0,
            'Expected Exception type not found in OOPS report:\n%s'
            % error_text)

        messages = [record.getMessage() for record in self.handler.records]
        messages = '\n'.join(messages)
        expected_message = (
            'Exception while processing HWDB submission '
            'test_submission_id_1 (OOPS-')
        self.failUnless(
                messages.startswith(expected_message),
                'Unexpected log message: %r' % messages)

        SubmissionParser.processSubmission = process_submission_regular

def test_suite():
    return TestLoader().loadTestsFromName(__name__)
