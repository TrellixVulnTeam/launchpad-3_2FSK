# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests and pagetests.
"""

import os

from canonical.launchpad.testing.systemdocs import (
    LayeredDocFileSuite,
    setUp,
    tearDown,
    )
from canonical.testing import LaunchpadZopelessLayer
from lp.services.testing import build_test_suite


here = os.path.dirname(os.path.realpath(__file__))

special = {
    'script-monitoring.txt': LayeredDocFileSuite(
            '../doc/script-monitoring.txt',
            setUp=setUp, tearDown=tearDown,
            layer=LaunchpadZopelessLayer
            ),
}

def test_suite():
    return build_test_suite(here, special)
