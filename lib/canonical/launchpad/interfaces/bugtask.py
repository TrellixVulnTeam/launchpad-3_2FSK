# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Interfaces for things related to bug tasks."""

__metaclass__ = type

from zope.component.interfaces import IView
from zope.i18nmessageid import MessageIDFactory
_ = MessageIDFactory('launchpad')
from zope.interface import Interface, Attribute
from zope.schema import Bool, Bytes, Choice, Datetime, Int, Text, TextLine, List
from zope.app.form.browser.interfaces import IAddFormCustomization

from sqlos.interfaces import ISelectResults

from canonical.lp import dbschema
from canonical.launchpad.interfaces import (
    IHasProductAndAssignee, IHasDateCreated)
from canonical.launchpad.validators.bug import non_duplicate_bug

class IEditableUpstreamBugTask(IHasProductAndAssignee):
    """A bug assigned to upstream, which is editable by the current
    user."""
    title = Attribute('Title')


class IReadOnlyUpstreamBugTask(IHasProductAndAssignee):
    """A bug assigned to upstream, which is read-only by the current
    user."""
    title = Attribute('Title')


class IEditableDistroBugTask(Interface):
    """A bug assigned to a distro package, which is editable by
    the current user."""
    title = Attribute('Title')


class IReadOnlyDistroBugTask(Interface):
    """A bug assigned to a distro package, which is read-only by the
    current user."""
    title = Attribute('Title')


class IEditableDistroReleaseBugTask(Interface):
    """A bug in a distro release package, which is editable by
    the current user."""
    title = Attribute('Title')


class IReadOnlyDistroReleaseBugTask(Interface):
    """A bug in a distro release package, which is read-only by the
    current user."""
    title = Attribute('Title')


class IBugTask(IHasDateCreated):
    """A description of a bug needing fixing in a particular product
    or package."""
    id = Int(title=_("Bug Task #"))
    bug = Int(title=_("Bug #"))
    product = Choice(title=_('Product'), required=False, vocabulary='Product')
    sourcepackagename = Choice(
        title=_("Source Package Name"), required=False,
        vocabulary='SourcePackageName')
    distribution = Choice(
        title=_("Distribution"), required=False, vocabulary='Distribution')
    distrorelease = Choice(
        title=_("Distribution Release"), required=False,
        vocabulary='DistroRelease')
    milestone = Choice(
        title=_('Target'), required=False, vocabulary='Milestone')
    status = Choice(
        title=_('Status'), vocabulary='BugStatus',
        default=dbschema.BugTaskStatus.NEW)
    priority = Choice(
        title=_('Priority'), vocabulary='BugPriority',
        default=dbschema.BugPriority.MEDIUM)
    severity = Choice(
        title=_('Severity'), vocabulary='BugSeverity',
        default=dbschema.BugSeverity.NORMAL)
    assignee = Choice(
        title=_('Assignee'), required=False, vocabulary='ValidAssignee')
    binarypackagename = Choice(
        title=_('Binary PackageName'), required=False,
        vocabulary='BinaryPackageName')
    dateassigned = Datetime()
    datecreated  = Datetime()
    owner = Int()
    maintainer = TextLine(
        title=_("Maintainer"), required=True, readonly=True)
    maintainer_displayname = TextLine(
        title=_("Maintainer"), required=True, readonly=True)

    contextname = Attribute("Description of the task's location.")
    title = Attribute("The title used for a task's Web page.")
    whiteboard = Text(title=_("Status Explanation"), required=False)


class IBugTaskSearch(Interface):
    """The schema used by a bug task search form.

    Note that this is slightly different than simply IBugTask because
    some of the field types are different (e.g. it makes sense for
    status to be a Choice on a bug task edit form, but it makes sense
    for status to be a List field on a search form, where more than
    one value can be selected.)
    """
    searchtext = TextLine(title=_("Bug ID or Text"), required=False)
    status = List(
        title=_('Bug Status'),
        value_type=IBugTask['status'],
        default=[dbschema.BugTaskStatus.NEW, dbschema.BugTaskStatus.ACCEPTED],
        required=False)
    severity = List(
        title=_('Severity'),
        value_type=IBugTask['severity'],
        required=False)
    assignee = Choice(
        title=_('Assignee'), vocabulary='ValidAssignee', required=False)
    unassigned = Bool(title=_('show only unassigned bugs'), required=False)
    milestone_assignment = Choice(
        title=_('Target'), vocabulary="Milestone", required=False)
    milestone = List(
        title=_('Target'), value_type=IBugTask['milestone'], required=False)


class IBugTaskSearchListingView(IView):
    """A view that can be used with a bugtask search listing."""

    searchtext_widget = Attribute("""The widget for entering a free-form text
                                     query on bug task details.""")

    status_widget = Attribute("""The widget for selecting task statuses to
                                 filter on. None if the widget is not to be
                                 shown.""")

    severity_widget = Attribute("""The widget for selecting task severities to
                                   filter on. None is the widget is not to be
                                   shown.""")

    assignee_widget = Attribute("""The widget for selecting task assignees
                                   to filter on. None if the widget is not to be
                                   shown.""")

    milestone_widget = Attribute("""The widget for selecting task targets to
                                    filter on. None if the widget is not to be
                                    shown.""")

    def task_columns():
        """Returns a sequence of column names to be shown in the listing.

        This list may be calculated on the fly, e.g. in the case of a
        listing that allows the user to choose which columns to show
        in the listing.
        """

    def search():
        """Return an IBatchNavigator for the POSTed search criteria."""


class IBugTaskDelta(Interface):
    """The change made to a bug task (e.g. in an edit screen).

    If product is not None, both sourcepackagename and binarypackagename must
    be None.

    Likewise, if sourcepackagename and/or binarypackagename is not None,
    product must be None.

    XXX 20050512 Brad/Bjorn: Fix the Attribute descriptions. -- mpt
    """
    bugtask = Attribute("The modified IBugTask.")
    product = Attribute("A dict containing two keys, 'old' and 'new' or None.")
    sourcepackagename = Attribute(
        "A dict containing two keys, 'old' and 'new' or None.")
    binarypackagename = Attribute(
        "A dict containing two keys, 'old' and 'new' or None.")
    target = Attribute(
        "A dict containing two keys, 'old' and 'new' or None.")
    status = Attribute(
        "A dict containing two keys, 'old' and 'new' or None.")
    priority = Attribute(
        "A dict containing two keys, 'old' and 'new' or None.")
    severity = Attribute(
        "A dict containing two keys, 'old' and 'new' or None.")
    assignee = Attribute(
        "A dict containing two keys, 'old' and 'new' or None.")


class IUpstreamBugTask(IBugTask):
    """A description of a bug needing fixing in a particular product."""
    product = Choice(title=_('Product'), required=True, vocabulary='Product')


class IDistroBugTask(IBugTask):
    """A description of a bug needing fixing in a particular package."""
    sourcepackagename = Choice(
        title=_("Source Package Name"), required=True,
        vocabulary='SourcePackageName')
    binarypackagename = Choice(
        title=_('Binary PackageName'), required=False,
        vocabulary='BinaryPackageName')
    distribution = Choice(
        title=_("Distribution"), required=True, vocabulary='Distribution')


class IDistroReleaseBugTask(IBugTask):
    """A description of a bug needing fixing in a particular realease."""
    sourcepackagename = Choice(
        title=_("Source Package Name"), required=True,
        vocabulary='SourcePackageName')
    binarypackagename = Choice(
        title=_('Binary PackageName'), required=False,
        vocabulary='BinaryPackageName')
    distrorelease = Choice(
        title=_("Distribution Release"), required=True,
        vocabulary='DistroRelease')


# XXX: Brad Bollenbach, 2005-02-03: This interface should be removed
# when spiv pushes a fix upstream for the bug that makes this hackery
# necessary:
#
#     https://launchpad.ubuntu.com/malone/bugs/121
class ISelectResultsSlicable(ISelectResults):
    def __getslice__(i, j):
        """Called to implement evaluation of self[i:j]."""


class IBugTaskSet(Interface):

    title = Attribute('Title')

    def __getitem__(key):
        """Get an IBugTask."""

    def __iter__():
        """Iterate through IBugTasks for a given bug."""

    def get(id):
        """Retrieve a BugTask with the given id.

        Raise a zope.exceptions.NotFoundError if there is no IBugTask
        matching the given id. Raise a zope.security.interfaces.Unauthorized
        if the user doesn't have the permission to view this bug.
        """

    def search(bug=None, searchtext=None, status=None, priority=None,
               severity=None, product=None, distribution=None, distrorelease=None,
               milestone=None, assignee=None, submitter=None, orderby=None):
        """Return a set of IBugTasks that satisfy the query arguments.

        Keyword arguments should always be used. The argument passing
        semantics are as follows:

        * BugTaskSet.search(arg = 'foo'): Match all IBugTasks where
          IBugTask.arg == 'foo'.

        * BugTaskSet.search(arg = any('foo', 'bar')): Match all IBugTasks
          where IBugTask.arg == 'foo' or IBugTask.arg == 'bar'

        * BugTaskSet.search(arg1 = 'foo', arg2 = 'bar'): Match all
          IBugTasks where IBugTask.arg1 == 'foo' and
          IBugTask.arg2 == 'bar'

        For a more thorough treatment, check out:

            lib/canonical/launchpad/doc/bugtask.txt
        """

    def createTask(bug, product=None, distribution=None, distrorelease=None,
                   sourcepackagename=None, binarypackagename=None, status=None,
                   priority=None, severity=None, assignee=None, owner=None,
                   milestone=None):
        """Create a bug task on a bug.

        Exactly one of product, distribution or distrorelease must be provided.
        """

    def assignedBugTasks(person, minseverity=None, minpriority=None,
                         showclosed=None, orderby=None, user=None):
        """Return all bug tasks assigned to the given person or to a
        package/product this person maintains.

        By default, closed (FIXED, REJECTED) tasks are not returned. If you
        want closed tasks too, just pass showclosed=True.

        If minseverity is not None, return only the bug tasks with severity 
        greater than minseverity. The same is valid for minpriority/priority.

        If you want the results ordered, you have to explicitly specify an
        <orderBy>. Otherwise the order used is not predictable.
        <orderBy> can be either a string with the column name you want to sort
        or a list of column names as strings.

        The <user> parameter is necessary to make sure we don't return any
        bugtask of a private bug for which the user is not subscribed. If
        <user> is None, no private bugtasks will be returned.
        """

    def bugTasksWithSharedInterest(person1, person2, orderBy=None, user=None):
        """Return all bug tasks which person1 and person2 share some interest.

        We assume they share some interest if they're both members of the
        maintainer or if one is the maintainer and the task is directly
        assigned to the other.

        If you want the results ordered, you have to explicitly specify an
        <orderBy>. Otherwise the order used is not predictable.
        <orderBy> can be either a string with the column name you want to sort
        or a list of column names as strings.

        The <user> parameter is necessary to make sure we don't return any
        bugtask of a private bug for which the user is not subscribed. If
        <user> is None, no private bugtasks will be returned.
        """


class IBugTaskSubset(Interface):
    """A subset of bugs.

    Generally speaking the 'subset' refers to the bugs reported on a
    specific upstream, distribution, or distrorelease.
    """

    context = Attribute(
        "The IDistribution, IDistroRelease or IProduct.")
    context_title = TextLine(title=_("Bugs reported in"))

    def __getitem__(item):
        """Get an IBugTask.

        Raise a KeyError if the IBug with that given ID is not
        reported within this context.
        """

    def search(bug=None, searchtext=None, status=None, priority=None,
               severity=None, milestone=None, assignee=None, submitter=None,
               orderby=None):
        """Return a set of IBugTasks that satisfy the query arguments.

        The search results are filtered to include matches within the
        current context.

        Keyword arguments should always be used. The argument passing
        semantics are as follows:

        * BugTaskSubset.search(arg = 'foo'): Match all IBugTasks where
          IBugTask.arg == 'foo'.

        * BugTaskSubset.search(arg = any('foo', 'bar')): Match all IBugTasks
          where IBugTask.arg == 'foo' or IBugTask.arg == 'bar'

        * BugTaskSubset.search(arg1 = 'foo', arg2 = 'bar'): Match all
          IBugTasks where IBugTask.arg1 == 'foo' and
          IBugTask.arg2 == 'bar'

        For a more thorough treatment, check out:

            lib/canonical/launchpad/doc/bugtask.txt
        """


class IBugTasksReport(Interface):

    user = Attribute(_("The user for whom this report will be generated"))

    minseverity = Attribute(_(
        "The minimum severity of tasks to display in this report."))

    minpriority = Attribute(_(
        "The minimum priority of bug fixing tasks to display in this "
        "report."))

    showclosed = Attribute(_(
        "Whether or not to show closed bugs on this report."))

    def maintainedPackageBugs():
        """Return an iterator over the tasks of bugs on distro
        packages the user maintains."""

    def maintainedProductBugs():
        """Return an iterator over the tasks of bugs on upstream
        products the user maintains."""

    def productAssigneeBugs():
        """Return an iterator over the bugtasks on upstream products
        which are assigned directly to the user."""

    def packageAssigneeBugs():
        """Return an iterator over the bug tasks on distro packages
        which are assigned directly to the user."""

    def assignedBugs():
        """An iterator over ALL the bugs directly or indirectly assigned
        to the person."""
