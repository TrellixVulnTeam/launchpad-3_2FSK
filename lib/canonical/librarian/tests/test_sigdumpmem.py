# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test the SIGDUMPMEM signal handler."""

__metaclass__ = type

import os
import time

from canonical.librarian.interfaces import DUMP_FILE, SIGDUMPMEM
from canonical.librarian.testing.server import TacLibrarianTestSetup
from canonical.testing.layers import LibrarianLayer
from lp.testing import TestCase


class SIGDUMPMEMTestCase(TestCase):
    layer = LibrarianLayer

    def test_sigdumpmem(self):
        # Remove the dump file, if one exists.
        if os.path.exists(DUMP_FILE):
            os.unlink(DUMP_FILE)
        self.assertFalse(os.path.exists(DUMP_FILE))

        # We rely on the fact that the librarian was started by the test
        # runner here as we use the LibrarianLayer.
        pid = int(open(TacLibrarianTestSetup().pidfile).read())

        # Send the signal and ensure the dump file is created.
        os.kill(pid, SIGDUMPMEM)
        timeout = 5
        start_time = time.time()
        while time.time() < start_time + timeout:
            if os.path.exists(DUMP_FILE):
                break
        self.assertTrue(os.path.exists(DUMP_FILE))
