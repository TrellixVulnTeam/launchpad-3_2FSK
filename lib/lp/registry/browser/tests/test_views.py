# Copyright 2009 Canonical Ltd.  All rights reserved.
"""
Run the view tests.
"""

import logging
import os
import unittest

from canonical.launchpad.testing.systemdocs import (
    LayeredDocFileSuite, setUp, tearDown)
from canonical.testing import (
    DatabaseFunctionalLayer, LaunchpadFunctionalLayer)


here = os.path.dirname(os.path.realpath(__file__))

special_test_layer = {
    'milestone-views.txt': LaunchpadFunctionalLayer,
    'person-views.txt': LaunchpadFunctionalLayer,
    'user-to-user-views.txt': LaunchpadFunctionalLayer,
}


def test_suite():
    suite = unittest.TestSuite()
    testsdir = os.path.abspath(here)

    # Add tests using default setup/teardown
    filenames = [filename
                 for filename in os.listdir(testsdir)
                 if filename.endswith('.txt')]
    # Sort the list to give a predictable order.
    filenames.sort()
    for filename in filenames:
        path = filename
        if path in special_test_layer:
            layer = special_test_layer[path]
        else:
            layer = DatabaseFunctionalLayer
        one_test = LayeredDocFileSuite(
            path, setUp=setUp, tearDown=tearDown, layer=layer,
            stdout_logging_level=logging.WARNING
            )
        suite.addTest(one_test)

    return suite
