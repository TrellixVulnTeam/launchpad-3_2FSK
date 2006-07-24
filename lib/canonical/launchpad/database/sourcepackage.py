# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = [
    'SourcePackage',
    ]

import apt_pkg
# apt_pkg requires this sillyness
apt_pkg.InitSystem()

from warnings import warn

from zope.interface import implements

from sqlobject import SQLObjectNotFound

from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import flush_database_updates, sqlvalues

from canonical.lp.dbschema import (
    PackagingType, PackagePublishingPocket, BuildStatus,
    PackagePublishingStatus, TicketStatus)

from canonical.launchpad.helpers import shortlist
from canonical.launchpad.interfaces import (
    ISourcePackage, IHasBuildRecords, ITicketTarget,
    TICKET_STATUS_DEFAULT_SEARCH)
from canonical.launchpad.components.bugtarget import BugTargetBase

from canonical.launchpad.database.bugtask import BugTaskSet
from canonical.launchpad.database.packaging import Packaging
from canonical.launchpad.database.publishing import SourcePackagePublishing
from canonical.launchpad.database.sourcepackagerelease import (
    SourcePackageRelease)
from canonical.launchpad.database.supportcontact import SupportContact
from canonical.launchpad.database.potemplate import POTemplate
from canonical.launchpad.database.ticket import Ticket, TicketSet
from canonical.launchpad.database.distributionsourcepackagerelease import \
    DistributionSourcePackageRelease
from canonical.launchpad.database.distroreleasesourcepackagerelease import \
    DistroReleaseSourcePackageRelease
from canonical.launchpad.database.build import Build


def compare_version(a, b):
    """Safely compares the version of two source packages"""
    return apt_pkg.VersionCompare(a.version, b.version)


class SourcePackage(BugTargetBase):
    """A source package, e.g. apache2, in a distrorelease.  This object
    implements the MagicSourcePackage specification. It is not a true
    database object, but rather attempts to represent the concept of a
    source package in a distro release, with links to the relevant database
    objects.
    """

    implements(ISourcePackage, IHasBuildRecords, ITicketTarget)

    def __init__(self, sourcepackagename, distrorelease):
        self.sourcepackagename = sourcepackagename
        self.distrorelease = distrorelease

    def _get_ubuntu(self):
        # XXX: Ideally, it would be possible to just do
        # ubuntu = getUtility(ILaunchpadCelebrities).ubuntu
        # and not need this method. However, importd currently depends
        # on SourcePackage methods that require the ubuntu celebrity,
        # and given it does not execute_zcml_for_scripts, we are forced
        # here to do this hack instead of using components. Ideally,
        # imports is rewritten to not use SourcePackage, or it
        # initializes the component architecture correctly.
        from canonical.launchpad.database.distribution import Distribution
        return Distribution.byName("ubuntu")

    @property
    def currentrelease(self):
        pkg = SourcePackagePublishing.selectFirst("""
            SourcePackagePublishing.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename = %s AND
            SourcePackagePublishing.distrorelease = %s
            """ % sqlvalues(self.sourcepackagename.id,
                            self.distrorelease.id),
            orderBy='-datepublished',
            clauseTables=['SourcePackageRelease'])
        if pkg is None:
            return None
        currentrelease = DistroReleaseSourcePackageRelease(
            distrorelease=self.distrorelease,
            sourcepackagerelease=pkg.sourcepackagerelease)
        return currentrelease

    def __getitem__(self, version):
        """See ISourcePackage."""
        pkg = SourcePackagePublishing.selectFirst("""
            SourcePackagePublishing.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.version = %s AND
            SourcePackageRelease.sourcepackagename = %s AND
            SourcePackagePublishing.distrorelease = %s
            """ % sqlvalues(version, self.sourcepackagename.id,
                            self.distrorelease.id),
            orderBy='-datepublished',
            clauseTables=['SourcePackageRelease'])
        if pkg is None:
            return None
        return DistroReleaseSourcePackageRelease(
            self.distrorelease, pkg.sourcepackagerelease)

    @property
    def displayname(self):
        return "%s %s" % (
            self.distrorelease.displayname, self.sourcepackagename.name)

    @property
    def title(self):
        titlestr = self.sourcepackagename.name
        titlestr += ' in ' + self.distribution.displayname
        titlestr += ' ' + self.distrorelease.displayname
        return titlestr

    @property
    def distribution(self):
        return self.distrorelease.distribution

    @property
    def format(self):
        if not self.currentrelease:
            return None
        return self.currentrelease.format

    @property
    def changelog(self):
        """See ISourcePackage"""

        clauseTables = ('SourcePackageName', 'SourcePackageRelease',
                        'SourcePackagePublishing','DistroRelease')

        query = ('SourcePackageRelease.sourcepackagename = '
                 'SourcePackageName.id AND '
                 'SourcePackageName = %d AND '
                 'SourcePackagePublishing.distrorelease = '
                 'DistroRelease.Id AND '
                 'SourcePackagePublishing.distrorelease = %d AND '
                 'SourcePackagePublishing.sourcepackagerelease = '
                 'SourcePackageRelease.id'
                 % (self.sourcepackagename.id,
                    self.distrorelease.id)
                 )

        spreleases = SourcePackageRelease.select(query,
                                                 clauseTables=clauseTables,
                                                 orderBy='version').reversed()
        changelog = ''

        for spr in spreleases:
            changelog += '%s \n\n' % spr.changelog

        return changelog

    @property
    def manifest(self):
        """For the moment, the manifest of a SourcePackage is defined as the
        manifest of the .currentrelease of that SourcePackage in the
        distrorelease. In future, we might have a separate table for the
        current working copy of the manifest for a source package.
        """
        if not self.currentrelease:
            return None
        return self.currentrelease.manifest

    @property
    def releases(self):
        """See ISourcePackage."""
        ret = SourcePackageRelease.select('''
            SourcePackageRelease.sourcepackagename = %d AND
            SourcePackagePublishingHistory.distrorelease = %d AND
            SourcePackagePublishingHistory.sourcepackagerelease =
                SourcePackageRelease.id
            ''' % (self.sourcepackagename.id, self.distrorelease.id),
            clauseTables=['SourcePackagePublishingHistory'])

        # sort by version number
        releases = sorted(shortlist(ret, longest_expected=15),
                          cmp=compare_version)
        return [DistributionSourcePackageRelease(
            distribution=self.distribution,
            sourcepackagerelease=release) for release in releases]

    @property
    def releasehistory(self):
        """See ISourcePackage."""
        ret = SourcePackageRelease.select('''
            SourcePackageRelease.sourcepackagename = %d AND
            SourcePackagePublishingHistory.distrorelease =
                DistroRelease.id AND
            DistroRelease.distribution = %d AND
            SourcePackagePublishingHistory.sourcepackagerelease =
                SourcePackageRelease.id
            ''' % (self.sourcepackagename.id, self.distribution.id),
            clauseTables=['DistroRelease', 'SourcePackagePublishingHistory'])

        # sort by debian version number
        return sorted(list(ret), cmp=compare_version)

    @property
    def name(self):
        return self.sourcepackagename.name

    @property
    def potemplates(self):
        result = POTemplate.selectBy(
            distroreleaseID=self.distrorelease.id,
            sourcepackagenameID=self.sourcepackagename.id)
        return sorted(list(result), key=lambda x: x.potemplatename.name)

    @property
    def currentpotemplates(self):
        result = POTemplate.selectBy(
            distroreleaseID=self.distrorelease.id,
            sourcepackagenameID=self.sourcepackagename.id,
            iscurrent=True)
        return sorted(list(result), key=lambda x: x.potemplatename.name)

    @property
    def product(self):
        # we have moved to focusing on productseries as the linker
        warn('SourcePackage.product is deprecated, use .productseries',
             DeprecationWarning, stacklevel=2)
        ps = self.productseries
        if ps is not None:
            return ps.product
        return None

    @property
    def productseries(self):
        # See if we can find a relevant packaging record
        packaging = self.packaging
        if packaging is None:
            return None
        return packaging.productseries

    @property
    def direct_packaging(self):
        """See ISourcePackage."""
        # get any packagings matching this sourcepackage
        return Packaging.selectFirstBy(
            sourcepackagenameID=self.sourcepackagename.id,
            distroreleaseID=self.distrorelease.id,
            orderBy='packaging')

    @property
    def packaging(self):
        """See ISourcePackage.packaging"""
        # First we look to see if there is packaging data for this
        # distrorelease and sourcepackagename. If not, we look up through
        # parent distroreleases, and when we hit Ubuntu, we look backwards in
        # time through Ubuntu releases till we find packaging information or
        # blow past the Warty Warthog.

        # see if there is a direct packaging
        result = self.direct_packaging
        if result is not None:
            return result

        ubuntu = self._get_ubuntu()
        # if we are an ubuntu sourcepackage, try the previous release of
        # ubuntu
        if self.distribution == ubuntu:
            ubuntureleases = self.distrorelease.previous_releases
            if ubuntureleases:
                previous_ubuntu_release = ubuntureleases[0]
                sp = SourcePackage(sourcepackagename=self.sourcepackagename,
                                   distrorelease=previous_ubuntu_release)
                return sp.packaging
        # if we have a parent distrorelease, try that
        if self.distrorelease.parentrelease is not None:
            sp = SourcePackage(sourcepackagename=self.sourcepackagename,
                               distrorelease=self.distrorelease.parentrelease)
            return sp.packaging
        # capitulate
        return None


    @property
    def shouldimport(self):
        """Note that this initial implementation of the method knows that we
        are only interested in importing ubuntu packages initially. Also, it
        knows that we should only import packages where the upstream
        revision control is in place and working.
        """

        ubuntu = self._get_ubuntu()
        if self.distribution != ubuntu:
            return False
        ps = self.productseries
        if ps is None:
            return False
        return ps.branch is not None

    @property
    def published_by_pocket(self):
        """See ISourcePackage."""
        result = SourcePackagePublishing.select("""
            SourcePackagePublishing.distrorelease = %s AND
            SourcePackagePublishing.sourcepackagerelease =
                SourcePackageRelease.id AND
            SourcePackageRelease.sourcepackagename = %s
            """ % sqlvalues(
                self.distrorelease.id,
                self.sourcepackagename.id),
            clauseTables=['SourcePackageRelease'])
        # create the dictionary with the set of pockets as keys
        thedict = {}
        for pocket in PackagePublishingPocket.items:
            thedict[pocket] = []
        # add all the sourcepackagereleases in the right place
        for spr in result:
            thedict[spr.pocket].append(DistroReleaseSourcePackageRelease(
                spr.distrorelease, spr.sourcepackagerelease))
        return thedict

    def searchTasks(self, search_params):
        """See canonical.launchpad.interfaces.IBugTarget."""
        search_params.setSourcePackage(self)
        return BugTaskSet().search(search_params)

    def getUsedBugTags(self):
        """See IBugTarget."""
        return self.distrorelease.getUsedBugTags()

    def createBug(self, bug_params):
        """See canonical.launchpad.interfaces.IBugTarget."""
        # We don't currently support opening a new bug directly on an
        # ISourcePackage, because internally ISourcePackage bugs mean bugs
        # targetted to be fixed in a specific distrorelease + sourcepackage.
        raise NotImplementedError(
            "A new bug cannot be filed directly on a source package in a "
            "specific distribution release, because releases are meant for "
            "\"targeting\" a fix to a specific release. It's possible that "
            "we may change this behaviour to allow filing a bug on a "
            "distribution release source package in the not-too-distant "
            "future. For now, you probably meant to file the bug on the "
            "distro-wide (i.e. not release-specific) source package.")

    def setPackaging(self, productseries, user):
        target = self.direct_packaging
        if target is not None:
            # we should update the current packaging
            target.productseries = productseries
            target.owner = user
            target.datecreated = UTC_NOW
        else:
            # ok, we need to create a new one
            Packaging(distrorelease=self.distrorelease,
            sourcepackagename=self.sourcepackagename,
            productseries=productseries, owner=user,
            packaging=PackagingType.PRIME)
        # and make sure this change is immediately available
        flush_database_updates()

    # ticket related interfaces
    def tickets(self, quantity=None):
        """See ITicketTarget."""
        ret = Ticket.select("""
            distribution = %s AND
            sourcepackagename = %s
            """ % sqlvalues(self.distribution.id,
                            self.sourcepackagename.id),
            orderBy='-datecreated',
            limit=quantity)
        return ret

    def newTicket(self, owner, title, description, datecreated=None):
        """See ITicketTarget."""
        return TicketSet.new(
            title=title, description=description, owner=owner,
            distribution=self.distribution,
            sourcepackagename=self.sourcepackagename, datecreated=datecreated)

    def getTicket(self, ticket_id):
        """See ITicketTarget."""
        # first see if there is a ticket with that number
        try:
            ticket = Ticket.get(ticket_id)
        except SQLObjectNotFound:
            return None
        # now verify that that ticket is actually for this target
        if ticket.distribution != self.distribution:
            return None
        if ticket.sourcepackagename != self.sourcepackagename:
            return None
        return ticket

    def searchTickets(self, search_text=None,
                      status=TICKET_STATUS_DEFAULT_SEARCH, sort=None):
        """See ITicketTarget."""
        return TicketSet.search(search_text=search_text, status=status,
                                sort=sort, distribution=self.distribution,
                                sourcepackagename=self.sourcepackagename)

    def addSupportContact(self, person):
        """See ITicketTarget."""
        if person in self.support_contacts:
            return False
        SupportContact(
            product=None, person=person.id,
            sourcepackagename=self.sourcepackagename.id,
            distribution=self.distribution.id)
        return True

    def removeSupportContact(self, person):
        """See ITicketTarget."""
        if person not in self.support_contacts:
            return False
        support_contact_entry = SupportContact.selectOneBy(
            distributionID=self.distribution.id,
            sourcepackagenameID=self.sourcepackagename.id,
            personID=person.id)
        support_contact_entry.destroySelf()
        return True

    @property
    def support_contacts(self):
        """See ITicketTarget."""
        support_contacts = SupportContact.selectBy(
            distributionID=self.distribution.id,
            sourcepackagenameID=self.sourcepackagename.id)

        return shortlist([
            support_contact.person for support_contact in support_contacts
            ],
            longest_expected=100)

    def __eq__(self, other):
        """See canonical.launchpad.interfaces.ISourcePackage."""
        return (
            (ISourcePackage.providedBy(other)) and
            (self.distrorelease.id == other.distrorelease.id) and
            (self.sourcepackagename.id == other.sourcepackagename.id))

    def __ne__(self, other):
        """See canonical.launchpad.interfaces.ISourcePackage."""
        return not self.__eq__(other)

    def getBuildRecords(self, status=None, name=None, pocket=None):
        """See IHasBuildRecords"""
        clauseTables = ['SourcePackageRelease',
                        'SourcePackagePublishingHistory']
        orderBy = ["-datebuilt"]

        condition_clauses = ["""
        Build.sourcepackagerelease = SourcePackageRelease.id AND
        SourcePackageRelease.sourcepackagename = %s AND
        SourcePackagePublishingHistory.distrorelease = %s AND
        SourcePackagePublishingHistory.status = %s AND
        SourcePackagePublishingHistory.sourcepackagerelease =
        SourcePackageRelease.id
        """ % sqlvalues(self.sourcepackagename.id, self.distrorelease.id,
                        PackagePublishingStatus.PUBLISHED)]

        # exclude gina-generated builds
        # buildstate == FULLYBUILT && datebuilt == null
        condition_clauses.append(
            "NOT (Build.buildstate=%s AND Build.datebuilt is NULL)"
            % sqlvalues(BuildStatus.FULLYBUILT))

        # XXX cprov 20060214: still not ordering ALL results (empty status)
        # properly, the pending builds will pre presented in the DESC
        # 'datebuilt' order. bug # 31392

        if status is not None:
            condition_clauses.append("Build.buildstate=%s"
                                     % sqlvalues(status))

        if pocket:
            condition_clauses.append(
                "Build.pocket = %s" % sqlvalues(pocket))

        # Order NEEDSBUILD by lastscore, it should present the build
        # in a more natural order.
        if status == BuildStatus.NEEDSBUILD:
            orderBy = ["-BuildQueue.lastscore"]
            clauseTables.append('BuildQueue')
            condition_clauses.append('BuildQueue.build = Build.id')

        return Build.select(' AND '.join(condition_clauses),
                            clauseTables=clauseTables, orderBy=orderBy)
