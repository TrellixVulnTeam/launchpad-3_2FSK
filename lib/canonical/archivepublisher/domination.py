# (c) Canonical Software Ltd. 2004, all rights reserved.
#
# This is the python package that defines the
# 'canonical.archivepublisher.domination' package. This package is
# related to the domination of old source and binary releases inside
# the publishing tables.

from canonical.lp.dbschema import PackagePublishingStatus

from canonical.database.constants import UTC_NOW

# Importing from canonical.launchpad.database will cause a circular import
# because we import from this file into database/distributionmirror.py
from canonical.launchpad.database.publishing import (
     BinaryPackagePublishingHistory, SecureSourcePackagePublishingHistory,
     SecureBinaryPackagePublishingHistory)

from canonical.database.sqlbase import (
    sqlvalues, flush_database_updates, cursor,
    clear_current_connection_cache)

import gc
import apt_pkg

def clear_cache():
    """Flush SQLObject updates and clear the cache."""
    # Flush them anyway, should basically be a noop thanks to not doing
    # lazyUpdate.
    flush_database_updates()
    clear_current_connection_cache()
    gc.collect()

PENDING = PackagePublishingStatus.PENDING
PUBLISHED = PackagePublishingStatus.PUBLISHED
SUPERSEDED = PackagePublishingStatus.SUPERSEDED
PENDINGREMOVAL = PackagePublishingStatus.PENDINGREMOVAL

# For stayofexecution processing in judgeSuperseded
from datetime import timedelta

# Ugly, but works
apt_pkg.InitSystem()

def _compare_source_packages_by_version_and_date(p1, p2):
    """Compare packages p1 and p2 by their version; using Debian rules.
    
    If the comparison is the same sourcepackagerelease, compare by datecreated
    instead. So later records beat earlier ones.
    """
    if p1.sourcepackagerelease.id == p2.sourcepackagerelease.id:
        return cmp(p1.datecreated, p2.datecreated)
    
    return apt_pkg.VersionCompare(p1.sourcepackagerelease.version,
                                  p2.sourcepackagerelease.version)

def _compare_binary_packages_by_version_and_date(p1, p2):
    """Compare packages p1 and p2 by their version; using Debian rules
    
    If the comparison is the same binarypackagerelease, compare by datecreated
    instead. So later records beat earlier ones.
    """
    if p1.binarypackagerelease.id == p2.binarypackagerelease.id:
        return cmp(p1.datecreated, p2.datecreated)

    return apt_pkg.VersionCompare(p1.binarypackagerelease.version,
                                  p2.binarypackagerelease.version)

class Dominator(object):
    """
    Manage the process of marking packages as superseded in the publishing
    tables as and when they become obsolete.
    """

    def __init__(self, logger):
        """
        Initialise the dominator. This process should be run after the
        publisher has published new stuff into the distribution but before
        the publisher creates the file lists for apt-ftparchive
        """
        object.__init__(self)
        self._logger = logger
        self.debug = self._logger.debug

    def _dominateSource(self, sourceinput):
        """
        Perform dominations for source.
        """

        self.debug("Dominating sources...")

        for source in sourceinput:
            # source is a list of versions ordered most-recent-first
            # basically skip the first entry because that is
            # never dominated by us, then just set subsequent entries
            # to SUPERSEDED unless they're already there or pending
            # removal

            # XXX: what happens when sourceinput[source] is None, or can
            # we assert it's not None?
            #   -- kiko, 2005-09-23
            super_release = sourceinput[source][0].sourcepackagerelease
            super_release_name = super_release.sourcepackagename.name
            for pubrec in sourceinput[source][1:]:
                if pubrec.status == PUBLISHED or pubrec.status == PENDING:
                    this_release = pubrec.sourcepackagerelease

                    this_release_name = this_release.sourcepackagename.name
                    self.debug("%s/%s has been judged as superseded by %s/%s" %
                               (this_release_name, this_release.version,
                                super_release_name, super_release.version))

                    pubrec.status = SUPERSEDED;
                    pubrec.datesuperseded = UTC_NOW;
                    pubrec.supersededby = super_release

    def _dominateBinary(self, binaryinput):
        """
        Perform dominations for binaries.
        """

        self.debug("Dominating binaries...")

        for binary in binaryinput:
            # XXX dsilvers 2004-11-11 This needs work. Unfortunately I'm not
            # completely sure how to correct for this.
            # For now; treat domination of binaries the same as for source
            # I.E. dominate by name only and highest version wins.

            # binary is a list of versions ordered most-recent-first
            # basically skip the first entry because that is
            # never dominated by us, then just set subsequent entries
            # to SUPERSEDED unless they're already there or pending
            # removal
            dominantrelease = binaryinput[binary][0].binarypackagerelease
            for pubrec in binaryinput[binary][1:]:
                if pubrec.status == PUBLISHED or pubrec.status == PENDING:
                    thisrelease = pubrec.binarypackagerelease
                    self.debug("The %s build of %s/%s has been judged "
                               "as superseded by the %s build of %s/%s.  "
                               "Arch-specific == %s" % (
                        thisrelease.build.distroarchrelease.architecturetag,
                        thisrelease.binarypackagename.name,
                        thisrelease.version,
                        dominantrelease.build.distroarchrelease.architecturetag,
                        dominantrelease.binarypackagename.name,
                        dominantrelease.version,
                        thisrelease.architecturespecific))
                    pubrec.status = SUPERSEDED;
                    pubrec.datesuperseded = UTC_NOW;
                    # XXX is this really .build? When superseding above
                    # we set supersededby = super_release..
                    #   -- kiko, 2005-09-23
                    pubrec.supersededby = dominantrelease.build


    def _sortPackages(self, pkglist, isSource = True):
        # pkglist is a list of packages with the following
        #  * sourcepackagename or packagename as appropriate
        #  * version
        #  * status
        # Don't care about any other attributes
        outpkgs = {}

        if isSource:
            self.debug("Sorting sources...")
        else:
            self.debug("Sorting binaries...")
        

        for inpkg in pkglist:
            if isSource:
                L = outpkgs.setdefault(
                    inpkg.sourcepackagerelease.sourcepackagename.name.encode(
                    'utf-8'), [])
            else:
                L = outpkgs.setdefault(
                    inpkg.binarypackagerelease.binarypackagename.name.encode(
                    'utf-8'), [])

            L.append(inpkg)

        for pkgname in outpkgs:
            if len(outpkgs[pkgname]) > 1:
                if isSource:
                    outpkgs[pkgname].sort(_compare_source_packages_by_version_and_date)
                else:
                    outpkgs[pkgname].sort(_compare_binary_packages_by_version_and_date)
                    
                outpkgs[pkgname].reverse()

        return outpkgs

    def _judgeSuperseded(self, source_records, binary_records, conf):
        """Determine whether the superseded packages supplied should
        be moved to death row or not.

        Currently this is done by assuming that any superseded binary
        package should be removed. In the future this should attempt
        to supersede binaries in build-sized chunks only.

        Superseded source packages are considered removable when they
        have no binaries in this distrorelease which are published or
        superseded

        When a package is considered for death row its status in the
        publishing table is set to PENDINGREMOVAL and the
        datemadepending is set to now.

        The package is then given a scheduled deletion date of now
        plus the defined stay of execution time provided in the
        configuration parameter.
        """

        self.debug("Beginning superseded processing...")

        # XXX: dsilvers: 20050922: Need to make binaries go in groups
        # but for now this'll do.
        # Essentially we ideally don't want to lose superseded binaries
        # unless the entire group is ready to be made pending removal.
        # In this instance a group is defined as all the binaries from a
        # given build. This assumes we've copied the arch_all binaries
        # from whichever build provided them into each arch-specific build
        # which we publish. If instead we simply publish the arch-all
        # binaries from another build then instead we should scan up from
        # the binary to its source, and then back from the source to each
        # binary published in *this* distroarchrelease for that source.
        # if the binaries as a group (in that definition) are all superseded
        # then we can consider them eligible for removal.
        for pub_record in binary_records:
            binpkg_release = pub_record.binarypackagerelease
            if pub_record.status == SUPERSEDED:
                self.debug("%s/%s (%s) has been judged eligible for removal" %
                           (binpkg_release.binarypackagename.name,
                            binpkg_release.version,
                            pub_record.distroarchrelease.architecturetag))
                pub_record.status = PENDINGREMOVAL
                pub_record.scheduleddeletiondate = UTC_NOW + \
                                          timedelta(days=conf.stayofexecution)
                pub_record.datemadepending = UTC_NOW

        for pub_record in source_records:
            srcpkg_release = pub_record.sourcepackagerelease
            if pub_record.status == SUPERSEDED:
                # Attempt to find all binaries of this
                # SourcePackageReleace which are/have been in this
                # distrorelease...
                considered_binaries = BinaryPackagePublishingHistory.select('''
                    (binarypackagepublishinghistory.status = %s OR
                     binarypackagepublishinghistory.status = %s OR
                     binarypackagepublishinghistory.status = %s) AND
                    binarypackagepublishinghistory.distroarchrelease =
                        distroarchrelease.id AND
                    distroarchrelease.distrorelease = %s AND
                    binarypackagepublishinghistory.binarypackagerelease =
                        binarypackagerelease.id AND
                    binarypackagerelease.build = build.id AND
                    build.sourcepackagerelease = %s AND
                    binarypackagepublishinghistory.pocket = %s''' % sqlvalues(
                    PENDING, PUBLISHED, SUPERSEDED,
                    pub_record.distrorelease.id, srcpkg_release.id,
                    pub_record.pocket),
                    clauseTables=['DistroArchRelease', 'BinaryPackageRelease',
                                  'Build'])
                if considered_binaries.count() > 0:
                    # There is at least one non-removed binary to consider
                    self.debug("%s/%s (source) has at least %d non-removed "
                               "binaries as yet" % (
                        srcpkg_release.sourcepackagename.name,
                        srcpkg_release.version,
                        considered_binaries.count()))
                    # However we can still remove *this* record if there's
                    # at least one other PUBLISHED for the spr. This happens
                    # when a package is moved between components.
                    if SecureSourcePackagePublishingHistory.selectBy(
                        distroreleaseID=pub_record.distrorelease.id,
                        pocket=pub_record.pocket,
                        status=PackagePublishingStatus.PUBLISHED,
                        sourcepackagereleaseID=srcpkg_release.id).count() == 0:
                        # Zero PUBLISHED for this spr, so nothing to take over
                        # for us, so leave it for consideration next time.
                        continue

                # Okay, so there's no unremoved binaries, let's go for it...
                self.debug(
                    "%s/%s (source) has been judged eligible for removal" %
                           (srcpkg_release.sourcepackagename.name,
                            srcpkg_release.version))
                           
                pub_record.status = PENDINGREMOVAL
                pub_record.scheduleddeletiondate = UTC_NOW + \
                                          timedelta(days=conf.stayofexecution)
                pub_record.datemadepending = UTC_NOW


    def judgeAndDominate(self, dr, pocket, config, do_clear_cache=True):
        """Perform the domination and superseding calculations across the
        distrorelease and pocket specified."""
        

        self.debug("Performing domination across %s/%s (Source)" %
                   (dr.name, pocket.title))

        # We can use SecureSourcePackagePublishingHistory here because
        # the standard .selectBy automatically says that embargo
        # should be false.

        sources = SecureSourcePackagePublishingHistory.selectBy(
            distroreleaseID=dr.id, pocket=pocket,
            status=PackagePublishingStatus.PUBLISHED)

        self._dominateSource(self._sortPackages(sources))

        if do_clear_cache:
            self.debug("Flushing SQLObject cache.")
            clear_cache()

        for distroarchrelease in dr.architectures:
            self.debug("Performing domination across %s/%s (%s)" % (
                dr.name, pocket.title, distroarchrelease.architecturetag))

            # Here we go behind SQLObject's back to generate an assitance
            # table which will seriously improve the performance of this
            # part of the publisher.
            # XXX: dsilvers: 20060204: It would be nice to not have to do this.
            # Most of this methodology is stolen from person.py
            flush_database_updates()
            cur = cursor()
            cur.execute("""SELECT bpn.id AS name, count(bpn.id) AS count INTO
                temporary table PubDomHelper FROM BinaryPackageRelease bpr,
                BinaryPackageName bpn, SecureBinaryPackagePublishingHistory
                sbpph WHERE bpr.binarypackagename = bpn.id AND
                sbpph.binarypackagerelease = bpr.id AND
                sbpph.distroarchrelease = %s AND sbpph.status = %s
                AND sbpph.pocket = %s
                GROUP BY bpn.id""" % sqlvalues(
                distroarchrelease.id, PackagePublishingStatus.PUBLISHED,
                pocket))

            binaries = SecureBinaryPackagePublishingHistory.select(
                """
                securebinarypackagepublishinghistory.distroarchrelease = %s
                AND securebinarypackagepublishinghistory.pocket = %s
                AND securebinarypackagepublishinghistory.status = %s AND
                securebinarypackagepublishinghistory.binarypackagerelease =
                    binarypackagerelease.id
                AND binarypackagerelease.binarypackagename IN (
                    SELECT name FROM PubDomHelper WHERE count > 1)"""
                % sqlvalues (distroarchrelease.id, pocket,
                             PackagePublishingStatus.PUBLISHED),
                clauseTables=['BinaryPackageRelease'])
            
            self._dominateBinary(self._sortPackages(binaries, False))
            if do_clear_cache:
                self.debug("Flushing SQLObject cache.")
                clear_cache()

            flush_database_updates()
            cur.execute("DROP TABLE PubDomHelper")

        sources = SecureSourcePackagePublishingHistory.selectBy(
            distroreleaseID=dr.id, pocket=pocket,
            status=PackagePublishingStatus.SUPERSEDED)
        
        binaries = SecureBinaryPackagePublishingHistory.select("""
            securebinarypackagepublishinghistory.distroarchrelease =
                distroarchrelease.id AND
            distroarchrelease.distrorelease = %s AND
            securebinarypackagepublishinghistory.status = %s AND
            securebinarypackagepublishinghistory.pocket = %s""" %
            sqlvalues(dr.id, PackagePublishingStatus.SUPERSEDED, pocket),
            clauseTables=['DistroArchRelease'])

        self._judgeSuperseded(sources, binaries, config)
        
        self.debug("Domination for %s/%s finished" %
                   (dr.name, pocket.title))

