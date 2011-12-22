# Copyright 2010-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""
Run the doctests and pagetests.
"""

import os

from lp.testing.systemdocs import (
    LayeredDocFileSuite,
    setUp,
    tearDown,
    )
from canonical.testing.layers import LaunchpadFunctionalLayer
from lp.services.testing import build_test_suite


here = os.path.dirname(os.path.realpath(__file__))

special = {
    'image-widget.txt': LayeredDocFileSuite(
        '../doc/image-widget.txt',
        setUp=setUp, tearDown=tearDown,
        layer=LaunchpadFunctionalLayer,
        ),
    }


def test_suite():
    return build_test_suite(here, special)
