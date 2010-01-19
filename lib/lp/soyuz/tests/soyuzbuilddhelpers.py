# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Mock Build objects for tests soyuz buildd-system."""

__metaclass__ = type

__all__ = [
    'MockBuilder',
    'SaneBuildingSlave',
    'SaneWaitingSlave',
    'InsaneWatingSlave',
    'LostBuildingSlave',
    'LostWaitingSlave',
    'LostBuildingBrokenSlave',
    'BrokenSlave',
    'OkSlave',
    'BuildingSlave',
    'AbortedSlave',
    'WaitingSlave',
    'AbortingSlave',
    ]

from StringIO import StringIO
import subprocess
import xmlrpclib

from canonical.config import config
from lp.buildmaster.interfaces.builder import CannotFetchFile


class MockBuilder:
    """Emulates a IBuilder class."""

    def __init__(self, name, slave):
        self.slave = slave
        self.builderok = True
        self.manual = False
        self.url = 'http://fake:0000'
        slave.urlbase = self.url
        self.name = name
        self.virtualized = True

    def failBuilder(self, reason):
        self.builderok = False
        self.failnotes = reason

    def slaveStatusSentence(self):
        return self.slave.status()

    def cleanSlave(self):
        return self.slave.clean()

    def requestAbort(self):
        return self.slave.abort()

    def resumeSlave(self, logger):
        return ('out', 'err')

    def checkSlaveAlive(self):
        pass

    def checkCanBuildForDistroArchSeries(self, distro_arch_series):
        pass


class SaneBuildingSlave:
    """A mock slave that is currently building build 8 and buildqueue 1."""

    def status(self):
        return ('BuilderStatus.BUILDING', '8-1', 'Doing something ...')

    def clean(self):
        print 'Rescuing SaneSlave'

    def echo(self, *args):
        return args

    def info(self):
        return ['1.0', 'i386', ['debian']]

class SaneWaitingSlave:
    """A mock slave that is currently waiting.

    Uses build 8 and buildqueue 1.
    """

    def status(self):
        return ('BuilderStatus.WAITING', 'BuildStatus.OK', '8-1')

    def clean(self):
        print 'Rescuing SaneSlave'


class InsaneWaitingSlave:
    """A mock slave waiting with a bogus Build/BuildQueue relation."""

    def status(self):
        return ('BuilderStatus.WAITING', 'BuildStatus.OK', '7-1')

    def clean(self):
        pass


class LostBuildingSlave:
    """A mock slave building bogus Build/BuildQueue IDs."""

    def status(self):
        return ('BuilderStatus.BUILDING', '1000-10000')

    def abort(self):
        pass


class LostWaitingSlave:
    """A mock slave waiting with bogus Build/BuildQueue IDs."""

    def status(self):
        return ('BuilderStatus.WAITING', 'BuildStatus.OK', '1000-10000')

    def clean(self):
        pass


class LostBuildingBrokenSlave:
    """A mock slave building bogus Build/BuildQueue IDs that can't be aborted.

    When 'aborted' it raises an xmlrpclib.Fault(8002, 'Could not abort')
    """

    def status(self):
        return ('BuilderStatus.BUILDING', '1000-10000')

    def abort(self):
        raise xmlrpclib.Fault(8002, "Could not abort")


class BrokenSlave:
    """A mock slave that reports that it is broken."""

    def status(self):
        raise xmlrpclib.Fault(8001, "Broken slave")


class OkSlave:
    """An idle mock slave that prints information about itself."""

    def status(self):
        return ('BuilderStatus.IDLE', '')

    def ensurepresent(self, sha1, url, user=None, password=None):
        print "ensurepresent called, url=%s" % url
        if user is not None and user != "":
            print "URL authorisation with %s/%s" % (user, password)
        return True, None

    def build(self, buildid, buildtype, chroot, filemap, args):
        info = 'OkSlave BUILDING'
        print info
        if 'archives' in args:
            print "Archives:"
            for archive_line in sorted(args['archives']):
                print " %s" % archive_line
        else:
            print "No archives set."
        print "Suite: %s" % args['suite']
        print "Ogre-component: %s" % args['ogrecomponent']
        print "Archive Purpose: %s" % args['archive_purpose']
        print "Archive Private: %s" % args['archive_private']
        return ('BuildStatus.Building', info)

    def fetchlogtail(self, size):
        return 'BOGUS'

    def clean(self):
        pass

    def info(self):
        return ('1.0', 'i386', 'debian')

    def resume(self):
        resume_argv = config.builddmaster.vm_resume_command.split()
        resume_process = subprocess.Popen(
            resume_argv, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        stdout, stderr = resume_process.communicate()

        return (stdout, stderr, resume_process.returncode)

    def sendFileToSlave(self, url, sha1, username="", password=""):
        present, info = self.ensurepresent(sha1, url, username, password)
        if not present:
            raise CannotFetchFile(url, info)

    def cacheFile(self, logger, libraryfilealias):
        self.sendFileToSlave(
            libraryfilealias.http_url, libraryfilealias.content.sha1)


class BuildingSlave(OkSlave):
    """A mock slave that looks like it's currently building."""

    def status(self):
        buildlog = xmlrpclib.Binary("This is a build log")
        return ('BuilderStatus.BUILDING', '1-1', buildlog)

    def getFile(self, sum):
        if sum == "buildlog":
            s = StringIO("This is a build log")
            s.headers = {'content-length':19}
            return s


class AbortedSlave(OkSlave):
    """A mock slave that looks like it's aborted."""

    def status(self):
        return ('BuilderStatus.ABORTED', '1-1')


class WaitingSlave(OkSlave):
    """A mock slave that looks like it's currently waiting."""

    def __init__(self, state, dependencies=None):
        self.state = state
        self.dependencies = dependencies

    def status(self):
        return ('BuilderStatus.WAITING', self.state, '1-1', {},
                self.dependencies )

    def getFile(self, sum):
        if sum == "buildlog":
            s = StringIO("This is a build log")
            s.headers = {'content-length':19}
            return s

class AbortingSlave(OkSlave):
    """A mock slave that looks like it's in the process of aborting."""

    def status(self):
        return ('BuilderStatus.ABORTING', '1-1')
