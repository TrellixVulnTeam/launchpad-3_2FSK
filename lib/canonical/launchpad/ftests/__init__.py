import os

import canonical.launchpad
from canonical.launchpad.ftests._launchpadformharness import (
    LaunchpadFormHarness)
from canonical.launchpad.ftests._login import *
from canonical.launchpad.ftests._sqlobject import syncUpdate
from canonical.launchpad.ftests._tales import test_tales
from canonical.launchpad.ftests.keys_for_tests import (
    import_public_test_keys, import_public_key, import_secret_test_key,
    decrypt_content)


def set_gotchi_and_emblem(browser):
    """Set the gotchi and emblem fields on the given browser instance."""
    icon = os.path.join(
      os.path.dirname(canonical.launchpad.__file__),
      'pagetests/standalone/big.png')
    browser.getControl(name='field.gotchi.action').value = ['change']
    browser.getControl(name='field.gotchi.image').add_file(
      open(icon), 'image/png', 'icon.png')
    emblem = os.path.join(
      os.path.dirname(canonical.launchpad.__file__),
      'pagetests/standalone/mypng.png')
    browser.getControl(name='field.emblem.action').value = ['change']
    browser.getControl(name='field.emblem.image').add_file(
      open(emblem), 'image/png', 'emblem.png')


