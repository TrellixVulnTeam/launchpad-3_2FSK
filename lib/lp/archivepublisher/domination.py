# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Archive Domination class.

We call 'domination' the procedure used to identify and supersede all
old versions for a given publication, source or binary, inside a suite
(distroseries + pocket, for instance, gutsy or gutsy-updates).

It also processes the superseded publications and makes the ones with
unnecessary files 'eligible for removal', which will then be considered
for archive removal.  See deathrow.py.

In order to judge if a source is 'eligible for removal' it also checks
if its resulting binaries are not necessary any more in the archive, i.e.,
old binary publications can (and should) hold sources in the archive.

Source version life-cycle example:

  * foo_2.1: currently published, source and binary files live in the archive
             pool and it is listed in the archive indexes.

  * foo_2.0: superseded, it's not listed in archive indexes but one of its
             files is used for foo_2.1 (the orig.tar.gz) or foo_2.1 could
             not build for one or more architectures that foo_2.0 could;

  * foo_1.8: eligible for removal, none of its files are required in the
             archive since foo_2.0 was published (new orig.tar.gz) and none
             of its binaries are published (foo_2.0 was completely built)

  * foo_1.0: removed, it already passed through the quarantine period and its
             files got removed from the archive.

Note that:

  * PUBLISHED and SUPERSEDED are publishing statuses.

  * 'eligible for removal' is a combination of SUPERSEDED or DELETED
    publishing status and a defined (non-empty) 'scheduleddeletiondate'.

  * 'removed' is a combination of 'eligible for removal' and a defined
    (non-empy) 'dateremoved'.

The 'domination' procedure is the 2nd step of the publication pipeline and
it is performed for each suite using:

  * judgeAndDominate(distroseries, pocket, pubconfig)

"""

__metaclass__ = type

__all__ = ['Dominator']

from datetime import timedelta
import functools
import gc
import operator

import apt_pkg

from lp.archivepublisher import ELIGIBLE_DOMINATION_STATES
from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import (
    sqlvalues, flush_database_updates, cursor,
    clear_current_connection_cache)

from canonical.launchpad.interfaces import PackagePublishingStatus
from lp.soyuz.interfaces.binarypackagerelease import BinaryPackageFormat


def clear_cache():
    """Flush SQLObject updates and clear the cache."""
    # Flush them anyway, should basically be a noop thanks to not doing
    # lazyUpdate.
    flush_database_updates()
    clear_current_connection_cache()
    gc.collect()


# Ugly, but works
apt_pkg.InitSystem()


def _compare_packages_by_version_and_date(get_release, p1, p2):
    """Compare publications p1 and p2 by their version; using Debian rules.

    If the publications are for the same package, compare by datecreated
    instead. This lets newer records win.
    """
    if get_release(p1).id == get_release(p2).id:
        return cmp(p1.datecreated, p2.datecreated)

    return apt_pkg.VersionCompare(get_release(p1).version,
                                  get_release(p2).version)


class Dominator:
    """ Manage the process of marking packages as superseded.

    Packages are marked as superseded when they become obsolete.
    """

    def __init__(self, logger, archive):
        """Initialise the dominator.

        This process should be run after the publisher has published
        new stuff into the distribution but before the publisher
        creates the file lists for apt-ftparchive.
        """
        self._logger = logger
        self.archive = archive
        self.debug = self._logger.debug

    def _dominatePublications(self, pubs):
        """Perform dominations for the given publications.

        :param pubs: A dict mapping names to a list of publications. Every
            publication must be PUBLISHED or PENDING, and the first in each
            list will be treated as dominant (so should be the latest).
        """
        self.debug("Dominating packages...")

        for name in pubs.keys():
            assert pubs[name], (
                "Empty list of publications for %s" % name)
            for pubrec in pubs[name][1:]:
                pubrec.supersede(pubs[name][0], self)

    def _sortPackages(self, pkglist, is_source=True):
        # pkglist is a list of packages with the following
        #  * sourcepackagename or packagename as appropriate
        #  * version
        #  * status
        # Don't care about any other attributes
        outpkgs = {}

        self.debug("Sorting packages...")

        attr_prefix = 'source' if is_source else 'binary'
        get_release = operator.attrgetter(attr_prefix + 'packagerelease')
        get_name = operator.attrgetter(attr_prefix + 'packagename')

        for inpkg in pkglist:
            L = outpkgs.setdefault(
                get_name(get_release(inpkg)).name.encode('utf-8'), [])
            L.append(inpkg)

        for pkgname in outpkgs:
            if len(outpkgs[pkgname]) > 1:
                outpkgs[pkgname].sort(
                    functools.partial(
                        _compare_packages_by_version_and_date, get_release))
                outpkgs[pkgname].reverse()

        return outpkgs

    def _setScheduledDeletionDate(self, pub_record, conf):
        """Set the scheduleddeletiondate on a publishing record.

        If the status is DELETED we set the date to UTC_NOW, otherwise
        it gets the configured stay of execution period.
        """
        if pub_record.status == PackagePublishingStatus.DELETED:
            pub_record.scheduleddeletiondate = UTC_NOW
        else:
            pub_record.scheduleddeletiondate = (
                UTC_NOW + timedelta(days=conf.stayofexecution))

    def _judgeSuperseded(self, source_records, binary_records, conf):
        """Determine whether the superseded packages supplied should
        be moved to death row or not.

        Currently this is done by assuming that any superseded binary
        package should be removed. In the future this should attempt
        to supersede binaries in build-sized chunks only, bug 55030.

        Superseded source packages are considered removable when they
        have no binaries in this distroseries which are published or
        superseded

        When a package is considered for death row it is given a
        'scheduled deletion date' of now plus the defined 'stay of execution'
        time provided in the configuration parameter.
        """
        # Avoid circular imports.
        from lp.soyuz.model.publishing import (
            BinaryPackagePublishingHistory,
            SourcePackagePublishingHistory)

        self.debug("Beginning superseded processing...")

        # XXX: dsilvers 2005-09-22 bug=55030:
        # Need to make binaries go in groups but for now this'll do.
        # An example of the concrete problem here is:
        # - Upload foo-1.0, which builds foo and foo-common (arch all).
        # - Upload foo-1.1, ditto.
        # - foo-common-1.1 is built (along with the i386 binary for foo)
        # - foo-common-1.0 is superseded
        # Foo is now uninstallable on any architectures which don't yet
        # have a build of foo-1.1, as the foo-common for foo-1.0 is gone.

        # Essentially we ideally don't want to lose superseded binaries
        # unless the entire group is ready to be made pending removal.
        # In this instance a group is defined as all the binaries from a
        # given build. This assumes we've copied the arch_all binaries
        # from whichever build provided them into each arch-specific build
        # which we publish. If instead we simply publish the arch-all
        # binaries from another build then instead we should scan up from
        # the binary to its source, and then back from the source to each
        # binary published in *this* distroarchseries for that source.
        # if the binaries as a group (in that definition) are all superseded
        # then we can consider them eligible for removal.
        for pub_record in binary_records:
            binpkg_release = pub_record.binarypackagerelease
            self.debug("%s/%s (%s) has been judged eligible for removal" %
                       (binpkg_release.binarypackagename.name,
                        binpkg_release.version,
                        pub_record.distroarchseries.architecturetag))
            self._setScheduledDeletionDate(pub_record, conf)
            # XXX cprov 20070820: 'datemadepending' is useless, since it's
            # always equals to "scheduleddeletiondate - quarantine".
            pub_record.datemadepending = UTC_NOW

        for pub_record in source_records:
            srcpkg_release = pub_record.sourcepackagerelease
            # Attempt to find all binaries of this
            # SourcePackageRelease which are/have been in this
            # distroseries...
            considered_binaries = BinaryPackagePublishingHistory.select("""
            binarypackagepublishinghistory.distroarchseries =
                distroarchseries.id AND
            binarypackagepublishinghistory.scheduleddeletiondate IS NULL AND
            binarypackagepublishinghistory.archive = %s AND
            binarypackagebuild.source_package_release = %s AND
            distroarchseries.distroseries = %s AND
            binarypackagepublishinghistory.binarypackagerelease =
            binarypackagerelease.id AND
            binarypackagerelease.build = binarypackagebuild.id AND
            binarypackagepublishinghistory.pocket = %s
            """ % sqlvalues(self.archive, srcpkg_release,
                            pub_record.distroseries, pub_record.pocket),
            clauseTables=['DistroArchSeries', 'BinaryPackageRelease',
                          'BinaryPackageBuild'])

            # There is at least one non-removed binary to consider
            if considered_binaries.count() > 0:
                # However we can still remove *this* record if there's
                # at least one other PUBLISHED for the spr. This happens
                # when a package is moved between components.
                published = SourcePackagePublishingHistory.selectBy(
                    distroseries=pub_record.distroseries,
                    pocket=pub_record.pocket,
                    status=PackagePublishingStatus.PUBLISHED,
                    archive=self.archive,
                    sourcepackagereleaseID=srcpkg_release.id)
                # Zero PUBLISHED for this spr, so nothing to take over
                # for us, so leave it for consideration next time.
                if published.count() == 0:
                    continue

            # Okay, so there's no unremoved binaries, let's go for it...
            self.debug(
                "%s/%s (%s) source has been judged eligible for removal" %
                (srcpkg_release.sourcepackagename.name,
                 srcpkg_release.version, pub_record.id))
            self._setScheduledDeletionDate(pub_record, conf)
            # XXX cprov 20070820: 'datemadepending' is pointless, since it's
            # always equals to "scheduleddeletiondate - quarantine".
            pub_record.datemadepending = UTC_NOW

    def judgeAndDominate(self, dr, pocket, config, do_clear_cache=True):
        """Perform the domination and superseding calculations

        It only works across the distroseries and pocket specified.
        """
        # Avoid circular imports.
        from lp.soyuz.model.publishing import (
             BinaryPackagePublishingHistory,
             SourcePackagePublishingHistory)

        for distroarchseries in dr.architectures:
            self.debug("Performing domination across %s/%s (%s)" % (
                dr.name, pocket.title, distroarchseries.architecturetag))

            # Here we go behind SQLObject's back to generate an assistance
            # table which will seriously improve the performance of this
            # part of the publisher.
            # XXX: dsilvers 2006-02-04: It would be nice to not have to do
            # this. Most of this methodology is stolen from person.py
            # XXX: malcc 2006-08-03: This should go away when we shift to
            # doing this one package at a time.
            flush_database_updates()
            cur = cursor()
            cur.execute("""SELECT bpn.id AS name, count(bpn.id) AS count INTO
                temporary table PubDomHelper FROM BinaryPackageRelease bpr,
                BinaryPackageName bpn, BinaryPackagePublishingHistory
                sbpph WHERE bpr.binarypackagename = bpn.id AND
                sbpph.binarypackagerelease = bpr.id AND
                sbpph.distroarchseries = %s AND sbpph.archive = %s AND
                sbpph.status = %s AND sbpph.pocket = %s
                GROUP BY bpn.id""" % sqlvalues(
                distroarchseries, self.archive,
                PackagePublishingStatus.PUBLISHED, pocket))

            binaries = BinaryPackagePublishingHistory.select(
                """
                binarypackagepublishinghistory.distroarchseries = %s
                AND binarypackagepublishinghistory.archive = %s
                AND binarypackagepublishinghistory.pocket = %s
                AND binarypackagepublishinghistory.status = %s AND
                binarypackagepublishinghistory.binarypackagerelease =
                    binarypackagerelease.id
                AND binarypackagerelease.binpackageformat != %s
                AND binarypackagerelease.binarypackagename IN (
                    SELECT name FROM PubDomHelper WHERE count > 1)"""
                % sqlvalues(distroarchseries, self.archive,
                            pocket, PackagePublishingStatus.PUBLISHED,
                            BinaryPackageFormat.DDEB),
                clauseTables=['BinaryPackageRelease'])

            self.debug("Dominating binaries...")
            self._dominatePublications(self._sortPackages(binaries, False))
            if do_clear_cache:
                self.debug("Flushing SQLObject cache.")
                clear_cache()

            flush_database_updates()
            cur.execute("DROP TABLE PubDomHelper")

        if do_clear_cache:
            self.debug("Flushing SQLObject cache.")
            clear_cache()

        self.debug("Performing domination across %s/%s (Source)" %
                   (dr.name, pocket.title))
        sources = SourcePackagePublishingHistory.selectBy(
            distroseries=dr, archive=self.archive, pocket=pocket,
            status=PackagePublishingStatus.PUBLISHED)
        self.debug("Dominating sources...")
        self._dominatePublications(self._sortPackages(sources))
        flush_database_updates()

        sources = SourcePackagePublishingHistory.select("""
            sourcepackagepublishinghistory.distroseries = %s AND
            sourcepackagepublishinghistory.archive = %s AND
            sourcepackagepublishinghistory.pocket = %s AND
            sourcepackagepublishinghistory.status IN %s AND
            sourcepackagepublishinghistory.scheduleddeletiondate is NULL
            """ % sqlvalues(dr, self.archive, pocket,
                            ELIGIBLE_DOMINATION_STATES))

        binaries = BinaryPackagePublishingHistory.select("""
            binarypackagepublishinghistory.distroarchseries =
                distroarchseries.id AND
            distroarchseries.distroseries = %s AND
            binarypackagepublishinghistory.archive = %s AND
            binarypackagepublishinghistory.pocket = %s AND
            binarypackagepublishinghistory.status IN %s AND
            binarypackagepublishinghistory.scheduleddeletiondate is NULL
            """ % sqlvalues(dr, self.archive, pocket,
                            ELIGIBLE_DOMINATION_STATES),
            clauseTables=['DistroArchSeries'])

        self._judgeSuperseded(sources, binaries, config)

        self.debug("Domination for %s/%s finished" %
                   (dr.name, pocket.title))
