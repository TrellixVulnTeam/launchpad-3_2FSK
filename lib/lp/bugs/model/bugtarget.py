# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

"""Components related to IBugTarget."""

__metaclass__ = type
__all__ = [
    'BugTargetBase',
    'HasBugsBase',
    'OfficialBugTag',
    'OfficialBugTagTargetMixin',
    ]

from storm.locals import Int, Reference, Storm, Unicode
from zope.component import getUtility
from zope.interface import implements

from canonical.database.sqlbase import cursor, sqlvalues
from lp.bugs.model.bugtask import (
    BugTaskSet, get_bug_privacy_filter)
from canonical.launchpad.searchbuilder import any, NULL, not_equals
from canonical.launchpad.interfaces.lpstorm import IMasterObject, IMasterStore
from canonical.launchpad.webapp.interfaces import ILaunchBag
from lp.bugs.interfaces.bugtarget import IOfficialBugTag
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.product import IProduct
from lp.bugs.interfaces.bugtask import (
    BugTagsSearchCombinator, BugTaskImportance, BugTaskSearchParams,
    BugTaskStatus, RESOLVED_BUGTASK_STATUSES, UNRESOLVED_BUGTASK_STATUSES)
from canonical.launchpad.webapp.interfaces import (
    IStoreSelector, MAIN_STORE, DEFAULT_FLAVOR)

class HasBugsBase:
    """Standard functionality for IHasBugs.

    All `IHasBugs` implementations should inherit from this class
    or from `BugTargetBase`.
    """
    def searchTasks(self, search_params, user=None,
                    order_by=None, search_text=None,
                    status=None,
                    importance=None,
                    assignee=None, bug_reporter=None, bug_supervisor=None,
                    bug_commenter=None, bug_subscriber=None, owner=None,
                    affected_user=None, affects_me=False,
                    has_patch=None, has_cve=None, distribution=None,
                    tags=None, tags_combinator=BugTagsSearchCombinator.ALL,
                    omit_duplicates=True, omit_targeted=None,
                    status_upstream=None, milestone_assignment=None,
                    milestone=None, component=None, nominated_for=None,
                    sourcepackagename=None, has_no_package=None,
                    hardware_bus=None, hardware_vendor_id=None,
                    hardware_product_id=None, hardware_driver_name=None,
                    hardware_driver_package_name=None,
                    hardware_owner_is_bug_reporter=None,
                    hardware_owner_is_affected_by_bug=False,
                    hardware_owner_is_subscribed_to_bug=False,
                    hardware_is_linked_to_bug=False):
        """See `IHasBugs`."""
        if status is None:
            # If no statuses are supplied, default to the
            # list of all unreolved statuses.
            status = list(UNRESOLVED_BUGTASK_STATUSES)

        if order_by is None:
            # If no order_by value is supplied, default to importance.
            order_by = ['-importance']

        if search_params is None:
            kwargs = dict(locals())
            del kwargs['self']
            del kwargs['user']
            del kwargs['search_params']
            search_params = BugTaskSearchParams.fromSearchForm(user, **kwargs)
        self._customizeSearchParams(search_params)
        return BugTaskSet().search(search_params)

    def _customizeSearchParams(self, search_params):
        """Customize `search_params` for a specific target."""
        raise NotImplementedError

    def _getBugTaskContextWhereClause(self):
        """Return an SQL snippet to filter bugtasks on this context."""
        raise NotImplementedError

    def _getBugTaskContextClause(self):
        """Return a SQL clause for selecting this target's bugtasks."""
        raise NotImplementedError(self._getBugTaskContextClause)

    @property
    def closed_bugtasks(self):
        """See `IHasBugs`."""
        closed_tasks_query = BugTaskSearchParams(
            user=getUtility(ILaunchBag).user,
            status=any(*RESOLVED_BUGTASK_STATUSES),
            omit_dupes=True)

        return self.searchTasks(closed_tasks_query)

    @property
    def open_bugtasks(self):
        """See `IHasBugs`."""
        open_tasks_query = BugTaskSearchParams(
            user=getUtility(ILaunchBag).user,
            status=any(*UNRESOLVED_BUGTASK_STATUSES),
            omit_dupes=True)

        return self.searchTasks(open_tasks_query)

    @property
    def new_bugtasks(self):
        """See `IHasBugs`."""
        open_tasks_query = BugTaskSearchParams(
            user=getUtility(ILaunchBag).user, status=BugTaskStatus.NEW,
            omit_dupes=True)

        return self.searchTasks(open_tasks_query)

    @property
    def high_bugtasks(self):
        """See `IHasBugs`."""
        high_tasks_query = BugTaskSearchParams(
            user=getUtility(ILaunchBag).user,
            importance=BugTaskImportance.HIGH,
            status=any(*UNRESOLVED_BUGTASK_STATUSES),
            omit_dupes=True)

        return self.searchTasks(high_tasks_query)

    @property
    def critical_bugtasks(self):
        """See `IHasBugs`."""
        critical_tasks_query = BugTaskSearchParams(
            user=getUtility(ILaunchBag).user,
            importance=BugTaskImportance.CRITICAL,
            status=any(*UNRESOLVED_BUGTASK_STATUSES),
            omit_dupes=True)

        return self.searchTasks(critical_tasks_query)

    @property
    def inprogress_bugtasks(self):
        """See `IHasBugs`."""
        inprogress_tasks_query = BugTaskSearchParams(
            user=getUtility(ILaunchBag).user,
            status=BugTaskStatus.INPROGRESS,
            omit_dupes=True)

        return self.searchTasks(inprogress_tasks_query)

    @property
    def unassigned_bugtasks(self):
        """See `IHasBugs`."""
        unassigned_tasks_query = BugTaskSearchParams(
            user=getUtility(ILaunchBag).user, assignee=NULL,
            status=any(*UNRESOLVED_BUGTASK_STATUSES), omit_dupes=True)

        return self.searchTasks(unassigned_tasks_query)

    @property
    def all_bugtasks(self):
        """See `IHasBugs`."""
        all_tasks_query = BugTaskSearchParams(
            user=getUtility(ILaunchBag).user,
            status=not_equals(BugTaskStatus.UNKNOWN))

        return self.searchTasks(all_tasks_query)

    def getBugCounts(self, user, statuses=None):
        """See `IHasBugs`."""
        if statuses is None:
            statuses = BugTaskStatus.items
        statuses = list(statuses)

        count_column = """
            COUNT (CASE WHEN BugTask.status = %s
                        THEN BugTask.id ELSE NULL END)"""
        select_columns = [count_column % sqlvalues(status)
                          for status in statuses]
        conditions = [
            '(%s)' % self._getBugTaskContextClause(),
            'BugTask.bug = Bug.id',
            'Bug.duplicateof is NULL']
        privacy_filter = get_bug_privacy_filter(user)
        if privacy_filter:
            conditions.append(privacy_filter)

        cur = cursor()
        cur.execute(
            "SELECT %s FROM BugTask, Bug WHERE %s" % (
                ', '.join(select_columns), ' AND '.join(conditions)))
        counts = cur.fetchone()
        return dict(zip(statuses, counts))



class BugTargetBase(HasBugsBase):
    """Standard functionality for IBugTargets.

    All IBugTargets should inherit from this class.
    """


class OfficialBugTagTargetMixin:
    """See `IOfficialBugTagTarget`.

    This class is inteneded to be used as a mixin for the classes
    Distribution, Product and Project, which can define official
    bug tags.

    Using this call in Project requires a fix of bug 341203, see
    below, class OfficialBugTag.
    """

    def _getOfficialTags(self):
        """Get the official bug tags as a sorted list of strings."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        if IDistribution.providedBy(self):
            target_clause = (OfficialBugTag.distribution == self)
        elif IProduct.providedBy(self):
            target_clause = (OfficialBugTag.product == self)
        else:
            raise AssertionError(
                '%s is not a valid official bug target' % self)
        tags = [
            obt.tag for obt
            in store.find(OfficialBugTag, target_clause).order_by('tag')]
        return tags

    def _setOfficialTags(self, tags):
        """Set the official bug tags from a list of strings."""
        new_tags = set([tag.lower() for tag in tags])
        old_tags = set(self.official_bug_tags)
        added_tags = new_tags.difference(old_tags)
        removed_tags = old_tags.difference(new_tags)
        for removed_tag in removed_tags:
            self.removeOfficialBugTag(removed_tag)
        for added_tag in added_tags:
            self.addOfficialBugTag(added_tag)

    official_bug_tags = property(_getOfficialTags, _setOfficialTags)

    def _getTag(self, tag):
        """Return the OfficialBugTag record for the given tag, if it exists.

        If the tag is not defined for this target, None is returned.
        """
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        if IDistribution.providedBy(self):
            target_clause = (OfficialBugTag.distribution == self)
        else:
            target_clause = (OfficialBugTag.product == self)
        return store.find(
            OfficialBugTag, OfficialBugTag.tag==tag, target_clause).one()

    def addOfficialBugTag(self, tag):
        """See `IOfficialBugTagTarget`."""
        # Tags must be unique per target; adding an existing tag
        # for a second time would lead to an exception.
        if self._getTag(tag) is None:
            new_tag = OfficialBugTag()
            new_tag.tag = tag
            new_tag.target = IMasterObject(self)
            IMasterStore(OfficialBugTag).add(new_tag)

    def removeOfficialBugTag(self, tag):
        """See `IOfficialBugTagTarget`."""
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        tag = self._getTag(tag)
        if tag is not None:
            store.remove(tag)


class OfficialBugTag(Storm):
    """See `IOfficialBugTag`."""
    # XXX Abel Deuring, 2009-03-11: The SQL table OfficialBugTag has
    # a column "project", while a constraint requires that either "product"
    # or "distribution" must be non-null. Once this is changed, we
    # should add the column "project" here. Bug #341203.

    implements(IOfficialBugTag)

    __storm_table__ = 'OfficialBugTag'

    id = Int(primary=True)

    tag = Unicode(allow_none=False)
    distribution_id = Int(name='distribution')
    distribution = Reference(distribution_id, 'Distribution.id')

    product_id = Int(name='product')
    product = Reference(product_id, 'Product.id')

    def target(self):
        """See `IOfficialBugTag`."""
        # A database constraint ensures that either distribution or
        # product is not None.
        if self.distribution is not None:
            return self.distribution
        else:
            return self.product

    def _settarget(self, target):
        """See `IOfficialBugTag`."""
        if IDistribution.providedBy(target):
            self.distribution = target
        elif IProduct.providedBy(target):
            self.product = target
        else:
            raise ValueError(
                'The target of an OfficialBugTag must be either an '
                'IDistribution instance or an IProduct instance.')

    target = property(target, _settarget, doc=target.__doc__)

