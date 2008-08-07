# Copyright 2004-2005 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = [
    'Revision', 'RevisionAuthor', 'RevisionParent', 'RevisionProperty',
    'RevisionSet']

from datetime import datetime, timedelta
import email

import pytz
from storm.expr import And, Asc, Desc, Exists, Not, Select
from storm.store import Store
from zope.component import getUtility
from zope.interface import implements
from sqlobject import (
    ForeignKey, IntCol, StringCol, SQLObjectNotFound, SQLMultipleJoin)

from canonical.database.sqlbase import quote, SQLBase, sqlvalues
from canonical.database.constants import DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.launchpad.interfaces import (
    EmailAddressStatus, IEmailAddressSet, IProduct, IProject,
    IRevision, IRevisionAuthor, IRevisionParent, IRevisionProperty,
    IRevisionSet)
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.validators.person import validate_public_person


class Revision(SQLBase):
    """See IRevision."""

    implements(IRevision)

    date_created = UtcDateTimeCol(notNull=True, default=DEFAULT)
    log_body = StringCol(notNull=True)
    gpgkey = ForeignKey(dbName='gpgkey', foreignKey='GPGKey', default=None)

    revision_author = ForeignKey(
        dbName='revision_author', foreignKey='RevisionAuthor', notNull=True)
    revision_id = StringCol(notNull=True, alternateID=True,
                            alternateMethodName='byRevisionID')
    revision_date = UtcDateTimeCol(notNull=False)

    properties = SQLMultipleJoin('RevisionProperty', joinColumn='revision')

    @property
    def parents(self):
        """See IRevision.parents"""
        return shortlist(RevisionParent.selectBy(
            revision=self, orderBy='sequence'))

    @property
    def parent_ids(self):
        """Sequence of globally unique ids for the parents of this revision.

        The corresponding Revision objects can be retrieved, if they are
        present in the database, using the RevisionSet Zope utility.
        """
        return [parent.parent_id for parent in self.parents]

    def getProperties(self):
        """See `IRevision`."""
        return dict((prop.name, prop.value) for prop in self.properties)

    def getBranch(self):
        """See `IRevision`."""
        from canonical.launchpad.database.branch import Branch
        from canonical.launchpad.database.branchrevision import BranchRevision

        store = Store.of(self)

        result_set = store.find(
            Branch,
            self.id == BranchRevision.revisionID,
            BranchRevision.branchID == Branch.id,
            Not(Branch.private))
        if self.revision_author.person is None:
            result_set.order_by(Asc(BranchRevision.sequence))
        else:
            result_set.order_by(
                Branch.ownerID != self.revision_author.personID,
                Asc(BranchRevision.sequence))

        return result_set.first()


class RevisionAuthor(SQLBase):
    implements(IRevisionAuthor)

    _table = 'RevisionAuthor'

    name = StringCol(notNull=True, alternateID=True)

    @property
    def name_without_email(self):
        """Return the name of the revision author without the email address.

        If there is no name information (i.e. when the revision author only
        supplied their email address), return None.
        """
        if '@' not in self.name:
            return self.name
        return email.Utils.parseaddr(self.name)[0]

    email = StringCol(notNull=False, default=None)
    person = ForeignKey(dbName='person', foreignKey='Person', notNull=False,
                        storm_validator=validate_public_person, default=None)

    def linkToLaunchpadPerson(self):
        """See `IRevisionAuthor`."""
        if self.person is not None or self.email is None:
            return False
        lp_email = getUtility(IEmailAddressSet).getByEmail(self.email)
        # If not found, we didn't link this person.
        if lp_email is None:
            return False
        # Only accept an email address that is validated.
        if lp_email.status != EmailAddressStatus.NEW:
            self.person = lp_email.person
            return True
        else:
            return False


class RevisionParent(SQLBase):
    """The association between a revision and its parent."""

    implements(IRevisionParent)

    _table = 'RevisionParent'

    revision = ForeignKey(
        dbName='revision', foreignKey='Revision', notNull=True)

    sequence = IntCol(notNull=True)
    parent_id = StringCol(notNull=True)


class RevisionProperty(SQLBase):
    """A property on a revision. See IRevisionProperty."""

    implements(IRevisionProperty)

    _table = 'RevisionProperty'

    revision = ForeignKey(
        dbName='revision', foreignKey='Revision', notNull=True)
    name = StringCol(notNull=True)
    value = StringCol(notNull=True)


class RevisionSet:

    implements(IRevisionSet)

    def getByRevisionId(self, revision_id):
        return Revision.selectOneBy(revision_id=revision_id)

    def _createRevisionAuthor(self, revision_author):
        """Extract out the email and check to see if it matches a Person."""
        email_address = email.Utils.parseaddr(revision_author)[1]
        # If there is no @, then it isn't a real email address.
        if '@' not in email_address:
            email_address = None

        author = RevisionAuthor(name=revision_author, email=email_address)
        author.linkToLaunchpadPerson()
        return author

    def new(self, revision_id, log_body, revision_date, revision_author,
            parent_ids, properties):
        """See IRevisionSet.new()"""
        if properties is None:
            properties = {}
        # create a RevisionAuthor if necessary:
        try:
            author = RevisionAuthor.byName(revision_author)
        except SQLObjectNotFound:
            author = self._createRevisionAuthor(revision_author)

        revision = Revision(revision_id=revision_id,
                            log_body=log_body,
                            revision_date=revision_date,
                            revision_author=author)
        seen_parents = set()
        for sequence, parent_id in enumerate(parent_ids):
            if parent_id in seen_parents:
                continue
            seen_parents.add(parent_id)
            RevisionParent(revision=revision, sequence=sequence,
                           parent_id=parent_id)

        # Create revision properties.
        for name, value in properties.iteritems():
            RevisionProperty(revision=revision, name=name, value=value)

        return revision

    def checkNewVerifiedEmail(self, email):
        """See `IRevisionSet`."""
        from zope.security.proxy import removeSecurityProxy
        # Bypass zope's security because IEmailAddress.email is not public.
        naked_email = removeSecurityProxy(email)
        for author in RevisionAuthor.selectBy(email=naked_email.email):
            author.person = email.person

    def getTipRevisionsForBranches(self, branches):
        """See `IRevisionSet`."""
        # If there are no branch_ids, then return None.
        branch_ids = [branch.id for branch in branches]
        if not branch_ids:
            return None
        return Revision.select("""
            Branch.id in %s AND
            Revision.revision_id = Branch.last_scanned_id
            """ % quote(branch_ids),
            clauseTables=['Branch'], prejoins=['revision_author'])

    def getRecentRevisionsForProduct(self, product, days):
        """See `IRevisionSet`."""
        cut_off_date = datetime.now(pytz.UTC) - timedelta(days=days)
        return Revision.select("""
            Revision.id in (
                SELECT br.revision
                FROM BranchRevision br, Branch b
                WHERE br.branch = b.id
                AND b.product = %s)
            AND Revision.revision_date >= %s
            """ % sqlvalues(product, cut_off_date),
            prejoins=['revision_author'])

    @staticmethod
    def getPublicRevisionsForPerson(person):
        """See `IRevisionSet`."""
        # Here to stop circular imports.
        from canonical.launchpad.database.branch import Branch
        from canonical.launchpad.database.branchrevision import BranchRevision
        from canonical.launchpad.database.teammembership import (
            TeamParticipation)

        store = Store.of(person)

        if person.is_team:
            person_query = And(
                RevisionAuthor.personID == TeamParticipation.personID,
                TeamParticipation.team == person)
        else:
            person_query = RevisionAuthor.person == person

        result_set = store.find(
            Revision,
            Revision.revision_author == RevisionAuthor.id,
            person_query,
            Exists(
                Select(True,
                       And(BranchRevision.revision == Revision.id,
                           BranchRevision.branch == Branch.id,
                           Not(Branch.private)),
                       (Branch, BranchRevision))))
        return result_set.order_by(Desc(Revision.revision_date))

    @staticmethod
    def getPublicRevisionsForProject(project):
        """See `IRevisionSet`."""
        # Here to stop circular imports.
        from canonical.launchpad.database.branch import Branch
        from canonical.launchpad.database.product import Product
        from canonical.launchpad.database.branchrevision import BranchRevision

        store = Store.of(project)

        # Need to specify the query tables explicitly for the sub select so it
        # doesn't try to join against Revision.
        query_tables = [Branch, BranchRevision]
        if IProduct.providedBy(project):
            project_query = (Branch.product == project)
        elif IProject.providedBy(project):
            query_tables.append(Product)
            project_query = And(
                Product.project == project,
                Branch.product == Product.id)
        else:
            raise AssertionError(
                "project must provide either IProduct or IProject")

        result_set = store.find(
            Revision,
            Exists(
                Select(True,
                       And(BranchRevision.revision == Revision.id,
                           BranchRevision.branch == Branch.id,
                           Not(Branch.private),
                           project_query),
                       query_tables)))
        return result_set.order_by(Desc(Revision.revision_date))
