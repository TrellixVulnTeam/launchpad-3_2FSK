#!/usr/bin/python2.4
##############################################################################
#
# Copyright (c) 2004 Zope Corporation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Test script

$Id: test.py 25177 2004-06-02 13:17:31Z jim $
"""
import sys, os, psycopg, time, logging, warnings, re

os.setpgrp() # So test_on_merge.py can reap its children

# Make tests run in a timezone no launchpad developers live in.
# Our tests need to run in any timezone.
# (No longer actually required, as PQM does this)
os.environ['TZ'] = 'Asia/Calcutta'
time.tzset()

here = os.path.dirname(os.path.realpath(__file__))
sys.path.insert(0, os.path.join(here, 'lib'))

# Set PYTHONPATH environment variable for spawned processes
os.environ['PYTHONPATH'] = ':'.join(sys.path)

# Set a flag if this is the main testrunner process
if len(sys.argv) > 1 and sys.argv[1] == '--resume-layer':
    main_process = False
else:
    main_process = True

# Install the import fascist import hook and atexit handler.
import importfascist
importfascist.install_import_fascist()

# Install the warning handler hook and atexit handler.
import warninghandler
warninghandler.install_warning_handler()

# Ensure overrides are generated
from configs import generate_overrides
generate_overrides()

# Tell canonical.config to use the test config section in launchpad.conf
from canonical.config import config
config.setDefaultSection('testrunner')

# Initialize testsuite profiling information
from canonical.testing.layers import setup_profiling
if main_process:
    setup_profiling()

# Remove this module's directory from path, so that zope.testbrowser
# can import pystone from test:
sys.path[:] = [p for p in sys.path if os.path.abspath(p) != here]


# Turn on psycopg debugging wrapper
#import canonical.database.debug
#canonical.database.debug.install()

# Unset the http_proxy environment variable, because we're going to make
# requests to localhost and we don't wand this to be proxied.
try:
    os.environ.pop('http_proxy')
except KeyError:
    pass

# Silence spurious warnings. Note that this does not propagate to subprocesses
# so this is not always as easy as it seems. Warnings caused by our code that
# need to be silenced should have an accomponied Bug reference.
#
warnings.filterwarnings(
        'ignore', 'PyCrypto', RuntimeWarning, 'twisted[.]conch[.]ssh'
        )
warnings.filterwarnings(
        'ignore', 'twisted.python.plugin', DeprecationWarning, 'buildbot'
        )
warnings.filterwarnings(
        'ignore', 'The concrete concept of a view has been deprecated.',
        DeprecationWarning
        )
warnings.filterwarnings(
        'ignore', 'bzrlib.*was deprecated', DeprecationWarning
        )

# This warning will be triggered if the beforeTraversal hook fails. We
# want to ensure it is not raised as an error, as this will mask the real
# problem.
warnings.filterwarnings(
        'always',
        re.escape('clear_request_started() called outside of a request'),
        UserWarning
        )

# Any warnings not explicitly silenced are errors
warnings.filterwarnings('error', append=True)


from canonical.ftests import pgsql
# If this is removed, make sure canonical.ftests.pgsql is updated
# because the test harness there relies on the Connection wrapper being
# installed.
pgsql.installFakeConnect()

from zope.testing import testrunner

defaults = [
    # Find tests in the tests and ftests directories
    '--tests-pattern=^f?tests$',
    '--test-path=%s' % os.path.join(here, 'lib'),
    '--package=canonical',
    ]

if __name__ == '__main__':

    # Extract so we can see them too
    options = testrunner.get_options(args=None, defaults=defaults)

    result = testrunner.run(defaults)
    # Cribbed from sourcecode/zope/test.py - avoid spurious error during exit.
    logging.disable(999999999)

    if main_process and options.verbose >= 3:
        from canonical.testing.layers import report_profile_stats
        report_profile_stats()
    sys.exit(result)

