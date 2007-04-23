# Copyright 2007 Canonical Ltd.  All rights reserved.

# This is a bin/withlist script for testing that Mailman can import and access
# the common libmailman package.  It works by side effect; on success it exits
# with a return code of 99, which would be difficult to false positive, but
# very easy to check by the parent process.  See test-monkeypatch.txt for
# details.
#
# This script must be called like so:
#
# bin/withlist -r canonical.mailman.tests.withlist_2.can_import_libmailman

import sys

def can_import_libmailman(mlist):
    try:
        import libmailman
    except ImportError:
        sys.exit(1)
    else:
        sys.exit(99)
