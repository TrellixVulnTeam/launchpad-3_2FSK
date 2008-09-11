# Copyright 2006 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

"""Components related to IBugTarget."""

__metaclass__ = type
__all__ = [
    'BugTargetBase',
    'HasBugsBase',
    ]

from zope.component import getUtility

from canonical.database.sqlbase import cursor, sqlvalues
from canonical.launchpad.database.bugtask import get_bug_privacy_filter
from canonical.launchpad.searchbuilder import any, NULL, not_equals
from canonical.launchpad.interfaces import ILaunchBag
from canonical.launchpad.interfaces.bugtask import (
    BugTaskImportance, BugTaskSearchParams, BugTaskStatus, IBugTaskSet,
    RESOLVED_BUGTASK_STATUSES, UNRESOLVED_BUGTASK_STATUSES)


class HasBugsBase:
    """Standard functionality for IHasBugs.

    All `IHasBugs` implementations should inherit from this class
    or from `BugTargetBase`.
    """
    def searchTasks(self, search_params, user=None,
                    order_by=('-importance',), search_text=None,
                    status=None,
                    importance=None,
                    assignee=None, bug_reporter=None, bug_supervisor=None,
                    bug_commenter=None, bug_subscriber=None, owner=None,
                    has_patch=None, has_cve=None,
                    tags=None, tags_combinator_all=True,
                    omit_duplicates=True, omit_targeted=None,
                    status_upstream=None, milestone_assignment=None,
                    milestone=None, component=None, nominated_for=None,
                    sourcepackagename=None, has_no_package=None):
        """See `IHasBugs`."""
        if status is None:
            # If no statuses are supplied, default to the
            # list of all unreolved statuses
            status = list(UNRESOLVED_BUGTASK_STATUSES)

        if search_params is None:
            kwargs = dict(locals())
            del kwargs['self']
            del kwargs['user']
            del kwargs['search_params']
            search_params = BugTaskSearchParams.fromSearchForm(user, **kwargs)
        self._customizeSearchParams(search_params)
        return getUtility(IBugTaskSet).search(search_params)

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
            user=getUtility(ILaunchBag).user, status=BugTaskStatus.INPROGRESS,
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

        from_tables = ['BugTask', 'Bug']
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
    def getMostCommonBugs(self, user, limit=10):
        """See canonical.launchpad.interfaces.IBugTarget."""
        constraints = []
        bug_privacy_clause = get_bug_privacy_filter(user)
        if bug_privacy_clause:
            constraints.append(bug_privacy_clause)
        constraints.append(self._getBugTaskContextWhereClause())
        c = cursor()
        c.execute("""
        SELECT duplicateof, COUNT(duplicateof)
        FROM Bug
        WHERE duplicateof IN (
            SELECT DISTINCT(Bug.id)
            FROM Bug, BugTask
            WHERE BugTask.bug = Bug.id AND
            %s)
        GROUP BY duplicateof
        ORDER BY COUNT(duplicateof) DESC
        LIMIT %d
        """ % ("AND\n".join(constraints), limit))

        common_bug_ids = [
            str(bug_id) for (bug_id, dupe_count) in c.fetchall()]

        if not common_bug_ids:
            return []
        # import this database class here, in order to avoid
        # circular dependencies.
        from canonical.launchpad.database.bug import Bug
        return list(
            Bug.select("Bug.id IN (%s)" % ", ".join(common_bug_ids)))
