# Copyright Canonical Limited
# Authors: Daniel Silverstone <daniel.silverstone@canonical.com>
#      and Adam Conrad <adam.conrad@canonical.com>

# Buildd Slave implementation

from os.path import isdir, exists
from os import mkdir, symlink, kill, environ, remove
from signal import SIGKILL
import xmlrpclib
__metaclass__ = type

import os
import xmlrpclib
import sha
import urllib2

from twisted.internet import protocol
from twisted.internet import reactor
from twisted.internet import process
from twisted.web import xmlrpc

devnull = open("/dev/null", "r")


# XXX 20050628 cprov
# RunCapture can be replaced with a call to
#
#   twisted.internet.utils.getProcessOutputAndValue
#
# when we start using Twisted 2.0.
class RunCapture(protocol.ProcessProtocol):
    """Run a command and capture its output to a slave's log"""

    def __init__(self, slave, callback):
        self.slave = slave
        self.notify = callback
        self.killCall = None

    def outReceived(self, data):
        """Pass on stdout data to the log."""
        self.slave.log(data)

    def errReceived(self, data):
        """Pass on stderr data to the log.

        With a bit of luck we won't interleave horribly."""
        self.slave.log(data)

    def processEnded(self, statusobject):
        """This method is called when a child process got terminated.

        Three actions are required at this point: identify if we are within an
        "aborting" process, eliminate pending calls to "kill" and invoke the
        programmed notification callback. We only really care about invoking
        the notification callback last thing in this method. The order
        of the rest of the method is not critical.
        """
        # finishing the ABORTING workflow
        if self.slave.builderstatus == BuilderStatus.ABORTING:
            self.slave.builderstatus = BuilderStatus.ABORTED

        # check if there is a pending request for kill the process,
        # in afirmative case simply cancel this request since it
        # already died.
        if self.killCall and self.killCall.active():
            self.killCall.cancel()
            
        # notify the slave, it'll perform the required actions     
        self.notify(statusobject.value.exitCode)


class BuildManager(object):
    """Build Daemon slave build manager abstract parent"""
    
    def __init__(self, slave, buildid):
        object.__init__(self)
        self._buildid = buildid
        self._slave = slave
        self._unpackpath = slave._config.get("allmanagers", "unpackpath")
        self._cleanpath = slave._config.get("allmanagers", "cleanpath")
        self._mountpath = slave._config.get("allmanagers", "mountpath")
        self._umountpath = slave._config.get("allmanagers", "umountpath")
        
    def runSubProcess(self, command, args):
        """Run a sub process capturing the results in the log."""
        self._subprocess = RunCapture(self._slave, self.iterate)
        self._slave.log("RUN: %s %r\n" % (command,args))
        childfds = {0: devnull.fileno(), 1: "r", 2: "r"}
        reactor.spawnProcess(
            self._subprocess, command, args, env=os.environ, 
            path=os.environ["HOME"], childFDs=childfds)

    def _unpackChroot(self, chroottarfile):
        """Unpack the buld chroot."""
        self.runSubProcess(self._unpackpath,
                           ["unpack-chroot", self._buildid, chroottarfile])

    def doCleanup(self):
        """Remove the build tree etc."""
        self.runSubProcess( self._cleanpath,
                        ["remove-build", self._buildid])

    def doMounting(self):
        """Mount things in the chroot, e.g. proc."""
        self.runSubProcess( self._mountpath,
                            ["mount-chroot", self._buildid])
        
    def doUnmounting(self):
        """Unmount the chroot."""
        self.runSubProcess( self._umountpath,
                            ["umount-chroot", self._buildid])

    def initiate(self, files, chroot, extra_args):
        """Initiate a build given the input files"""
        os.mkdir("%s/build-%s" % (os.environ["HOME"], self._buildid))
        for f in files:
            os.symlink( self._slave.cachePath(files[f]),
                        "%s/build-%s/%s" % (os.environ["HOME"],
                                            self._buildid, f))
        self._unpackChroot(self._slave.cachePath(chroot))

    def iterate(self, success):
        """Perform an iteration of the slave.

        The BuildManager tends to work by invoking several
        subprocesses in order. the iterate method is called by the
        object created by runSubProcess to gather the results of the
        sub process.
        """
        raise NotImplementedError("BuildManager should be subclassed to be "
                                  "used")

    def abort(self):
        """Abort the build by killing the subprocess."""
        if not self.alreadyfailed:
            self.alreadyfailed = True
        # Either SIGKILL and SIGTERM presents the same behavior,
        # the process is just killed some time after the signal was sent
        # 10 s ~ 40 s, and returns None as exit_code, instead of the normal
        # interger. See further info on DebianBuildermanager.iterate in
        # debian.py
        # XXX cprov 20050902:
        # we may want to follow the canonical.tachandler kill process style,
        # which sends SIGTERM to the process wait a given timeout and if was
        # not killed sends a SIGKILL. IMO it only would be worth if we found
        # different behaviour than the previous described.
        self._subprocess.transport.signalProcess('TERM')
        # alternativelly to simply send SIGTERM, we can pend a request to
        # send SIGKILL to the process if nothing happened in 10 seconds
        # see base class process
        self._subprocess.killCall = reactor.callLater(10, self.kill) 

    def kill(self):
        """Send SIGKILL to child process

        Mask exception generated when the child process has already exited.
        """
        try:
            self._subprocess.transport.signalProcess('KILL')
        except process.ProcessExitedAlready:
            self._slave.log("ABORTING: Process Exited Already\n")            

class BuilderStatus:
    """Status values for the builder."""

    IDLE = "BuilderStatus.IDLE"
    BUILDING = "BuilderStatus.BUILDING"
    WAITING = "BuilderStatus.WAITING"
    ABORTING = "BuilderStatus.ABORTING"
    ABORTED = "BuilderStatus.ABORTED"

    UNKNOWNSUM = "BuilderStatus.UNKNOWNSUM"
    UNKNOWNBUILDER = "BuilderStatus.UNKNOWNBUILDER"
    

class BuildStatus:
    """Status values for builds themselves."""

    OK = "BuildStatus.OK"
    DEPFAIL = "BuildStatus.DEPFAIL"
    PACKAGEFAIL = "BuildStatus.PACKAGEFAIL"
    CHROOTFAIL = "BuildStatus.CHROOTFAIL"
    BUILDERFAIL = "BuildStatus.BUILDERFAIL"
    
class BuildDSlave(object):
    """Build Daemon slave. Implementation of most needed functions
    for a Build-Slave device.
    """

    def __init__(self, config):
        object.__init__(self)
        self._config = config
        self.builderstatus = BuilderStatus.IDLE
        self._cachepath = self._config.get("slave","filecache")
        self.buildstatus = BuildStatus.OK
        self.waitingfiles = {}
        self._log = None
        
        if not os.path.isdir(self._cachepath):
            raise ValueError("FileCache path is not a dir")
        
    def getArch(self):
        """Return the Architecture tag for the slave."""
        return self._config.get("slave","architecturetag")

    def cachePath(self, file):
        """Return the path in the cache of the file specified."""
        return os.path.join(self._cachepath, file)

    def ensurePresent(self, sha1sum, url=None):
        """Ensure we have the file with the checksum specified.

        Optionally you can provide the librarian URL and
        the build slave will fetch the file if it doesn't have it.
        """
        if url is not None:
            if not os.path.exists(self.cachePath(sha1sum)):
                self.log('Fetching %s by url %s' % (sha1sum, url))
                try:
                    f = urllib2.urlopen(url)
                except Exception, e:
                    self.log('Error accessing Librarian: %s' % e)
                else:
                    of = open(self.cachePath(sha1sum), "w")
                    # Upped for great justice to 256k
                    check_sum = sha.sha()
                    for chunk in iter(lambda: f.read(256*1024), ''):
                        of.write(chunk)
                        check_sum.update(chunk)
                    of.close()
                    f.close()
                    if check_sum.hexdigest() != sha1sum:
                        os.remove(self.cachePath(sha1sum))
                        self.log("Digests did not match, removing again!")
        return os.path.exists(self.cachePath(sha1sum))

    def storeFile(self, content):
        """Take the provided content and store it in the file cache."""
        sha1sum = sha.sha(content).hexdigest()
        if self.ensurePresent(sha1sum):
            return sha1sum
        f = open(self.cachePath(sha1sum), "w")
        f.write(content)
        f.close()
        return sha1sum

    def fetchFile(self, sha1sum):
        """Fetch the file of the given sha1sum."""
        if not self.ensurePresent(sha1sum):
            raise ValueError("Unknown SHA1sum %s" % sha1sum)
        f = open(self.cachePath(sha1sum), "r")
        c = f.read()
        f.close()
        return c

    def abort(self):
        """Abort the current build."""
        # XXX: dsilvers: 2005/01/21: Current abort mechanism doesn't wait
        # for abort to complete. This is potentially an issue in a heavy
        # load situation
        if self.builderstatus != BuilderStatus.BUILDING:
            raise ValueError("Slave is not BUILDING when asked to abort")
        self.manager.abort()
        self.builderstatus = BuilderStatus.ABORTING

    def clean(self):
        """Clean up pending files and reset the internal build state."""
        if self.builderstatus not in [BuilderStatus.WAITING,
                                      BuilderStatus.ABORTED]:
            raise ValueError('Slave is not WAITING|ABORTED when asked'
                             'to clean')
        for f in self.waitingfiles:
            os.remove(self.cachePath(self.waitingfiles[f]))
        self.builderstatus = BuilderStatus.IDLE
        if self._log is not None:
            self._log.close()
            os.remove(self.cachePath("buildlog"))
            self._log = None
        self.waitingfiles = {}
        self.manager = None
        self.buildstatus = BuildStatus.OK

    def log(self, data):
        """Write the provided data to the log."""
        if self._log is not None:
            self._log.write(data);
            self._log.flush()
        if data.endswith("\n"):
            data = data[:-1]
        print "Build log: " + data

    def getLogTail(self):
        """Return the tail of the log."""
        ret = ""
        if self._log is not None:
            rlog = None
            try:
                rlog = open(self.cachePath("buildlog"), "r")
                rlog.seek(0,2)
                count = rlog.tell()
                if count > 2048:
                    count = 2048
                rlog.seek(-count, 2)
                ret = rlog.read(count)
            finally:
                if rlog is not None:
                    rlog.close()
        return ret

    def startBuild(self, manager):
        """Start a build with the provided BuildManager instance."""
        if self.builderstatus != BuilderStatus.IDLE:
            raise ValueError("Slave is not IDLE when asked to start building")
        self.manager = manager
        self.builderstatus = BuilderStatus.BUILDING
        self.emptyLog()

    def emptyLog(self):
        """Empty the log and start again."""
        if self._log is not None:
            self._log.close()
        self._log = open(self.cachePath("buildlog"), "w")

    def builderFail(self):
        """Cease building because the builder has a problem."""
        if self.builderstatus != BuilderStatus.BUILDING:
            raise ValueError("Slave is not BUILDING when set to BUILDERFAIL")
        self.builderstatus = BuilderStatus.WAITING
        self.buildstatus = BuildStatus.BUILDERFAIL

    def chrootFail(self):
        """Cease building because the chroot could not be created or contained
        a set of package control files which couldn't upgrade themselves, or
        yet a lot of causes that imply the CHROOT is corrupted not the
        package.
        """
        if self.builderstatus != BuilderStatus.BUILDING:
            raise ValueError("Slave is not BUILDING when set to CHROOTFAIL")
        self.builderstatus = BuilderStatus.WAITING
        self.buildstatus = BuildStatus.CHROOTFAIL

    def buildFail(self):
        """Cease building because the package failed to build."""
        if self.builderstatus != BuilderStatus.BUILDING:
            raise ValueError("Slave is not BUILDING when set to BUILDFAIL")
        self.builderstatus = BuilderStatus.WAITING
        self.buildstatus = BuildStatus.PACKAGEFAIL

    def depFail(self):
        """Cease building due to a dependency issue."""
        if self.builderstatus != BuilderStatus.BUILDING:
            raise ValueError("Slave is not BUILDING when set to DEPFAIL")
        self.builderstatus = BuilderStatus.WAITING
        self.buildstatus = BuildStatus.DEPFAIL

    def giveBack(self):
        """Give-back package due to a transient buildd/archive issue."""
        if self.builderstatus != BuilderStatus.BUILDING:
            raise ValueError("Slave is not BUILDING when set to GIVENBACK")
        self.builderstatus = BuilderStatus.WAITING
        self.buildstatus = BuildStatus.GIVENBACK

    def buildComplete(self):
        """Mark the build as complete and waiting interaction from the build
        daemon master.
        """
        if self.builderstatus != BuilderStatus.BUILDING:
            raise ValueError("Slave is not BUILDING when told build is "
                             "complete")
        self.builderstatus = BuilderStatus.WAITING
        self.buildstatus = BuildStatus.OK
        

class XMLRPCBuildDSlave(xmlrpc.XMLRPC):
    """XMLRPC build daemon slave management interface"""

    def __init__(self, config):
        xmlrpc.XMLRPC.__init__(self)
        # The V1.0 new-style protocol introduces string-style protocol
        # versions of the form 'MAJOR.MINOR', the protocol is '1.0' for now
        # implying the presence of /filecache/ /filecache/buildlog and
        # the reduced and optimised XMLRPC interface.
        self.protocolversion = '1.0'
        self.slave = BuildDSlave(config)
        self._builders = {}    
        print "Initialised"

    def registerBuilder(self, builderclass, buildertag):
        self._builders[buildertag] = builderclass

    def xmlrpc_echo(self, *args):
        """Echo the argument back."""
        return args

    def xmlrpc_info(self):
        """Return the protocol version and the builder methods supported."""
        return (self.protocolversion, self.slave.getArch(),
                self._builders.keys())

    def xmlrpc_status(self):
        """Return the status of the build daemon.

        Depending on the builder status we return differing amounts of
        data. We do however always return the builder status as the first
        value.
        """
        status = self.slave.builderstatus
        statusname = status.split('.')[-1]
        func = getattr(self, "status_" + statusname, None)
        if func is None:
            raise ValueError("Unknown status '%s'" % status)
        return (status, ) + func()

    def status_IDLE(self):
        """Handler for xmlrpc_status IDLE.

        Returns a tuple containing a empty string since there's nothing
        to report.
        """
        # keep the result code sane
        return ('', )
    
    def status_BUILDING(self):
        """Handler for xmlrpc_status BUILDING.
        
        Returns the build id and up to one kilobyte of log tail
        """
        tail = self.slave.getLogTail()
        return (self.buildid, xmlrpclib.Binary(tail))

    def status_WAITING(self):
        """Handler for xmlrpc_status WAITING.
        
        Returns the build id and the set of files waiting to be returned
        unless the builder failed in which case we return the buildstatus
        and the build id but no file set.
        """
        if self.slave.buildstatus in (BuildStatus.OK, BuildStatus.PACKAGEFAIL,
                                      BuildStatus.DEPFAIL):
            return (self.slave.buildstatus, self.buildid,
                    self.slave.waitingfiles)
        return (self.slave.buildstatus, self.buildid)

    def status_ABORTED(self):
        """Handler for xmlrpc_status ABORTED.

        The only action the master can take is clean, other than ask status,
        of course, it returns the build id only.
        """
        return (self.buildid, )

    def status_ABORTING(self):
        """Handler for xmlrpc_status ABORTING.

        This state means the builder performing the ABORT command and is
        not able to do anything else than answer its status, returns the
        build id only.
        """
        return (self.buildid, )

    def xmlrpc_ensurepresent(self, sha1sum, url):
        """Attempt to ensure the given file is present."""
        return self.slave.ensurePresent(sha1sum, url)

    def xmlrpc_abort(self):
        """Abort the current build."""
        self.slave.abort()
        return BuilderStatus.ABORTING

    def xmlrpc_clean(self):
        """Clean up the waiting files and reset the slave's internal state."""
        self.slave.clean()
        return BuilderStatus.IDLE

    def xmlrpc_build(self, buildid, builder, chrootsum, filemap, args):
        if not builder in self._builders:
            return BuilderStatus.UNKNOWNBUILDER
        if not self.slave.ensurePresent(chrootsum):
            return BuilderStatus.UNKNOWNSUM, chrootsum
        for checksum in filemap.itervalues():
            if not self.slave.ensurePresent(checksum):
                return BuilderStatus.UNKNOWNSUM, checksum
        if buildid is None or buildid == "" or buildid == 0:
            raise ValueError(buildid)
        # builder is available, buildd is non empty,
        # filelist is consistent, chrootsum is available, let's initiate...

        self.buildid = buildid
        
        self.slave.startBuild(self._builders[builder](self.slave, buildid))
        self.slave.manager.initiate(filemap, chrootsum, args)
        return BuilderStatus.BUILDING
    
