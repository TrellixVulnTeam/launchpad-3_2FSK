# (C) Canonical Software Ltd. 2004-2006, all rights reserved.

__all__ = [ 'Publisher', 'pocketsuffix', 'suffixpocket' ]

import os
from md5 import md5
from sha import sha
from datetime import datetime

from canonical.archivepublisher.domination import Dominator
from canonical.archivepublisher.ftparchive import FTPArchiveHandler
from canonical.librarian.client import LibrarianClient
from canonical.lp.dbschema import (
    PackagePublishingPocket, PackagePublishingStatus)

from canonical.launchpad.interfaces import pocketsuffix

suffixpocket = dict((v, k) for (k, v) in pocketsuffix.items())
# XXX: if people actually start seriously using ComponentSelections this
# will need to be revisited. For instance, adding new components will
# break places which use this list. -- kiko, 2006-08-23
HARDCODED_COMPONENT_ORDER = ['main', 'restricted', 'universe', 'multiverse']

DISTRORELEASE_STANZA = """Origin: %s
Label: %s
Suite: %s
Version: %s
Codename: %s
Date: %s
Architectures: %s
Components: %s
Description: %s
"""

DISTROARCHRELEASE_STANZA = """Archive: %s
Version: %s
Component: %s
Origin: %s
Label: %s
Architecture: %s
"""

def reorder_components(components):
    """Return a list of the components provided.

    The list will be ordered by the semi arbitrary rules of ubuntu.
    Over time this method needs to be removed and replaced by having
    component ordering codified in the database.
    """
    ret = []
    for comp in HARDCODED_COMPONENT_ORDER:
        if comp in components:
            ret.append(comp)
            components.remove(comp)
    ret.extend(components)
    return ret


class Publisher(object):
    """Publisher is the class used to provide the facility to publish
    files in the pool of a Distribution. The publisher objects will be
    instantiated by the archive build scripts and will be used throughout
    the processing of each DistroRelease and DistroArchRelease in question
    """

    def __init__(self, log, config, diskpool, distribution, library=None):
        """Initialise a publisher. Publishers need the pool root dir
        and a DiskPool object.
        """
        self.log = log

        self._config = config
        self.distro = distribution
        if not os.path.isdir(config.poolroot):
            raise ValueError("Root %s is not a directory or does "
                             "not exist" % config.poolroot)
        self._diskpool = diskpool

        if library is None:
            self._library = LibrarianClient()
        else:
            self._library = library

        # Grab a reference to an apt_handler as we use it later to
        # probe which components need releases files generated.
        self.apt_handler = FTPArchiveHandler(self.log, self._config,
                                             self._diskpool, self.distro,
                                             self)
        # Track which distrorelease pockets have been dirtied by a
        # change, and therefore need domination/apt-ftparchive work.
        # This is a set of tuples in the form (distrorelease.name, pocket)
        self.dirty_pockets = set()

    def A_publish(self, force_publishing):
        """First step in publishing: actual package publishing.

        Asks each DistroRelease to publish itself, which causes
        publishing records to be updated, and files to be placed on disk
        where necessary.
        """
        self.log.debug("* Step A: Publishing packages")
        for distrorelease in self.distro:
            more_dirt = distrorelease.publish(self._diskpool, self.log,
                                              is_careful=force_publishing)
            self.dirty_pockets.update(more_dirt)

    def B_dominate(self, force_domination):
        """Second step in publishing: domination."""
        self.log.debug("* Step B: dominating packages")
        judgejudy = Dominator(self.log)
        for distrorelease in self.distro:
            for pocket in PackagePublishingPocket.items:
                if not force_domination:
                    if not self.isDirty(distrorelease, pocket):
                        self.log.debug("Skipping domination for %s/%s" %
                                   (distrorelease.name, pocket))
                        continue
                    if not distrorelease.isUnstable():
                        # We're not doing a full run and the
                        # distrorelease is now 'stable': if we try to
                        # write a release file for it, we're doing
                        # something wrong.
                        assert pocket != PackagePublishingPocket.RELEASE
                judgejudy.judgeAndDominate(distrorelease, pocket, self._config)

    def C_doFTPArchive(self, is_careful):
        """Does the ftp-archive step: generates Sources and Packages."""
        self.log.debug("* Step C: Set apt-ftparchive up and run it")
        self.apt_handler.run(is_careful)

    def C_writeIndexes(self, is_careful):
        """Write Index files (Packages & Sources) using LP information.

        Iterates over all distroreleases and its pockets and components.
        """
        self.log.debug("* Step C': write indexes derictly from DB")
        for distrorelease in self.distro:
            for pocket, suffix in pocketsuffix.items():
                if not is_careful:
                    if not self.isDirty(distrorelease, pocket):
                        self.log.debug("Skipping index generation for %s/%s" %
                                   (distrorelease.name, pocket))
                        continue
                    if not distrorelease.isUnstable():
                        # See comment in B_dominate
                        assert pocket != PackagePublishingPocket.RELEASE

                for component in distrorelease.components:
                    self._writeComponentIndexes(
                        distrorelease, pocket, component)

    def D_writeReleaseFiles(self, is_careful):
        """Write out the Release files for the provided distribution.

        If is_careful is specified, we include all pockets of all releases.

        Otherwise we include only pockets flagged as true in dirty_pockets.
        """
        self.log.debug("* Step D: Generating Release files.")
        for distrorelease in self.distro:
            for pocket, suffix in pocketsuffix.items():

                if not is_careful:
                    if not self.isDirty(distrorelease, pocket):
                        self.log.debug("Skipping release files for %s/%s" %
                                   (distrorelease.name, pocket))
                        continue
                    if not distrorelease.isUnstable():
                        # See comment in B_dominate
                        assert pocket != PackagePublishingPocket.RELEASE

                self._writeDistroRelease(distrorelease, pocket)

    def E_sanitiseLinks(self):
        """Ensure links in the pool are sane."""
        self.log.debug("* Step E: Sanitising links in the pool.")
        self._diskpool.sanitiseLinks(HARDCODED_COMPONENT_ORDER)

    def isDirty(self, distrorelease, pocket):
        """True if a publication has happened in this release and pocket."""
        if not (distrorelease.name, pocket) in self.dirty_pockets:
            return False
        return True

    def _writeDistroRelease(self, distrorelease, pocket):
        """Write out the Release files for the provided distrorelease."""
        # XXX: untested method -- kiko, 2006-08-24

        # As we generate file lists for apt-ftparchive we record which
        # distroreleases and so on we need to generate Release files for.
        # We store this in release_files_needed and consume the information
        # when writeReleaseFiles is called.
        full_name = distrorelease.name + pocketsuffix[pocket]
        release_files_needed = self.apt_handler.release_files_needed
        if full_name not in release_files_needed:
            # If we don't need to generate a release for this release
            # and pocket, don't!
            return

        all_components = set()
        all_architectures = set()
        all_files = set()
        for component, architectures in release_files_needed[full_name].items():

            all_components.add(component)
            for architecture in architectures:
                # XXX malcc 2006-09-20: We don't like the way we build this
                # all_architectures list. Make this better code.
                clean_architecture = self._writeDistroArchRelease(
                    distrorelease, pocket, component, architecture, all_files)
                if clean_architecture != "source":
                    all_architectures.add(clean_architecture)

        drsummary = "%s %s " % (self.distro.displayname,
                                distrorelease.displayname)
        if pocket == PackagePublishingPocket.RELEASE:
            drsummary += distrorelease.version
        else:
            drsummary += pocket.name.capitalize()

        f = open(os.path.join(
            self._config.distsroot, full_name, "Release"), "w")

        stanza = DISTRORELEASE_STANZA % (
                    self.distro.displayname,
                    self.distro.displayname,
                    full_name,
                    distrorelease.version,
                    distrorelease.name,
                    datetime.utcnow().strftime("%a, %d %b %Y %k:%M:%S UTC"),
                    " ".join(sorted(list(all_architectures))),
                    " ".join(reorder_components(all_components)), drsummary)
        f.write(stanza)

        f.write("MD5Sum:\n")
        all_files = sorted(list(all_files), key=os.path.dirname)
        for file_name in all_files:
            self._writeSumLine(full_name, f, file_name, md5)
        f.write("SHA1:\n")
        for file_name in all_files:
            self._writeSumLine(full_name, f, file_name, sha)

        f.close()

    def _writeComponentIndexes(self, distrorelease, pocket, component):
        """Write Index files for single distrorelease + pocket + component.

        Iterates over all supported architectures and 'sources', no
        support for installer-* yet.
        Write contents using LP info to an extra plain file (Packages.lp
        and Sources.lp .
        """
        full_name = distrorelease.name + pocketsuffix[pocket]

        self.log.debug("Generate Indexes for %s/%s"
                       % (full_name, component.name))

        source_index_path = os.path.join(
            self._config.distsroot, full_name, component.name,
            'source', "Sources.lp")
        source_index = open(source_index_path, "w")

        self.log.debug("Generating Sources")

        for spp in distrorelease.getSourcePackagePublishing(
            PackagePublishingStatus.PUBLISHED, pocket=pocket,
            component=component):
            source_index.write(spp.index_stanza().encode('utf-8'))

        source_index.close()

        for arch in distrorelease.architectures:
            arch_path = 'binary-%s' % arch.architecturetag
            self.log.debug("Generating Packages for %s" % arch_path)

            package_index_path = os.path.join(
                self._config.distsroot, full_name, component.name,
                arch_path, "Packages.lp")

            package_index = open(package_index_path, "w")

            for bpp in distrorelease.getBinaryPackagePublishing(
                archtag=arch.architecturetag, pocket=pocket,
                component=component):
                package_index.write(bpp.index_stanza().encode('utf-8'))

            package_index.close()

    def _writeDistroArchRelease(self, distrorelease, pocket, component,
                                architecture, all_files):
        """Write out a Release file for a DAR."""
        # XXX: untested method -- kiko, 2006-08-24

        full_name = distrorelease.name + pocketsuffix[pocket]

        self.log.debug("Writing Release file for %s/%s/%s" % (
            full_name, component, architecture))
        if architecture != "source":
            file_stub = "Packages"

            # Set up the debian-installer paths, which are nested
            # inside the component
            di_path = os.path.join(component, "debian-installer",
                                   architecture)
            di_file_stub = os.path.join(di_path, file_stub)
            for suffix in ('', '.gz', '.bz2'):
                all_files.add(di_file_stub + suffix)
            # Strip "binary-" off the front of the architecture
            clean_architecture = architecture[7:]
        else:
            file_stub = "Sources"
            clean_architecture = architecture

        # Now, grab the actual (non-di) files inside each of
        # the suite's architectures
        file_stub = os.path.join(component, architecture, file_stub)
        for suffix in ('', '.gz', '.bz2'):
            all_files.add(file_stub + suffix)
        all_files.add(os.path.join(component, architecture, "Release"))

        f = open(os.path.join(self._config.distsroot, full_name,
                              component, architecture, "Release"), "w")
        stanza = DISTROARCHRELEASE_STANZA % (
                full_name,
                distrorelease.version,
                component,
                self.distro.displayname,
                self.distro.displayname,
                clean_architecture)
        f.write(stanza)
        f.close()

        return clean_architecture

    def _writeSumLine(self, distrorelease_name, out_file, file_name, sum_form):
        """Write out a checksum line.

        Writes a checksum to the given file for the given filename in
        the given form.
        """
        full_name = os.path.join(self._config.distsroot,
                                 distrorelease_name, file_name)
        if not os.path.exists(full_name):
            # The file we were asked to write out doesn't exist.
            # Most likely we have an incomplete archive (E.g. no sources
            # for a given distrorelease). This is a non-fatal issue
            self.log.debug("Failed to find " + full_name)
            return
        in_file = open(full_name,"r")
        contents = in_file.read()
        in_file.close()
        length = len(contents)
        checksum = sum_form(contents).hexdigest()
        out_file.write(" %s % 16d %s\n" % (checksum, length, file_name))
