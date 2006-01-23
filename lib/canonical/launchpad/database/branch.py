# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type
__all__ = ['Branch', 'BranchSet', 'BranchRelationship', 'BranchLabel']

from zope.interface import implements

from sqlobject import (
    ForeignKey, IntCol, StringCol, BoolCol, MultipleJoin, RelatedJoin)
from canonical.database.constants import UTC_NOW
from canonical.database.sqlbase import SQLBase, sqlvalues, quote, quote_like
from canonical.database.datetimecol import UtcDateTimeCol

from canonical.config import config
from canonical.launchpad.interfaces import IBranch, IBranchSet
from canonical.launchpad.database.revision import Revision, RevisionNumber
from canonical.launchpad.database.branchsubscription import BranchSubscription

from canonical.lp.dbschema import (
    EnumCol, BranchRelationships, BranchLifecycleStatus)


class Branch(SQLBase):
    """A sequence of ordered revisions in Bazaar."""

    implements(IBranch)

    _table = 'Branch'
    name = StringCol(notNull=False)
    title = StringCol(notNull=False)
    summary = StringCol(notNull=True)
    url = StringCol(dbName='url')
    whiteboard = StringCol(default=None)
    started_at = ForeignKey(
        dbName='started_at', foreignKey='RevisionNumber', default=None)

    owner = ForeignKey(dbName='owner', foreignKey='Person', notNull=True)
    author = ForeignKey(dbName='author', foreignKey='Person', default=None)

    product = ForeignKey(dbName='product', foreignKey='Product', default=None)
    branch_product_name = StringCol(default=None)
    product_locked = BoolCol(default=False, notNull=True)

    home_page = StringCol()
    branch_home_page = StringCol(default=None)
    home_page_locked = BoolCol(default=False, notNull=True)

    lifecycle_status = EnumCol(schema=BranchLifecycleStatus, notNull=True,
        default=BranchLifecycleStatus.NEW)

    landing_target = ForeignKey(
        dbName='landing_target', foreignKey='Branch', default=None)
    current_delta_url = StringCol(default=None)
    current_diff_adds = IntCol(default=None)
    current_diff_deletes = IntCol(default=None)
    current_conflicts_url = StringCol(default=None)
    current_activity = IntCol(default=0, notNull=True)
    stats_updated = UtcDateTimeCol(default=None)

    last_mirrored = UtcDateTimeCol(default=None)
    last_mirror_attempt = UtcDateTimeCol(default=None)
    mirror_failures = IntCol(default=0, notNull=True)
    pull_disabled = BoolCol(default=False, notNull=True)

    cache_url = StringCol(default=None)

    revision_history = MultipleJoin('RevisionNumber', joinColumn='branch',
        orderBy='-sequence')

    subjectRelations = MultipleJoin('BranchRelationship', joinColumn='subject')
    objectRelations = MultipleJoin('BranchRelationship', joinColumn='object')

    subscriptions = MultipleJoin(
        'BranchSubscription', joinColumn='branch', orderBy='id')
    subscribers = RelatedJoin(
        'Person', joinColumn='branch', otherColumn='person',
        intermediateTable='BranchSubscription', orderBy='name')

    @property
    def product_name(self):
        if self.product is None:
            return '+junk'
        return self.product.name

    def revision_count(self):
        return RevisionNumber.selectBy(branchID=self.id).count()

    def latest_revisions(self, quantity=10):
        return RevisionNumber.selectBy(
            branchID=self.id, orderBy='-sequence').limit(quantity)

    def revisions_since(self, timestamp):
        return RevisionNumber.select(
            'Revision.id=RevisionNumber.revision AND '
            'RevisionNumber.branch = %d AND '
            'Revision.revision_date > %s' %
            (self.id, quote(timestamp)),
            orderBy='-sequence',
            clauseTables=['Revision'])

    def createRelationship(self, branch, relationship):
        BranchRelationship(subject=self, object=branch, label=relationship)

    def getRelations(self):
        return tuple(self.subjectRelations) + tuple(self.objectRelations)

    # subscriptions
    def subscribe(self, person):
        """See IBranch."""
        for sub in self.subscriptions:
            if sub.person.id == person.id:
                return sub
        return BranchSubscription(branch=self, person=person)

    def unsubscribe(self, person):
        """See IBranch."""
        for sub in self.subscriptions:
            if sub.person.id == person.id:
                BranchSubscription.delete(sub.id)
                break

    def has_subscription(self, person):
        """See IBranch."""
        assert person is not None
        subscription = BranchSubscription.selectOneBy(
            personID=person.id, branchID=self.id)
        return subscription is not None


class BranchSet:
    """The set of all branches."""

    implements(IBranchSet)

    def __getitem__(self, branch_id):
        """See IBranchSet."""
        branch = self.get(branch_id)
        if branch is None:
            raise NotFoundError(branch_id)
        return branch

    def get(self, branch_id, default=None):
        """See IBranchSet."""
        try:
            return Branch.get(branch_id)
        except SQLObjectNotFound:
            return default

    def __iter__(self):
        """See IBranchSet."""
        return iter(Branch.select())

    def new(self, name, owner, product, url, title=None,
            lifecycle_status=BranchLifecycleStatus.NEW, author=None,
            summary=None, home_page=None):
        """See IBranchSet."""
        if not home_page:
            home_page = None
        return Branch(
            name=name, owner=owner, author=author, product=product, url=url,
            title=title, lifecycle_status=lifecycle_status, summary=summary,
            home_page=home_page)

    def get_supermirror_pull_queue(self):
        """See IBranchSet.get_supermirror_pull_queue."""
        supermirror_root = config.launchpad.supermirror_root
        assert quote(supermirror_root) == quote_like(supermirror_root)
        return Branch.select("(last_mirror_attempt is NULL "
                             " OR (%s - last_mirror_attempt > '1 day')) "
                             "AND NOT (url ILIKE '%s%%')"
                             % (UTC_NOW, supermirror_root))


class BranchRelationship(SQLBase):
    """A relationship between branches.

    e.g. "subject is a debianization-branch-of object"
    """

    _table = 'BranchRelationship'
    _columns = [
        ForeignKey(name='subject', foreignKey='Branch', dbName='subject', 
                   notNull=True),
        IntCol(name='label', dbName='label', notNull=True),
        ForeignKey(name='object', foreignKey='Branch', dbName='subject', 
                   notNull=True),
        ]

    def _get_src(self):
        return self.subject
    def _set_src(self, value):
        self.subject = value

    def _get_dst(self):
        return self.object
    def _set_dst(self, value):
        self.object = value

    def _get_labelText(self):
        return BranchRelationships.items[self.label]

    def nameSelector(self, sourcepackage=None, selected=None):
        # XXX: Let's get HTML out of the database code.
        #      -- SteveAlexander, 2005-04-22
        html = '<select name="binarypackagename">\n'
        if not sourcepackage:
            # Return nothing for an empty query.
            binpkgs = []
        else:
            binpkgs = self._table.select("""
                binarypackagename.id = binarypackage.binarypackagename AND
                binarypackage.build = build.id AND
                build.sourcepackagerelease = sourcepackagerelease.id AND
                sourcepackagerelease.sourcepackage = %s"""
                % sqlvalues(sourcepackage),
                clauseTables = ['binarypackagename', 'binarypackage',
                                'build', 'sourcepackagerelease']
                )
        for pkg in binpkgs:
            html = html + '<option value="' + pkg.name + '"'
            if pkg.name==selected: html = html + ' selected'
            html = html + '>' + pkg.name + '</option>\n'
        html = html + '</select>\n'
        return html


class BranchLabel(SQLBase):
    _table = 'BranchLabel'

    label = ForeignKey(foreignKey='Label', dbName='label', notNull=True)
    branch = ForeignKey(foreignKey='Branch', dbName='branch', notNull=True)
