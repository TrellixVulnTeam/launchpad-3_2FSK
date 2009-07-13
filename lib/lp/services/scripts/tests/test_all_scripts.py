# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Check the integrity of the /scripts and /cronscripts."""

__metaclass__ = type
__all__ = []

import os
import unittest

from lp.services.scripts.tests import find_lp_scripts
from lp.testing import (
    run_script, TestCase)


class ScriptsTestCase(TestCase):

    def test_scripts(self):
        for script_path in find_lp_scripts():
            cmd_line = script_path + " -h"
            out, err, returncode = run_script(cmd_line)
            self.assertEquals(
                os.EX_OK, returncode, "%s failed\n%s" % (script_path, err))


def test_suite():
    return unittest.TestLoader().loadTestsFromName(__name__)
