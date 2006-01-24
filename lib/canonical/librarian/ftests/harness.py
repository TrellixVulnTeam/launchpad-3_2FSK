# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import os, os.path, shutil
from canonical.config import config
import canonical

from canonical.launchpad.daemons.tachandler import TacTestSetup

class LibrarianTestSetup(TacTestSetup):
    r"""Set up a librarian for use by functional tests.
    
    >>> from urllib import urlopen
    >>> from canonical.config import config
    >>> host = config.librarian.download_host
    >>> port = config.librarian.download_port

    >>> LibrarianTestSetup().setUp()

    Set a socket timeout, so that this test cannot hang indefinitely.
    
    >>> import socket
    >>> print socket.getdefaulttimeout()
    None
    >>> socket.setdefaulttimeout(1)
    
    Make sure the server is running.

    >>> 'Copyright' in urlopen('http://%s:%d/' % (host, port)).read()
    True

    >>> LibrarianTestSetup().tearDown()

    Make sure it is not running
    >>> urlopen('http://%s:%d/' % (host, port))
    Traceback (most recent call last):
    ...
    IOError: ...
    
    And again for luck.

    >>> LibrarianTestSetup().setUp()
    >>> 'Copyright' in urlopen('http://%s:%d/' % (host, port)).read()
    True

    Tidy up.
    
    >>> LibrarianTestSetup().tearDown()
    >>> socket.setdefaulttimeout(None)

    """
    def setUpRoot(self):
        if os.path.isdir(self.root):
            shutil.rmtree(self.root)
        os.makedirs(self.root, 0700)

    @property
    def root(self):
        return config.librarian.server.root

    @property
    def tacfile(self):
        return os.path.abspath(os.path.join(
            os.path.dirname(canonical.__file__), os.pardir, os.pardir,
            'daemons/librarian.tac'
            ))

    @property
    def pidfile(self):
        return os.path.join(self.root, 'librarian.pid')

    @property
    def logfile(self):
        return os.path.join(self.root, 'librarian.log')

# Kill any librarian left lying around from a previous interrupted run.
# Be paranoid since we trash the librarian directory as part of this.
assert config.default_section == 'testrunner', \
        'Imported dangerous test harness outside of the test runner'
LibrarianTestSetup().killTac()
