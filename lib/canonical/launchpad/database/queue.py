# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = [
    'DistroReleaseQueue',
    'DistroReleaseQueueBuild',
    'DistroReleaseQueueSource',
    'DistroReleaseQueueCustom',
    'DistroReleaseQueueSet',
    'filechunks',
    ]

import os
import shutil
import tempfile
import pytz
from datetime import datetime

from zope.interface import implements

from sqlobject import (
    ForeignKey, SQLMultipleJoin, SQLObjectNotFound)

from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import UTC_NOW

from canonical.lp.dbschema import (
    EnumCol, DistroReleaseQueueStatus, DistroReleaseQueueCustomFormat,
    PackagePublishingPocket, PackagePublishingStatus)

from canonical.launchpad.interfaces import (
    IDistroReleaseQueue, IDistroReleaseQueueBuild, IDistroReleaseQueueSource,
    IDistroReleaseQueueCustom, NotFoundError, QueueStateWriteProtectedError,
    QueueInconsistentStateError, QueueSourceAcceptError,
    QueueBuildAcceptError, IDistroReleaseQueueSet)

from canonical.librarian.interfaces import DownloadFailed


from canonical.launchpad.database.publishing import (
    SecureSourcePackagePublishingHistory,
    SecureBinaryPackagePublishingHistory)


from canonical.cachedproperty import cachedproperty

# There are imports below in DistroReleaseQueueCustom for various bits
# of the archivepublisher which cause circular import errors if they
# are placed here.


def filechunks(file, chunk_size=256*1024):
    """Return an iterator which reads chunks of the given file."""
    # We use the two-arg form of the iterator here to form an iterator
    # which reads chunks from the given file.
    return iter(lambda: file.read(chunk_size), '')


def debug(logger, msg):
    """Shorthand debug notation for publish() methods."""
    if logger is not None:
        logger.debug(msg)


class DistroReleaseQueue(SQLBase):
    """A Queue item for Lucille."""
    implements(IDistroReleaseQueue)

    _defaultOrder = ['id']

    status = EnumCol(dbName='status', unique=False, notNull=True,
                     default=DistroReleaseQueueStatus.NEW,
                     schema=DistroReleaseQueueStatus)

    distrorelease = ForeignKey(dbName="distrorelease",
                               foreignKey='DistroRelease')

    pocket = EnumCol(dbName='pocket', unique=False, default=None, notNull=True,
                     schema=PackagePublishingPocket)

    changesfile = ForeignKey(dbName='changesfile',
                             foreignKey="LibraryFileAlias",
                             notNull=True)

    # Join this table to the DistroReleaseQueueBuild and the
    # DistroReleaseQueueSource objects which are related.
    sources = SQLMultipleJoin('DistroReleaseQueueSource',
                              joinColumn='distroreleasequeue')
    builds = SQLMultipleJoin('DistroReleaseQueueBuild',
                             joinColumn='distroreleasequeue')

    # Also the custom files associated with the build.
    customfiles = SQLMultipleJoin('DistroReleaseQueueCustom',
                                  joinColumn='distroreleasequeue')


    def _set_status(self, value):
        """Directly write on 'status' is forbidden.

        Force user to use the provided machine-state methods.
        Raises QueueStateWriteProtectedError.
        """
        # XXX: bug #29663: this is a bit evil, but does the job. Andrew
        # has suggested using immutable=True in the column definition.
        #   -- kiko, 2006-01-25
        # allow 'status' write only in creation process.
        if self._SO_creating:
            self._SO_set_status(value)
            return
        # been facist
        raise QueueStateWriteProtectedError(
            'Directly write on queue status is forbidden use the '
            'provided methods to set it.')

    def setNew(self):
        """See IDistroReleaseQueue."""
        self._SO_set_status(DistroReleaseQueueStatus.NEW)

    def setUnapproved(self):
        """See IDistroReleaseQueue."""
        self._SO_set_status(DistroReleaseQueueStatus.UNAPPROVED)

    def setAccepted(self):
        """See IDistroReleaseQueue."""
        for source in self.sources:
            # if something goes wrong we will raise an exception
            # (QueueSourceAcceptError) before setting any value.
            # Mask the error with state-machine default exception
            try:
                source.checkComponentAndSection()
            except QueueSourceAcceptError, info:
                raise QueueInconsistentStateError(info)

        for build in self.builds:
            # as before, but for QueueBuildAcceptError
            try:
                build.checkComponentAndSection()
            except QueueBuildAcceptError, info:
                raise QueueInconsistentStateError(info)

        # if the previous checks applied and pass we do set the value
        self._SO_set_status(DistroReleaseQueueStatus.ACCEPTED)

    def setDone(self):
        """See IDistroReleaseQueue."""
        self._SO_set_status(DistroReleaseQueueStatus.DONE)

    def setRejected(self):
        """See IDistroReleaseQueue."""
        self._SO_set_status(DistroReleaseQueueStatus.REJECTED)

    # XXX cprov 20060314: following properties should be redesigned to
    # reduce the duplicated code.
    @cachedproperty
    def queue_icons(self):
        """See IDistroReleaseQueue"""
        icons = []

        if self.sources:
            icons.append('/@@/package-source')

        if self.builds:
            icons.append('/@@/package-binary')

        custom_set = set()
        for custom in self.customfiles:
            custom_set.add(custom.customformat)

        custom_icons = {
            DistroReleaseQueueCustomFormat.DEBIAN_INSTALLER: '/@@/ubuntu.gif',
            DistroReleaseQueueCustomFormat.ROSETTA_TRANSLATIONS: '/@@/translations',
            DistroReleaseQueueCustomFormat.DIST_UPGRADER: '/@@/topic_icon.gif',
            }

        for custom_format in custom_set:
            icons.append(custom_icons[custom_format])

        if not icons:
            raise NotFoundError('Queue Icon not found for %s' % self.id)

        return icons

    @cachedproperty
    def changesfilename(self):
        """A changes filename to accurately represent this upload."""
        filename = self.sourcepackagename.name + "_" + self.sourceversion + "_"
        arch_tags = []
        if self.sources:
            arch_tags.append("source")
        for queue_build in self.builds:
            tag = queue_build.build.distroarchrelease.architecturetag
            arch_tags.append(tag)
        filename += "+".join(arch_tags) + ".changes"
        return filename

    @property
    def age(self):
        """See IDistroReleaseQueue"""
        UTC = pytz.timezone('UTC')
        now = datetime.now(UTC)
        return now - self.datecreated

    @cachedproperty
    def datecreated(self):
        """The date on which this queue item was created.

        We look through the sources/builds of this queue item to find out
        when we created it. This is heuristic for now but may be made into
        a column at a later date.
        """
        if self.sources:
            return self.sources[0].sourcepackagerelease.dateuploaded
        if self.builds:
            return self.builds[0].build.binarypackages[0].datecreated
        if self.customfiles:
            return self.customfiles[0].libraryfilealias.content.datecreated

        raise NotFoundError('Can not find datecreated for %s' % self.id)

    @cachedproperty
    def displayname(self):
        """See IDistroReleaseQueue"""
        if self.sources:
            return self.sources[0].sourcepackagerelease.name
        if self.builds:
            return self.builds[0].build.sourcepackagerelease.name
        if self.customfiles:
            return self.customfiles[0].libraryfilealias.filename

        raise NotFoundError('Can not find displayname for %s' % self.id)

    @cachedproperty
    def sourcepackagename(self):
        """The source package name related to this queue item.

        We look through sources/builds to find it. This is heuristic for now
        but may be made into a column at a later date.
        """
        assert self.sources or self.builds
        if self.sources:
            return self.sources[0].sourcepackagerelease.sourcepackagename
        if self.builds:
            return self.builds[0].build.sourcepackagerelease.sourcepackagename

    @cachedproperty
    def sourceversion(self):
        """The source package version related to this queue item.

        This is currently heuristic but may be more easily calculated later.
        """
        if self.sources:
            return self.sources[0].sourcepackagerelease.version
        if self.builds:
            return self.builds[0].build.sourcepackagerelease.version
        if self.customfiles:
            return '-'

        raise NotFoundError('Can not find version for %s' % self.id)

    @cachedproperty
    def sourcepackagerelease(self):
        """The source package release related to this queue item.

        This is currently heuristic but may be more easily calculated later.
        """
        assert self.sources or self.builds
        if self.sources:
            return self.sources[0].sourcepackagerelease
        if self.builds:
            return self.builds[0].build.sourcepackagerelease

    def realiseUpload(self, logger=None):
        """See IDistroReleaseQueue."""
        assert self.status == DistroReleaseQueueStatus.ACCEPTED

        # In realising an upload we first load all the sources into
        # the publishing tables, then the binaries, then we attempt
        # to publish the custom objects.
        for queue_source in self.sources:
            queue_source.publish(logger)
        for queue_build in self.builds:
            queue_build.publish(logger)
        for customfile in self.customfiles:
            customfile.publish(logger)

        self.setDone()

    def addSource(self, spr):
        """See IDistroReleaseQueue."""
        return DistroReleaseQueueSource(distroreleasequeue=self.id,
                                        sourcepackagerelease=spr.id)

    def addBuild(self, build):
        """See IDistroReleaseQueue."""
        return DistroReleaseQueueBuild(distroreleasequeue=self.id,
                                       build=build.id)

    def addCustom(self, library_file, custom_type):
        """See IDistroReleaseQueue."""
        return DistroReleaseQueueCustom(distroreleasequeue=self.id,
                                        libraryfilealias=library_file.id,
                                        customformat=custom_type)


class DistroReleaseQueueBuild(SQLBase):
    """A Queue item's related builds (for Lucille)."""
    implements(IDistroReleaseQueueBuild)

    _defaultOrder = ['id']

    distroreleasequeue = ForeignKey(
        dbName='distroreleasequeue',
        foreignKey='DistroReleaseQueue'
        )

    build = ForeignKey(dbName='build', foreignKey='Build')

    def checkComponentAndSection(self):
        """See IDistroReleaseQueueBuild."""
        distrorelease = self.distroreleasequeue.distrorelease
        for binary in self.build.binarypackages:
            if binary.component not in distrorelease.components:
                raise QueueBuildAcceptError(
                    'Component "%s" is not allowed in %s'
                    % (binary.component.name, distrorelease.name))
            if binary.section not in distrorelease.sections:
                raise QueueBuildAcceptError(
                    'Section "%s" is not allowed in %s' % (binary.section.name,
                                                           distrorelease.name))

    def publish(self, logger=None):
        """See IDistroReleaseQueueBuild."""
        # Determine the build's architecturetag.
        build_archtag = self.build.distroarchrelease.architecturetag
        # Determine the target arch release.
        # This will raise NotFoundError if anything odd happens.
        target_dar = self.distroreleasequeue.distrorelease[build_archtag]
        debug(logger, "Publishing build to %s/%s/%s" % (
            target_dar.distrorelease.distribution.name,
            target_dar.distrorelease.name,
            build_archtag))
        # And get the other distroarchreleases
        other_dars = set(self.distroreleasequeue.distrorelease.architectures)
        other_dars = other_dars - set([target_dar])
        # First up, publish everything in this build into that dar.
        published_binaries = []
        for binary in self.build.binarypackages:
            target_dars = set([target_dar])
            if not binary.architecturespecific:
                target_dars = target_dars.union(other_dars)
                debug(logger, "... %s/%s (Arch Independent)" % (
                    binary.binarypackagename.name,
                    binary.version))
            else:
                debug(logger, "... %s/%s (Arch Specific)" % (
                    binary.binarypackagename.name,
                    binary.version))
            for each_target_dar in target_dars:
                # XXX: dsilvers: 20051020: What do we do about embargoed
                # binaries here? bug 3408
                sbpph = SecureBinaryPackagePublishingHistory(
                    binarypackagerelease=binary.id,
                    distroarchrelease=each_target_dar.id,
                    component=binary.component.id,
                    section=binary.section.id,
                    priority=binary.priority,
                    status=PackagePublishingStatus.PENDING,
                    datecreated=UTC_NOW,
                    pocket=self.distroreleasequeue.pocket,
                    embargo=False
                    )
                published_binaries.append(sbpph)


class DistroReleaseQueueSource(SQLBase):
    """A Queue item's related sourcepackagereleases (for Lucille)."""
    implements(IDistroReleaseQueueSource)

    _defaultOrder = ['id']

    distroreleasequeue = ForeignKey(
        dbName='distroreleasequeue',
        foreignKey='DistroReleaseQueue'
        )

    sourcepackagerelease = ForeignKey(
        dbName='sourcepackagerelease',
        foreignKey='SourcePackageRelease'
        )

    def checkComponentAndSection(self):
        """See IDistroReleaseQueueSource."""
        distrorelease = self.distroreleasequeue.distrorelease
        component = self.sourcepackagerelease.component
        section = self.sourcepackagerelease.section

        if component not in distrorelease.components:
            raise QueueSourceAcceptError(
                'Component "%s" is not allowed in %s' % (component.name,
                                                         distrorelease.name))

        if section not in distrorelease.sections:
            raise QueueSourceAcceptError(
                'Section "%s" is not allowed in %s' % (section.name,
                                                       distrorelease.name))

    def publish(self, logger=None):
        """See IDistroReleaseQueueSource."""
        # Publish myself in the distrorelease pointed at by my queue item.
        # XXX: dsilvers: 20051020: What do we do here to support embargoed
        # sources? bug 3408
        debug(logger, "Publishing source %s/%s to %s/%s" % (
            self.sourcepackagerelease.name,
            self.sourcepackagerelease.version,
            self.distroreleasequeue.distrorelease.distribution.name,
            self.distroreleasequeue.distrorelease.name))

        return SecureSourcePackagePublishingHistory(
            distrorelease=self.distroreleasequeue.distrorelease.id,
            sourcepackagerelease=self.sourcepackagerelease.id,
            component=self.sourcepackagerelease.component.id,
            section=self.sourcepackagerelease.section.id,
            status=PackagePublishingStatus.PENDING,
            datecreated=UTC_NOW,
            pocket=self.distroreleasequeue.pocket,
            embargo=False)


class DistroReleaseQueueCustom(SQLBase):
    """A Queue item's related custom format uploads."""
    implements(IDistroReleaseQueueCustom)

    _defaultOrder = ['id']

    distroreleasequeue = ForeignKey(
        dbName='distroreleasequeue',
        foreignKey='DistroReleaseQueue'
        )

    customformat = EnumCol(dbName='customformat', unique=False,
                           default=None, notNull=True,
                           schema=DistroReleaseQueueCustomFormat)

    libraryfilealias = ForeignKey(dbName='libraryfilealias',
                                  foreignKey="LibraryFileAlias",
                                  notNull=True)

    def publish(self, logger=None):
        """See IDistroReleaseQueueCustom."""
        # This is a marker as per the comment in dbschema.py.
        ##CUSTOMFORMAT##
        # Essentially, if you alter anything to do with what custom formats
        # are, what their tags are, or anything along those lines, you should
        # grep for the marker in the source tree and fix it up in every place
        # so marked.
        name = "publish_" + self.customformat.name
        method = getattr(self, name, None)
        if method is not None:
            method(logger)
        else:
            raise NotFoundError("Unable to find a publisher method for %s" % (
                self.customformat.name))

    @property
    def temp_filename(self):
        """See IDistroReleaseQueueCustom."""
        temp_dir = tempfile.mkdtemp()
        temp_file_name = os.path.join(temp_dir, self.libraryfilealias.filename)

        temp_file = file(temp_file_name, "wb")
        # Pump the file from the librarian...
        self.libraryfilealias.open()
        for chunk in filechunks(self.libraryfilealias):
            temp_file.write(chunk)
        temp_file.close()
        self.libraryfilealias.close()
        return temp_file_name

    @property
    def archive_config(self):
        """See IDistroReleaseQueueCustom."""
        # XXX cprov 20050303: use the Zope Component Lookup to instantiate
        # the object in question and avoid circular imports
        from canonical.archivepublisher.config import Config as ArchiveConfig
        distrorelease = self.distroreleasequeue.distrorelease
        return ArchiveConfig(distrorelease.distribution,
                             distrorelease.distribution.releases)

    def publish_DEBIAN_INSTALLER(self, logger=None):
        """See IDistroReleaseQueueCustom."""
        # XXX cprov 20050303: We need to use the Zope Component Lookup
        # to instantiate the object in question and avoid circular imports
        from canonical.archivepublisher.debian_installer import (
            process_debian_installer)

        temp_filename = self.temp_filename
        try:
            process_debian_installer(
                self.archive_config.archiveroot, temp_filename,
                self.distroreleasequeue.distrorelease.name)
        finally:
            shutil.rmtree(os.path.dirname(temp_filename))

    def publish_DIST_UPGRADER(self, logger=None):
        """See IDistroReleaseQueueCustom."""
        # XXX cprov 20050303: We need to use the Zope Component Lookup
        # to instantiate the object in question and avoid circular imports
        from canonical.archivepublisher.dist_upgrader import (
            process_dist_upgrader)

        temp_filename = self.temp_filename
        try:
            process_dist_upgrader(
                self.archive_config.archiveroot, temp_filename,
                self.distroreleasequeue.distrorelease.name)
        finally:
            shutil.rmtree(os.path.dirname(temp_filename))

    def publish_ROSETTA_TRANSLATIONS(self, logger=None):
        """See IDistroReleaseQueueCustom."""
        # XXX: dsilvers: 20051115: We should be able to get a
        # sourcepackagerelease directly.
        sourcepackagerelease = (
            self.distroreleasequeue.builds[0].build.sourcepackagerelease)

        if sourcepackagerelease.component.name != 'main':
            # XXX: CarlosPerelloMarin 20060216 This should be implemented
            # using a more general rule to accept different policies depending
            # on the distribution. See bug #31665 for more details.
            # Ubuntu's MOTU told us that they are not able to handle
            # translations like we do in main. We are going to import only
            # packages in main.
            return

        # Attach the translation tarball. It's always published.
        try:
            sourcepackagerelease.attachTranslationFiles(
                self.libraryfilealias, True)
        except DownloadFailed:
            if logger is not None:
                debug(logger, "Unable to fetch %s to import it into Rosetta" %
                    self.libraryfilealias.url)


class DistroReleaseQueueSet:
    """See IDistroReleaseQueueSet"""
    implements(IDistroReleaseQueueSet)

    def __iter__(self):
        """See IDistroReleaseQueueSet."""
        return iter(DistroReleaseQueue.select())

    def __getitem__(self, queue_id):
        """See IDistroReleaseQueueSet."""
        try:
            return DistroReleaseQueue.get(queue_id)
        except SQLObjectNotFound:
            raise NotFoundError(queue_id)

    def get(self, queue_id):
        """See IDistroReleaseQueueSet."""
        try:
            return DistroReleaseQueue.get(queue_id)
        except SQLObjectNotFound:
            raise NotFoundError(queue_id)

    def count(self, status=None, distrorelease=None):
        """See IDistroReleaseQueueSet."""
        clauses = []
        if status:
            clauses.append("status=%s" % sqlvalues(status))

        if distrorelease:
            clauses.append("distrorelease=%s" % sqlvalues(distrorelease.id))

        query = " AND ".join(clauses)
        # XXX: bug #29647, select("") issues an empty where so I use
        # this or None crap -- kiko, 2006-01-25
        return DistroReleaseQueue.select(query or None).count()

