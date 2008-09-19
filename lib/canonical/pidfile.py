# Copyright 2004-2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import tempfile
import os
import atexit
import sys
from signal import signal, SIGTERM

from canonical.config import config

def pidfile_path(service_name, use_config=None):
    """Return the full pidfile path for the given service

    >>> pidfile_path('nuts') == '/var/tmp/%s-nuts.pid' % config.instance_name
    True

    You can pass in your own config instance to use.

    >>> class MyConfig:
    ...     class canonical:
    ...         pid_dir = '/var/tmp'
    ...     instance_name = 'blah'
    >>> pidfile_path('beans', MyConfig)
    '/var/tmp/blah-beans.pid'
    """
    if use_config is None:
        use_config = config
    return os.path.join(use_config.canonical.pid_dir, '%s-%s.pid' % (
        use_config.instance_name, service_name
        ))


def make_pidfile(service_name):
    """Write the current process id to a PID file.

    Also installs an atexit handler to remove the file on process termination.

    Also installs a SIGTERM signal handler to remove the file on SIGTERM.
    If you install your own handler, you will want to call remove_pidfile
    inside it.

    To test, we run a subprocess that creates a pidfile and checks
    that the correct PID is stored in it.

    >>> cmd = '''
    ... import os.path, sys
    ... from canonical.pidfile import make_pidfile, pidfile_path
    ... make_pidfile('nuts')
    ... sys.exit(
    ...     int(open(pidfile_path('nuts')).read().strip() == str(os.getpid()))
    ...     )
    ... '''
    >>> import sys, subprocess
    >>> cmd = '%s -c "%s"' % (sys.executable, cmd)
    >>> subprocess.call(cmd, shell=True)
    1

    Make sure that the process has been removed.

    >>> os.path.exists(pidfile_path('nuts'))
    False

    And we want the pidfile to be removed if the process is exited with
    Ctrl-C or SIGTERM, too.

    >>> from signal import SIGINT, SIGTERM
    >>> import time
    >>> for signal in [SIGINT, SIGTERM]:
    ...     cmd = '''
    ... from canonical.pidfile import make_pidfile
    ... import time
    ... make_pidfile('nuts')
    ... try:
    ...     time.sleep(30)
    ... except KeyboardInterrupt:
    ...     pass'''
    ...     cmd = '%s -c "%s"' % (sys.executable, cmd)
    ...     p = subprocess.Popen(cmd, shell=True)
    ...     count = 0
    ...     while not os.path.exists(pidfile_path('nuts')) and count < 100:
    ...         time.sleep(0.1)
    ...         count += 1
    ...     os.kill(int(open(pidfile_path('nuts')).read()), SIGINT)
    ...     time.sleep(2)
    ...     print os.path.exists(pidfile_path('nuts'))
    False
    False

    """
    pidfile = pidfile_path(service_name)
    if os.path.exists(pidfile):
        raise RuntimeError("PID file %s already exists. Already running?" %
                pidfile)

    atexit.register(remove_pidfile, service_name)
    def remove_pidfile_handler(*ignored):
        sys.exit(-1 * SIGTERM)
    signal(SIGTERM, remove_pidfile_handler)

    fd, tempname = tempfile.mkstemp(dir=os.path.dirname(pidfile))
    outf = os.fdopen(fd, 'w')
    outf.write(str(os.getpid())+'\n')
    outf.flush()
    outf.close()
    os.rename(tempname, pidfile)


def remove_pidfile(service_name, use_config=None):
    """Remove the PID file.

    This should only be needed if you are overriding the default SIGTERM
    signal handler.

    >>> path = pidfile_path('legumes')
    >>> file = open(path, 'w')
    >>> try:
    ...     print >> file, os.getpid()
    ... finally:
    ...     file.close()
    >>> remove_pidfile('legumes')
    >>> os.path.exists(path)
    False

    You can also pass in your own config instance, in which case the pid does
    not need to match the current process's pid.

    >>> class MyConfig:
    ...     class canonical:
    ...         pid_dir = '/var/tmp'
    ...     instance_name = 'blah'
    >>> path = pidfile_path('pits', MyConfig)

    >>> file = open(path, 'w')
    >>> try:
    ...     print >> file, os.getpid() + 1
    ... finally:
    ...     file.close()
    >>> remove_pidfile('pits', MyConfig)
    >>> os.path.exists(path)
    False
    """
    pidfile = pidfile_path(service_name, use_config)
    pid = get_pid(service_name, use_config)
    if pid is None:
        return
    if use_config is not None or pid == os.getpid():
        os.unlink(pidfile)


def get_pid(service_name, use_config=None):
    """Return the PID for the given service as an integer, or None

    May raise a ValueError if the PID file is corrupt.

    This method will only be needed by service or monitoring scripts.

    Currently no checking is done to ensure that the process is actually
    running, is healthy, or died horribly a while ago and its PID being
    used by something else. What we have is probably good enough.

    We make the pidfile in a separate process so as to cleanly keep the atexit
    and signal handler code out of the test environment.)

    >>> get_pid('nuts') is None
    True

    >>> import sys, subprocess, os, time, signal
    >>> cmd = '''
    ... import time
    ... from canonical.pidfile import make_pidfile
    ... make_pidfile('nuts')
    ... try:
    ...     time.sleep(30)
    ... except KeyboardInterrupt:
    ...     pass'''
    ...
    >>> cmd = '%s -c "%s"' % (sys.executable, cmd)
    >>> p = subprocess.Popen(cmd, shell=True)
    >>> for i in range(100):
    ...     if os.path.exists(pidfile_path('nuts')):
    ...         break
    ...     time.sleep(0.1)
    ... else:
    ...     print 'Error: pid file was not created'
    ...
    >>> pid = int(open(pidfile_path('nuts')).read())

    >>> get_pid('nuts') == pid
    True
    >>> os.kill(pid, signal.SIGINT)
    >>> for i in range(20):
    ...     if not os.path.exists(pidfile_path('nuts')):
    ...         break
    ...     time.sleep(0.1)
    ... else:
    ...     print 'Error: pid file was not removed'
    ...
    >>> get_pid('nuts') is None
    True

    You can also pass in your own config instance.

    >>> class MyConfig:
    ...     class canonical:
    ...         pid_dir = '/var/tmp'
    ...     instance_name = 'blah'
    >>> path = pidfile_path('beans', MyConfig)
    >>> path
    '/var/tmp/blah-beans.pid'
    >>> file = open(path, 'w')
    >>> try:
    ...     print >> file, 72
    ... finally:
    ...     file.close()
    >>> get_pid('beans', MyConfig)
    72
    >>> os.remove(path)
    """
    pidfile = pidfile_path(service_name, use_config)
    try:
        pid = open(pidfile).read()
        return int(pid)
    except IOError:
        return None
    except ValueError:
        raise ValueError("Invalid PID %s" % repr(pid))
