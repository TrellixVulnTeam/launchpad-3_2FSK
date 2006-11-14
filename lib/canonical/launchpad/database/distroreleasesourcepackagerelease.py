# Copyright 2005 Canonical Ltd.  All rights reserved.

"""Classes to represent source package releases in a distribution release."""

__metaclass__ = type

__all__ = [
    'DistroReleaseSourcePackageRelease',
    ]

from zope.interface import implements


from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import sqlvalues

from canonical.launchpad.database.build import Build
from canonical.launchpad.database.binarypackagerelease import (
    BinaryPackageRelease)
from canonical.launchpad.database.publishing import (
    SecureSourcePackagePublishingHistory, SourcePackagePublishingHistory)
from canonical.launchpad.database.queue import DistroReleaseQueue
from canonical.launchpad.interfaces import (
    IDistroReleaseSourcePackageRelease, NotFoundError)
from canonical.lp.dbschema import (
    PackagePublishingStatus, DistroReleaseQueueStatus)

class DistroReleaseSourcePackageRelease:
    """This is a "Magic SourcePackageRelease in Distro Release". It is not
    an SQLObject but instead it describes the behaviour of a specific
    release of the package in the distrorelease."""

    implements(IDistroReleaseSourcePackageRelease)

    def __init__(self, distrorelease, sourcepackagerelease):
        self.distrorelease = distrorelease
        self.sourcepackagerelease = sourcepackagerelease

    @property
    def name(self):
        """See IDistroReleaseSourcePackageRelease."""
        return self.sourcepackagerelease.sourcepackagename.name

    @property
    def version(self):
        """See IDistroReleaseSourcePackageRelease."""
        return self.sourcepackagerelease.version

    @property
    def distribution(self):
        """See IDistroReleaseSourcePackageRelease."""
        return self.distrorelease.distribution

    @property
    def displayname(self):
        """See IDistroReleaseSourcePackageRelease."""
        return '%s %s' % (self.name, self.version)

    @property
    def title(self):
        """See IDistroReleaseSourcePackageRelease."""
        return '%s %s (source) in %s %s' % (
            self.name, self.version, self.distribution.name,
            self.distrorelease.name)

    @property
    def current_publishing_record(self):
        """An internal property used by methods of this class to know where
        this release is or was published.
        """
        pub_hist = self.publishing_history
        if pub_hist.count() == 0:
            return None
        return pub_hist[0]

    @property
    def pocket(self):
        """See IDistroReleaseSourcePackageRelease."""
        currpub = self.current_publishing_record
        if currpub is None:
            return None
        return currpub.pocket

    @property
    def section(self):
        """See IDistroReleaseSourcePackageRelease."""
        currpub = self.current_publishing_record
        if currpub is None:
            return None
        return currpub.section

    @property
    def component(self):
        """See IDistroReleaseSourcePackageRelease."""
        currpub = self.current_publishing_record
        if currpub is None:
            return None
        return currpub.component

    @property
    def publishing_history(self):
        """See IDistroReleaseSourcePackage."""
        return SourcePackagePublishingHistory.select("""
            distrorelease = %s AND
            sourcepackagerelease = %s
            """ % sqlvalues(self.distrorelease.id,
                            self.sourcepackagerelease.id),
            orderBy='-datecreated')

    @property
    def builds(self):
        """See IDistroReleaseSourcePackageRelease."""
        return Build.select("""
            Build.sourcepackagerelease = %s AND
            Build.distroarchrelease = DistroArchRelease.id AND
            DistroArchRelease.distrorelease = %s
            """ % sqlvalues(self.sourcepackagerelease.id,
                            self.distrorelease.id),
            orderBy='-datecreated',
            clauseTables=['distroarchrelease'])

    @property
    def files(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.files

    @property
    def binaries(self):
        """See IDistroReleaseSourcePackageRelease."""
        clauseTables = [
            'SourcePackageRelease',
            'BinaryPackageRelease',
            'DistroArchRelease',
            'Build',
            'BinaryPackagePublishingHistory'
        ]

        query = """
        SourcePackageRelease.id=Build.sourcepackagerelease AND
        BinaryPackageRelease.build=Build.id AND
        DistroArchRelease.id=
            BinaryPackagePublishingHistory.distroarchrelease AND
        BinaryPackagePublishingHistory.binarypackagerelease=
            BinaryPackageRelease.id AND
        DistroArchRelease.distrorelease=%s AND
        Build.sourcepackagerelease=%s
        """ % sqlvalues(self.distrorelease.id, self.sourcepackagerelease.id)

        return BinaryPackageRelease.select(
                query, prejoinClauseTables=['Build'],
                clauseTables=clauseTables)

    @property
    def changesfile(self):
        """See IDistroReleaseSourcePackageRelease."""
        clauseTables = [
            'DistroReleaseQueue',
            'DistroReleaseQueueSource',
            ]
        query = """
        DistroReleaseQueue.id = DistroReleaseQueueSource.distroreleasequeue AND
        DistroReleaseQueue.distrorelease = %s AND
        DistroReleaseQueueSource.sourcepackagerelease = %s AND
        DistroReleaseQueue.status = %s
        """ % sqlvalues(self.distrorelease, self.sourcepackagerelease,
                        DistroReleaseQueueStatus.DONE)
        queue_record = DistroReleaseQueue.selectOne(
            query, clauseTables=clauseTables)

        if not queue_record:
            return None

        return queue_record.changesfile

    @property
    def builddepends(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.builddepends

    @property
    def builddependsindep(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.builddependsindep

    @property
    def architecturehintlist(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.architecturehintlist

    @property
    def dsc(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.dsc

    @property
    def format(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.format

    @property
    def urgency(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.urgency

    @property
    def changelog(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.changelog

    @property
    def uploaddistrorelease(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.uploaddistrorelease

    @property
    def dscsigningkey(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.dscsigningkey

    @property
    def dateuploaded(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.dateuploaded

    @property
    def sourcepackagename(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.sourcepackagename

    @property
    def manifest(self):
        """See ISourcePackageRelease."""
        return self.sourcepackagerelease.manifest

    @property
    def current_published(self):
        """See IDistroArchReleaseSourcePackage."""
        # Retrieve current publishing info
        current = SourcePackagePublishingHistory.selectFirst("""
        distrorelease = %s AND
        sourcepackagerelease = %s AND
        status = %s
        """ % sqlvalues(self.distrorelease.id,
                        self.sourcepackagerelease.id,
                        PackagePublishingStatus.PUBLISHED),
            orderBy='-datecreated')

        if current is None:
            raise NotFoundError("Source package %s not published in %s"
                                % (self.sourcepackagename.name,
                                   self.distrorelease.name))

        return current

    def changeOverride(self, new_component=None, new_section=None):
        """See IDistroReleaseSourcePackageRelease."""

        # Check we have been asked to do something
        if (new_component is None and
            new_section is None):
            raise AssertionError("changeOverride must be passed either a"
                                 " new component or new section")

        # Retrieve current publishing info
        current = self.current_published

        # Check there is a change to make
        if new_component is None:
            new_component = current.component
        if new_section is None:
            new_section = current.section

        if (new_component == current.component and
            new_section == current.section):
            return

        SecureSourcePackagePublishingHistory(
            distrorelease=current.distrorelease,
            sourcepackagerelease=current.sourcepackagerelease,
            status=PackagePublishingStatus.PENDING,
            datecreated=UTC_NOW,
            embargo=False,
            pocket=current.pocket,
            component=new_component,
            section=new_section,
        )

    def supersede(self):
        """See IDistroReleaseSourcePackageRelease."""
        # Retrieve current publishing info
        current = self.current_published
        current = SecureSourcePackagePublishingHistory.get(current.id)
        current.status = PackagePublishingStatus.SUPERSEDED
        current.datesuperseded = UTC_NOW

        return current

