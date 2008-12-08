# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Browser views for Soyuz publishing records."""

__metaclass__ = type

__all__ = [
    'BinaryPublishingRecordView',
    'SourcePublicationURL',
    'SourcePublishingRecordSelectableView',
    'SourcePublishingRecordView',
    ]

from operator import attrgetter

from zope.interface import implements

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.interfaces import (
    IBinaryPackagePublishingHistory, ISourcePackagePublishingHistory)
from canonical.launchpad.webapp import (
    LaunchpadView, canonical_url)
from canonical.launchpad.interfaces import (
    BuildStatus, PackagePublishingStatus)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.interfaces import ICanonicalUrlData


class SourcePublicationURL:
    """Dynamic URL declaration for `ISourcePackagePublishingHistory`"""
    implements(ICanonicalUrlData)
    rootsite = None

    def __init__(self, context):
        self.context = context

    @property
    def inside(self):
        return self.context.archive

    @property
    def path(self):
        return u"+sourcepub/%s" % self.context.id


class BasePublishingRecordView(LaunchpadView):
    """Base Publishing view class."""

    @property
    def is_source(self):
        return ISourcePackagePublishingHistory.providedBy(self.context)

    @property
    def is_binary(self):
        return IBinaryPackagePublishingHistory.providedBy(self.context)

    # The reason we define the map below outside the only function that uses
    # it (date_last_changed()) is that this allows us to test whether the map
    # covers all PackagePublishingStatus enumeration values.
    # The pertinent tests in doc/publishing-pages.txt will fail if we add a
    # new value to the PackagePublishingStatus enumeration but do not update
    # this map.
    timestamp_map = {
        PackagePublishingStatus.DELETED: 'dateremoved',
        PackagePublishingStatus.OBSOLETE: 'scheduleddeletiondate',
        PackagePublishingStatus.PENDING: 'datecreated',
        PackagePublishingStatus.PUBLISHED: 'datepublished',
        PackagePublishingStatus.SUPERSEDED: 'datesuperseded'
    }

    @property
    def date_last_changed(self):
        """Return the date of last change considering the publishing status.

        The date returned is as follows:
            * pending        -> datecreated
            * published      -> datepublished
            * superseded     -> datesuperseded
            * deleted        -> dateremoved
            * obsolete       -> scheduleddeletiondate
        """
        accessor = attrgetter(self.timestamp_map[self.context.status])
        return accessor(self.context)


    def wasDeleted(self):
        """Whether or not a publishing record deletion was requested.

        A publishing record deletion represents the explicit request from a
        archive-administrator (self.remove_by) to purge the published contents
        of this record from the archive for an arbitrary reason
        (self.removal_comment).
        """
        return self.context.status == PackagePublishingStatus.DELETED

    def wasSuperseded(self):
        """Whether or not a publishing record was superseded.

        'Superseded' means that a new and higher version of this package was
        uploaded/built after it was published or the publishing attributes
        (section, component, priority/urgency) was modified.
        """
        return self.context.supersededby is not None

    def isPendingRemoval(self):
        """Whether or not a publishing record is marked for removal.

        This package will be removed from the archive respecting the Soyuz
        'death row' quarantine period and the absence of file references in
        the target archive.
        """
        return self.context.scheduleddeletiondate is not None

    def isRemoved(self):
        """Whether or not a publishing records was removed from the archive.

        A publishing record (all files related to it) is removed from the
        archive disk once it pass through its quarantine period and it's not
        referred by any other archive publishing record.
        Archive removal represents the act of having its content purged from
        archive disk, such situation can be triggered for different status,
        each one representing a distinct step in the Soyuz publishing workflow:

         * SUPERSEDED -> the publication is not necessary since there is already
           a newer/higher/modified version available

         * DELETED -> the publishing was explicitly marked for removal by a
           archive-administrator, it's not wanted in the archive.

         * OBSOLETE -> the publication has become obsolete because its targeted
           distroseries has become obsolete (not supported by its developers).
        """
        return self.context.dateremoved is not None

    @property
    def js_connector(self):
        """Return the javascript glue for expandable rows mechanism."""
        return """
        <script type="text/javascript">
           registerLaunchpadFunction(function() {
               connect('pub%s-expander', 'onclick', function (e) {
                   toggleExpandableTableRow('pub%s');
                   });
               });
        </script>
        """ % (self.context.id, self.context.id)


class SourcePublishingRecordView(BasePublishingRecordView):
    """View class for `ISourcePackagePublishingHistory`."""
    __used_for__ = ISourcePackagePublishingHistory

    def wasCopied(self):
        """Whether or not a source is published in its original location.

        A source is not in its original location when:

         * The publishing `Archive` is not the same than where the source
            was uploaded. (SSPPH -> SPR -> Archive != SSPPH -> Archive).
        Or

          * The publishing `DistroSeries` is not the same than where the
            source was uploaded (SSPPH -> SPR -> DS != SSPPH -> DS).
        """
        source = self.context.sourcepackagerelease

        if self.context.archive != source.upload_archive:
            return True

        if self.context.distroseries != source.upload_distroseries:
            return True

        return False

    @property
    def allow_selection(self):
        """Do not render the checkbox corresponding to this record."""
        return False

    @property
    def published_source_and_binary_files(self):
        """Return list of dicts describing all files published
           for a certain source publication.
        """
        files = sorted(self.context.getSourceAndBinaryLibraryFiles(),
                       key=lambda l: l.filename)
        ret = []
        urls = set()
        for f in files:
            d = {}
            url = f.http_url
            if url in urls:
                # Don't print out the same file multiple times. This
                # actually happens for arch-all builds, and is
                # particularly irritating for PPAs.
                continue
            urls.add(url)
            d["url"] = url
            d["filename"] = f.filename
            d["filesize"] = f.content.filesize
            ret.append(d)
        return ret

    @property
    def built_packages(self):
        """Return a list of dictionaries with package names and their summary.

        For each built package from this published source, return a
        dictionary with keys "binarypackagename" and "summary", where
        the binarypackagename is unique (i.e. it ignores the same package
        published in more than one place/architecture.)
        """
        results = []
        packagenames = set()
        for pub in self.context.getPublishedBinaries():
            package = pub.binarypackagerelease
            packagename = package.binarypackagename.name
            if packagename not in packagenames:
                entry = {
                    "binarypackagename" : packagename,
                    "summary" : package.summary,
                    }
                results.append(entry)
                packagenames.add(packagename)
        return results

    @cachedproperty
    def builds(self):
        """Return a list of Builds for the context published source."""
        return list(self.context.getBuilds())

    @property
    def build_status(self):
        """Return the contents of the 'Built' column.

        If any build for this source is still PENDING or BUILDING, return the
        'build-building' icon, followed by the architectures building linking
        to their corresponding build pages.

        If all builds have quiesced and any of them has failed (
        FAILEDTOBUILD, MANUALDEPWAIT, CHROOTWAIT or FAILEDTOUPLOAD) return
        the 'no' icon, followed by the architectures where the source failed,
        also linking to their corresponding build page.

        Finally, if all builds have quiesced and none of them failed, return
        the 'yes' icon.
        """
        def content_template(desc, image, builds=None):
            icon = ('<img alt="%(desc)s" title="%(desc)s" '
                    'src="%(image)s" /> ') % {
                'desc': desc, 'image': image}
            if builds is None:
                return icon
            arch_links = []
            for build in builds:
                arch_tag = build.distroarchseries.architecturetag
                arch_links.append(
                    '<a href="%(url)s" title="%(title)s">%(arch_tag)s</a>' % {
                        'url': canonical_url(build),
                        'arch_tag': arch_tag,
                        'title': desc})
            return icon + " ".join(arch_links)

        def collect_builds(states):
            wanted = []
            for state in states:
                candidates = [build for build in self.builds
                              if build.buildstate == state]
                wanted.extend(candidates)
            return wanted

        failed_states = (
            BuildStatus.FAILEDTOBUILD, BuildStatus.MANUALDEPWAIT,
            BuildStatus.CHROOTWAIT, BuildStatus.FAILEDTOUPLOAD)

        pending_states = (
            BuildStatus.NEEDSBUILD, BuildStatus.BUILDING)

        failures = collect_builds(failed_states)
        pending = collect_builds(pending_states)

        if len(pending) != 0:
            return content_template(
                'Still building', '/@@/build-building', builds=pending)
        elif len(failures) != 0:
            return content_template(
                'Build failures', '/@@/no', builds=failures)
        else:
            return content_template('Built successfully', '/@@/yes')

    @property
    def linkify_source_archive(self):
        """Return True if the source's upload_archive should be linkified.

        The source archive is the upload_archive for any source that was
        copied.  It should be linkified only if it's a PPA and the user
        has permission to view that PPA.
        """
        archive = self.context.sourcepackagerelease.upload_archive

        if not archive.is_ppa:
            return False

        return check_permission('launchpad.View', archive)


class SourcePublishingRecordSelectableView(SourcePublishingRecordView):
    """View class for a selectable `ISourcePackagePublishingHistory`."""

    @property
    def allow_selection(self):
        """Allow the checkbox corresponding to this record to be rendered."""
        return True


class BinaryPublishingRecordView(BasePublishingRecordView):
    """View class for `IBinaryPackagePublishingHistory`."""
    __used_for__ = IBinaryPackagePublishingHistory

    def wasCopied(self):
        """Whether or not a binary is published in its original location.

        A binary is not in its original location when:

         * The publishing `Archive` is not the same than where the binary
           was built. (SBPPH -> BPR -> Build -> Archive != SBPPH -> Archive).
        Or

          * The publishing `DistroArchSeries` is not the same than where
            the binary was built (SBPPH -> BPR -> B -> DAS != SBPPH -> DAS).

        Or

          * The publishing pocket is not the same than where the binary was
            built (SBPPH -> BPR -> B -> Pocket != SBPPH -> Pocket).

        """
        build = self.context.binarypackagerelease.build

        if self.context.archive != build.archive:
            return True

        if self.context.distroarchseries != build.distroarchseries:
            return True

        if self.context.pocket != build.pocket:
            return True

        return False

