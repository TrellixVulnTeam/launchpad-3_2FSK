# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

"""Classes that implement IBugTask and its related interfaces."""

__metaclass__ = type

__all__ = [
    'BugTaskDelta',
    'BugTaskToBugAdapter',
    'BugTaskMixin',
    'BugTask',
    'BugTaskSet',
    'NullBugTask',
    'bugtask_sort_key',
    'get_bug_privacy_filter',
    'get_related_bugtasks_search_params',
    'search_value_to_where_condition',
    ]


import datetime
from operator import attrgetter

from lazr.enum import DBItem
import pytz
from sqlobject import (
    ForeignKey,
    SQLObjectNotFound,
    StringCol,
    )
from sqlobject.sqlbuilder import SQLConstant
from storm.expr import (
    Alias,
    And,
    AutoTables,
    Desc,
    In,
    Join,
    LeftJoin,
    Or,
    SQL,
    )
from storm.store import (
    EmptyResultSet,
    Store,
    )
from storm.zope.interfaces import (
    IResultSet,
    ISQLObjectResultSet,
    )
from zope.component import getUtility
from zope.interface import (
    alsoProvides,
    implements,
    )
from zope.interface.interfaces import IMethod
from zope.security.proxy import (
    isinstance as zope_isinstance,
    removeSecurityProxy,
    )

from canonical.config import config
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.nl_search import nl_phrase_search
from canonical.database.sqlbase import (
    block_implicit_flushes,
    convert_storm_clause_to_string,
    cursor,
    quote,
    quote_like,
    SQLBase,
    sqlvalues,
    )
from canonical.launchpad.components.decoratedresultset import (
    DecoratedResultSet,
    )
from canonical.launchpad.helpers import shortlist
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.interfaces.lpstorm import IStore
from canonical.launchpad.searchbuilder import (
    all,
    any,
    greater_than,
    not_equals,
    NULL,
    )
from canonical.launchpad.webapp.interfaces import (
    DEFAULT_FLAVOR,
    ILaunchBag,
    IStoreSelector,
    MAIN_STORE,
    )
from lp.app.enums import ServiceUsage
from lp.app.errors import NotFoundError
from lp.bugs.interfaces.bug import IBugSet
from lp.bugs.interfaces.bugattachment import BugAttachmentType
from lp.bugs.interfaces.bugnomination import BugNominationStatus
from lp.bugs.interfaces.bugtask import (
    BUG_SUPERVISOR_BUGTASK_STATUSES,
    BugBranchSearch,
    BugTaskImportance,
    BugTaskSearchParams,
    BugTaskStatus,
    BugTaskStatusSearch,
    ConjoinedBugTaskEditError,
    IBugTask,
    IBugTaskDelta,
    IBugTaskSet,
    IDistroBugTask,
    IDistroSeriesBugTask,
    IllegalRelatedBugTasksParams,
    IllegalTarget,
    INullBugTask,
    IProductSeriesBugTask,
    IUpstreamBugTask,
    RESOLVED_BUGTASK_STATUSES,
    UNRESOLVED_BUGTASK_STATUSES,
    UserCannotEditBugTaskAssignee,
    UserCannotEditBugTaskImportance,
    UserCannotEditBugTaskMilestone,
    UserCannotEditBugTaskStatus,
    )
from lp.bugs.model.bugnomination import BugNomination
from lp.bugs.model.bugsubscription import BugSubscription
from lp.registry.enum import BugNotificationLevel
from lp.registry.interfaces.distribution import (
    IDistribution,
    IDistributionSet,
    )
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
    )
from lp.registry.interfaces.distroseries import (
    IDistroSeries,
    IDistroSeriesSet,
    )
from lp.registry.interfaces.milestone import IProjectGroupMilestone
from lp.registry.interfaces.person import (
    IPerson,
    validate_person,
    validate_public_person,
    )
from lp.registry.interfaces.product import (
    IProduct,
    IProductSet,
    )
from lp.registry.interfaces.productseries import (
    IProductSeries,
    IProductSeriesSet,
    )
from lp.registry.interfaces.projectgroup import IProjectGroup
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.registry.interfaces.sourcepackagename import ISourcePackageNameSet
from lp.registry.interfaces.structuralsubscription import (
    IStructuralSubscriptionTarget,
    )
from lp.registry.model.pillar import pillar_sort_key
from lp.registry.model.sourcepackagename import SourcePackageName
from lp.services.propertycache import get_property_cache
from lp.soyuz.enums import PackagePublishingStatus
from lp.soyuz.model.publishing import SourcePackagePublishingHistory
from lp.soyuz.model.sourcepackagerelease import SourcePackageRelease


debbugsseveritymap = {
    None: BugTaskImportance.UNDECIDED,
    'wishlist': BugTaskImportance.WISHLIST,
    'minor': BugTaskImportance.LOW,
    'normal': BugTaskImportance.MEDIUM,
    'important': BugTaskImportance.HIGH,
    'serious': BugTaskImportance.HIGH,
    'grave': BugTaskImportance.HIGH,
    'critical': BugTaskImportance.CRITICAL,
    }


def bugtask_sort_key(bugtask):
    """A sort key for a set of bugtasks. We want:

          - products first, followed by their productseries tasks
          - distro tasks, followed by their distroseries tasks
          - ubuntu first among the distros
    """
    if bugtask.product:
        product_name = bugtask.product.name
        productseries_name = None
    elif bugtask.productseries:
        productseries_name = bugtask.productseries.name
        product_name = bugtask.productseries.product.name
    else:
        product_name = None
        productseries_name = None

    if bugtask.distribution:
        distribution_name = bugtask.distribution.name
    else:
        distribution_name = None

    if bugtask.distroseries:
        distroseries_name = bugtask.distroseries.version
        distribution_name = bugtask.distroseries.distribution.name
    else:
        distroseries_name = None

    if bugtask.sourcepackagename:
        sourcepackage_name = bugtask.sourcepackagename.name
    else:
        sourcepackage_name = None

    # Move ubuntu to the top.
    if distribution_name == 'ubuntu':
        distribution_name = '-'

    return (
        bugtask.bug.id, distribution_name, product_name, productseries_name,
        distroseries_name, sourcepackage_name)


def get_related_bugtasks_search_params(user, context, **kwargs):
    """Returns a list of `BugTaskSearchParams` which can be used to
    search for all tasks related to a user given by `context`.

    Which tasks are related to a user?
      * the user has to be either assignee or owner of this task
        OR
      * the user has to be subscriber or commenter to the underlying bug
        OR
      * the user is reporter of the underlying bug, but this condition
        is automatically fulfilled by the first one as each new bug
        always get one task owned by the bug reporter
    """
    assert IPerson.providedBy(context), "Context argument needs to be IPerson"
    relevant_fields = ('assignee', 'bug_subscriber', 'owner', 'bug_commenter',
                       'structural_subscriber')
    search_params = []
    for key in relevant_fields:
        # all these parameter default to None
        user_param = kwargs.get(key)
        if user_param is None or user_param == context:
            # we are only creating a `BugTaskSearchParams` object if
            # the field is None or equal to the context
            arguments = kwargs.copy()
            arguments[key] = context
            if key == 'owner':
                # Specify both owner and bug_reporter to try to
                # prevent the same bug (but different tasks)
                # being displayed.
                # see `PersonRelatedBugTaskSearchListingView.searchUnbatched`
                arguments['bug_reporter'] = context
            search_params.append(
                BugTaskSearchParams.fromSearchForm(user, **arguments))
    if len(search_params) == 0:
        # unable to search for related tasks to user_context because user
        # modified the query in an invalid way by overwriting all user
        # related parameters
        raise IllegalRelatedBugTasksParams(
            ('Cannot search for related tasks to \'%s\', at least one '
             'of these parameter has to be empty: %s'
                %(context.name, ", ".join(relevant_fields))))
    return search_params


class BugTaskDelta:
    """See `IBugTaskDelta`."""

    implements(IBugTaskDelta)

    def __init__(self, bugtask, status=None, importance=None,
                 assignee=None, milestone=None, statusexplanation=None,
                 bugwatch=None, target=None):
        self.bugtask = bugtask

        self.assignee = assignee
        self.bugwatch = bugwatch
        self.importance = importance
        self.milestone = milestone
        self.status = status
        self.statusexplanation = statusexplanation
        self.target = target


class BugTaskMixin:
    """Mix-in class for some property methods of IBugTask implementations."""

    @property
    def bug_subscribers(self):
        """See `IBugTask`."""
        indirect_subscribers = self.bug.getIndirectSubscribers()
        return self.bug.getDirectSubscribers() + indirect_subscribers

    @property
    def bugtargetdisplayname(self):
        """See `IBugTask`."""
        return self.target.bugtargetdisplayname

    @property
    def bugtargetname(self):
        """See `IBugTask`."""
        return self.target.bugtargetname

    @property
    def target(self):
        """See `IBugTask`."""
        # We explicitly reference attributes here (rather than, say,
        # IDistroBugTask.providedBy(self)), because we can't assume this
        # task has yet been marked with the correct interface.
        if self.product:
            return self.product
        elif self.productseries:
            return self.productseries
        elif self.distribution:
            if self.sourcepackagename:
                return self.distribution.getSourcePackage(
                    self.sourcepackagename)
            else:
                return self.distribution
        elif self.distroseries:
            if self.sourcepackagename:
                return self.distroseries.getSourcePackage(
                    self.sourcepackagename)
            else:
                return self.distroseries
        else:
            raise AssertionError("Unable to determine bugtask target.")

    @property
    def related_tasks(self):
        """See `IBugTask`."""
        other_tasks = [
            task for task in self.bug.bugtasks if task != self]

        return other_tasks

    @property
    def pillar(self):
        """See `IBugTask`."""
        if self.product is not None:
            return self.product
        elif self.productseries is not None:
            return self.productseries.product
        elif self.distribution is not None:
            return self.distribution
        else:
            return self.distroseries.distribution

    @property
    def other_affected_pillars(self):
        """See `IBugTask`."""
        result = set()
        this_pillar = self.pillar
        for task in self.bug.bugtasks:
            that_pillar = task.pillar
            if that_pillar != this_pillar:
                result.add(that_pillar)
        return sorted(result, key=pillar_sort_key)

    @property
    def mentoring_offers(self):
        """See `IHasMentoringOffers`."""
        # mentoring is on IBug as a whole, not on a specific task, so we
        # pass through to the bug
        return self.bug.mentoring_offers

    def canMentor(self, user):
        """See `ICanBeMentored`."""
        # mentoring is on IBug as a whole, not on a specific task, so we
        # pass through to the bug
        return self.bug.canMentor(user)

    def isMentor(self, user):
        """See `ICanBeMentored`."""
        # mentoring is on IBug as a whole, not on a specific task, so we
        # pass through to the bug
        return self.bug.isMentor(user)

    def offerMentoring(self, user, team):
        """See `ICanBeMentored`."""
        # mentoring is on IBug as a whole, not on a specific task, so we
        # pass through to the bug
        return self.bug.offerMentoring(user, team)

    def retractMentoring(self, user):
        """See `ICanBeMentored`."""
        # mentoring is on IBug as a whole, not on a specific task, so we
        # pass through to the bug
        return self.bug.retractMentoring(user)


class NullBugTask(BugTaskMixin):
    """A null object for IBugTask.

    This class is used, for example, to be able to render a URL like:

      /products/evolution/+bug/5

    when bug #5 isn't yet reported in evolution.
    """
    implements(INullBugTask)

    def __init__(self, bug, product=None, productseries=None,
                 sourcepackagename=None, distribution=None,
                 distroseries=None):
        """Initialize a NullBugTask."""
        self.id = None
        self.bug = bug
        self.product = product
        self.productseries = productseries
        self.sourcepackagename = sourcepackagename
        self.distribution = distribution
        self.distroseries = distroseries

        # Mark the task with the correct interface, depending on its
        # context.
        if self.product:
            alsoProvides(self, IUpstreamBugTask)
        elif self.distribution:
            alsoProvides(self, IDistroBugTask)
        elif self.distroseries:
            alsoProvides(self, IDistroSeriesBugTask)
        elif self.productseries:
            alsoProvides(self, IProductSeriesBugTask)
        else:
            raise AssertionError('Unknown NullBugTask: %r.' % self)

        # Make us provide the interface by setting all required attributes
        # to None, and define the methods as raising NotImplementedError.
        # The attributes are set to None because it doesn't make
        # sense for these attributes to have a value when there is no
        # real task there. (In fact, it may make sense for these
        # values to be non-null, but I haven't yet found a use case
        # for it, and I don't think there's any point on designing for
        # that until we've encountered one.)
        def this_is_a_null_bugtask_method(*args, **kwargs):
            raise NotImplementedError

        for name, spec in INullBugTask.namesAndDescriptions(True):
            if not hasattr(self, name):
                if IMethod.providedBy(spec):
                    value = this_is_a_null_bugtask_method
                else:
                    value = None
                setattr(self, name, value)

    @property
    def title(self):
        """See `IBugTask`."""
        return 'Bug #%s is not in %s: "%s"' % (
            self.bug.id, self.bugtargetdisplayname, self.bug.title)


def BugTaskToBugAdapter(bugtask):
    """Adapt an IBugTask to an IBug."""
    return bugtask.bug


@block_implicit_flushes
def validate_target_attribute(self, attr, value):
    """Update the targetnamecache."""
    # Don't update targetnamecache during _init().
    if self._SO_creating:
        return value
    # Determine the new target attributes.
    target_params = dict(
        product=self.product,
        productseries=self.productseries,
        sourcepackagename=self.sourcepackagename,
        distribution=self.distribution,
        distroseries=self.distroseries)
    utility_iface_dict = {
        'productID': IProductSet,
        'productseriesID': IProductSeriesSet,
        'sourcepackagenameID': ISourcePackageNameSet,
        'distributionID': IDistributionSet,
        'distroseriesID': IDistroSeriesSet,
        }
    utility_iface = utility_iface_dict[attr]
    if value is None:
        target_params[attr[:-2]] = None
    else:
        target_params[attr[:-2]] = getUtility(utility_iface).get(value)

    # Use a NullBugTask to determine the new target.
    nulltask = NullBugTask(self.bug, **target_params)
    self.updateTargetNameCache(nulltask.target)

    return value


class PassthroughValue:
    """A wrapper to allow setting values on conjoined bug tasks."""

    def __init__(self, value):
        self.value = value


@block_implicit_flushes
def validate_conjoined_attribute(self, attr, value):
    # If the value has been wrapped in a _PassthroughValue instance,
    # then we are being updated by our conjoined master: pass the
    # value through without any checking.
    if isinstance(value, PassthroughValue):
        return value.value

    # If this bugtask has no bug yet, then we are probably being
    # instantiated.
    if self.bug is None:
        return value

    if self._isConjoinedBugTask():
        raise ConjoinedBugTaskEditError(
            "This task cannot be edited directly, it should be"
            " edited through its conjoined_master.")
    # The conjoined slave is updated before the master one because,
    # for distro tasks, conjoined_slave does a comparison on
    # sourcepackagename, and the sourcepackagenames will not match
    # if the conjoined master is altered before the conjoined slave!
    conjoined_bugtask = self.conjoined_slave
    if conjoined_bugtask:
        setattr(conjoined_bugtask, attr, PassthroughValue(value))

    return value


def validate_status(self, attr, value):
    if value not in self._NON_CONJOINED_STATUSES:
        return validate_conjoined_attribute(self, attr, value)
    else:
        return value


def validate_assignee(self, attr, value):
    value = validate_conjoined_attribute(self, attr, value)
    # Check if this person is valid and not None.
    return validate_person(self, attr, value)


@block_implicit_flushes
def validate_sourcepackagename(self, attr, value):
    is_passthrough = isinstance(value, PassthroughValue)
    value = validate_conjoined_attribute(self, attr, value)
    if not is_passthrough:
        self._syncSourcePackages(value)
    return validate_target_attribute(self, attr, value)


class BugTask(SQLBase, BugTaskMixin):
    """See `IBugTask`."""
    implements(IBugTask)
    _table = "BugTask"
    _defaultOrder = ['distribution', 'product', 'productseries',
                     'distroseries', 'milestone', 'sourcepackagename']
    _CONJOINED_ATTRIBUTES = (
        "status", "importance", "assigneeID", "milestoneID",
        "date_assigned", "date_confirmed", "date_inprogress",
        "date_closed", "date_incomplete", "date_left_new",
        "date_triaged", "date_fix_committed", "date_fix_released",
        "date_left_closed")
    _NON_CONJOINED_STATUSES = (BugTaskStatus.WONTFIX, )

    bug = ForeignKey(dbName='bug', foreignKey='Bug', notNull=True)
    product = ForeignKey(
        dbName='product', foreignKey='Product',
        notNull=False, default=None,
        storm_validator=validate_target_attribute)
    productseries = ForeignKey(
        dbName='productseries', foreignKey='ProductSeries',
        notNull=False, default=None,
        storm_validator=validate_target_attribute)
    sourcepackagename = ForeignKey(
        dbName='sourcepackagename', foreignKey='SourcePackageName',
        notNull=False, default=None,
        storm_validator=validate_sourcepackagename)
    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution',
        notNull=False, default=None,
        storm_validator=validate_target_attribute)
    distroseries = ForeignKey(
        dbName='distroseries', foreignKey='DistroSeries',
        notNull=False, default=None,
        storm_validator=validate_target_attribute)
    milestone = ForeignKey(
        dbName='milestone', foreignKey='Milestone',
        notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    status = EnumCol(
        dbName='status', notNull=True,
        schema=BugTaskStatus,
        default=BugTaskStatus.NEW,
        storm_validator=validate_status)
    statusexplanation = StringCol(dbName='statusexplanation', default=None)
    importance = EnumCol(
        dbName='importance', notNull=True,
        schema=BugTaskImportance,
        default=BugTaskImportance.UNDECIDED,
        storm_validator=validate_conjoined_attribute)
    assignee = ForeignKey(
        dbName='assignee', foreignKey='Person',
        storm_validator=validate_assignee,
        notNull=False, default=None)
    bugwatch = ForeignKey(dbName='bugwatch', foreignKey='BugWatch',
        notNull=False, default=None)
    date_assigned = UtcDateTimeCol(notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    datecreated = UtcDateTimeCol(notNull=False, default=UTC_NOW)
    date_confirmed = UtcDateTimeCol(notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    date_inprogress = UtcDateTimeCol(notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    date_closed = UtcDateTimeCol(notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    date_incomplete = UtcDateTimeCol(notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    date_left_new = UtcDateTimeCol(notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    date_triaged = UtcDateTimeCol(notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    date_fix_committed = UtcDateTimeCol(notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    date_fix_released = UtcDateTimeCol(notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    date_left_closed = UtcDateTimeCol(notNull=False, default=None,
        storm_validator=validate_conjoined_attribute)
    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    # The targetnamecache is a value that is only supposed to be set
    # when a bugtask is created/modified or by the
    # update-bugtask-targetnamecaches cronscript. For this reason it's
    # not exposed in the interface, and client code should always use
    # the bugtargetname and bugtargetdisplayname properties.
    #
    # This field is actually incorrectly named, since it currently
    # stores the bugtargetdisplayname.
    targetnamecache = StringCol(
        dbName='targetnamecache', notNull=False, default=None)

    @property
    def title(self):
        """See `IBugTask`."""
        return 'Bug #%s in %s: "%s"' % (
            self.bug.id, self.bugtargetdisplayname, self.bug.title)

    @property
    def bugtargetdisplayname(self):
        """See `IBugTask`."""
        return self.targetnamecache

    @property
    def age(self):
        """See `IBugTask`."""
        UTC = pytz.timezone('UTC')
        now = datetime.datetime.now(UTC)

        return now - self.datecreated

    @property
    def task_age(self):
        """See `IBugTask`."""
        return self.age.seconds

    # Several other classes need to generate lists of bug tasks, and
    # one thing they often have to filter for is completeness. We maintain
    # this single canonical query string here so that it does not have to be
    # cargo culted into Product, Distribution, ProductSeries etc
    completeness_clause = """
        BugTask.status IN ( %s )
        """ % ','.join([str(a.value) for a in RESOLVED_BUGTASK_STATUSES])

    @property
    def is_complete(self):
        """See `IBugTask`.

        Note that this should be kept in sync with the completeness_clause
        above.
        """
        return self.status in RESOLVED_BUGTASK_STATUSES

    def findSimilarBugs(self, user, limit=10):
        """See `IBugTask`."""
        if self.product is not None:
            context_params = {'product': self.product}
        elif (self.sourcepackagename is not None and
            self.distribution is not None):
            context_params = {
                'distribution': self.distribution,
                'sourcepackagename': self.sourcepackagename,
                }
        elif self.distribution is not None:
            context_params = {'distribution': self.distribution}
        else:
            raise AssertionError("BugTask doesn't have a searchable target.")

        matching_bugtasks = getUtility(IBugTaskSet).findSimilar(
            user, self.bug.title, **context_params)

        matching_bugs = getUtility(IBugSet).getDistinctBugsForBugTasks(
            matching_bugtasks, user, limit)

        # Make sure to exclude the bug of the current bugtask.
        return [bug for bug in matching_bugs if bug.id != self.bugID]

    def subscribe(self, person, subscribed_by):
        """See `IBugTask`."""
        return self.bug.subscribe(person, subscribed_by)

    def isSubscribed(self, person):
        """See `IBugTask`."""
        return self.bug.isSubscribed(person)

    def _syncSourcePackages(self, new_spnid):
        """Synchronize changes to source packages with other distrotasks.

        If one distroseriestask's source package is changed, all the
        other distroseriestasks with the same distribution and source
        package has to be changed, as well as the corresponding
        distrotask.
        """
        if self.bug is None:
            # The validator is being called on an incomplete bug task.
            return
        if self.distroseries is not None:
            distribution = self.distroseries.distribution
        else:
            distribution = self.distribution
        if distribution is not None:
            for bugtask in self.related_tasks:
                if bugtask.distroseries:
                    related_distribution = bugtask.distroseries.distribution
                else:
                    related_distribution = bugtask.distribution
                if (related_distribution == distribution and
                    bugtask.sourcepackagenameID == self.sourcepackagenameID):
                    bugtask.sourcepackagenameID = PassthroughValue(new_spnid)

    def getConjoinedMaster(self, bugtasks, bugtasks_by_package=None):
        """See `IBugTask`."""
        conjoined_master = None
        if IDistroBugTask.providedBy(self):
            if bugtasks_by_package is None:
                bugtasks_by_package = (
                    self.bug.getBugTasksByPackageName(bugtasks))
            bugtasks = bugtasks_by_package[self.sourcepackagename]
            possible_masters = [
                bugtask for bugtask in bugtasks
                if (bugtask.distroseries is not None and
                    bugtask.sourcepackagename == self.sourcepackagename)]
            # Return early, so that we don't have to get currentseries,
            # which is expensive.
            if len(possible_masters) == 0:
                return None
            current_series = self.distribution.currentseries
            for bugtask in possible_masters:
                if bugtask.distroseries == current_series:
                    conjoined_master = bugtask
                    break
        elif IUpstreamBugTask.providedBy(self):
            assert self.product.development_focusID is not None, (
                'A product should always have a development series.')
            devel_focusID = self.product.development_focusID
            for bugtask in bugtasks:
                if bugtask.productseriesID == devel_focusID:
                    conjoined_master = bugtask
                    break

        if (conjoined_master is not None and
            conjoined_master.status in self._NON_CONJOINED_STATUSES):
            conjoined_master = None
        return conjoined_master

    @property
    def conjoined_master(self):
        """See `IBugTask`."""
        return self.getConjoinedMaster(shortlist(self.bug.bugtasks))

    @property
    def conjoined_slave(self):
        """See `IBugTask`."""
        conjoined_slave = None
        if IDistroSeriesBugTask.providedBy(self):
            distribution = self.distroseries.distribution
            if self.distroseries != distribution.currentseries:
                # Only current series tasks are conjoined.
                return None
            for bugtask in shortlist(self.bug.bugtasks):
                if (bugtask.distribution == distribution and
                    bugtask.sourcepackagename == self.sourcepackagename):
                    conjoined_slave = bugtask
                    break
        elif IProductSeriesBugTask.providedBy(self):
            product = self.productseries.product
            if self.productseries != product.development_focus:
                # Only development focus tasks are conjoined.
                return None
            for bugtask in shortlist(self.bug.bugtasks):
                if bugtask.product == product:
                    conjoined_slave = bugtask
                    break

        if (conjoined_slave is not None and
            self.status in self._NON_CONJOINED_STATUSES):
            conjoined_slave = None
        return conjoined_slave

    def _isConjoinedBugTask(self):
        """Return True when conjoined_master is not None, otherwise False."""
        return self.conjoined_master is not None

    def _syncFromConjoinedSlave(self):
        """Ensure the conjoined master is synched from its slave.

        This method should be used only directly after when the
        conjoined master has been created after the slave, to ensure
        that they are in sync from the beginning.
        """
        conjoined_slave = self.conjoined_slave

        for synched_attr in self._CONJOINED_ATTRIBUTES:
            slave_attr_value = getattr(conjoined_slave, synched_attr)
            # Bypass our checks that prevent setting attributes on
            # conjoined masters by calling the underlying sqlobject
            # setter methods directly.
            setattr(self, synched_attr, PassthroughValue(slave_attr_value))

    def _init(self, *args, **kw):
        """Marks the task when it's created or fetched from the database."""
        SQLBase._init(self, *args, **kw)

        # We check both the foreign key column and the reference so we
        # can detect unflushed references.  The reference check will
        # only be made if the FK is None, so no additional queries
        # will be executed.
        if self.productID is not None or self.product is not None:
            alsoProvides(self, IUpstreamBugTask)
        elif (self.productseriesID is not None or
              self.productseries is not None):
            alsoProvides(self, IProductSeriesBugTask)
        elif self.distroseriesID is not None or self.distroseries is not None:
            alsoProvides(self, IDistroSeriesBugTask)
        elif self.distributionID is not None or self.distribution is not None:
            # If nothing else, this is a distro task.
            alsoProvides(self, IDistroBugTask)
        else:
            raise AssertionError("Task %d is floating." % self.id)

    @property
    def target_uses_malone(self):
        """See `IBugTask`"""
        # XXX sinzui 2007-10-04 bug=149009:
        # This property is not needed. Code should inline this implementation.
        return (self.pillar.bug_tracking_usage == ServiceUsage.LAUNCHPAD)

    def transitionToMilestone(self, new_milestone, user):
        """See `IBugTask`."""
        if not self.userCanEditMilestone(user):
            raise UserCannotEditBugTaskMilestone(
                "User does not have sufficient permissions "
                "to edit the bug task milestone.")
        else:
            self.milestone = new_milestone

    def transitionToImportance(self, new_importance, user):
        """See `IBugTask`."""
        if not self.userCanEditImportance(user):
            raise UserCannotEditBugTaskImportance(
                "User does not have sufficient permissions "
                "to edit the bug task importance.")
        else:
            self.importance = new_importance

    def setImportanceFromDebbugs(self, severity):
        """See `IBugTask`."""
        try:
            self.importance = debbugsseveritymap[severity]
        except KeyError:
            raise ValueError('Unknown debbugs severity "%s".' % severity)
        return self.importance

    def canTransitionToStatus(self, new_status, user):
        """See `IBugTask`."""
        celebrities = getUtility(ILaunchpadCelebrities)
        if (user.inTeam(self.pillar.bug_supervisor) or
            user.inTeam(self.pillar.owner) or
            user.id == celebrities.bug_watch_updater.id or
            user.id == celebrities.bug_importer.id or
            user.id == celebrities.janitor.id):
            return True
        else:
            return (self.status not in (
                        BugTaskStatus.WONTFIX, BugTaskStatus.FIXRELEASED)
                    and new_status not in BUG_SUPERVISOR_BUGTASK_STATUSES)

    def transitionToStatus(self, new_status, user, when=None):
        """See `IBugTask`."""
        if not new_status or user is None:
            # This is mainly to facilitate tests which, unlike the
            # normal status form, don't always submit a status when
            # testing the edit form.
            return

        if not self.canTransitionToStatus(new_status, user):
            raise UserCannotEditBugTaskStatus(
                "Only Bug Supervisors may change status to %s." % (
                    new_status.title,))

        if self.status == new_status:
            # No change in the status, so nothing to do.
            return

        old_status = self.status
        self.status = new_status

        if new_status == BugTaskStatus.UNKNOWN:
            # Ensure that all status-related dates are cleared,
            # because it doesn't make sense to have any values set for
            # date_confirmed, date_closed, etc. when the status
            # becomes UNKNOWN.
            self.date_confirmed = None
            self.date_inprogress = None
            self.date_closed = None
            self.date_incomplete = None
            self.date_triaged = None
            self.date_fix_committed = None
            self.date_fix_released = None

            return

        if when is None:
            UTC = pytz.timezone('UTC')
            when = datetime.datetime.now(UTC)

        # Record the date of the particular kinds of transitions into
        # certain states.
        if ((old_status < BugTaskStatus.CONFIRMED) and
            (new_status >= BugTaskStatus.CONFIRMED)):
            # Even if the bug task skips the Confirmed status
            # (e.g. goes directly to Fix Committed), we'll record a
            # confirmed date at the same time anyway, otherwise we get
            # a strange gap in our data, and potentially misleading
            # reports.
            self.date_confirmed = when

        if ((old_status < BugTaskStatus.INPROGRESS) and
            (new_status >= BugTaskStatus.INPROGRESS)):
            # Same idea with In Progress as the comment above about
            # Confirmed.
            self.date_inprogress = when

        if (old_status == BugTaskStatus.NEW and
            new_status > BugTaskStatus.NEW and
            self.date_left_new is None):
            # This task is leaving the NEW status for the first time
            self.date_left_new = when

        # If the new status is equal to or higher
        # than TRIAGED, we record a `date_triaged`
        # to mark the fact that the task has passed
        # through this status.
        if (old_status < BugTaskStatus.TRIAGED and
            new_status >= BugTaskStatus.TRIAGED):
            # This task is now marked as TRIAGED
            self.date_triaged = when

        # If the new status is equal to or higher
        # than FIXCOMMITTED, we record a `date_fixcommitted`
        # to mark the fact that the task has passed
        # through this status.
        if (old_status < BugTaskStatus.FIXCOMMITTED and
            new_status >= BugTaskStatus.FIXCOMMITTED):
            # This task is now marked as FIXCOMMITTED
            self.date_fix_committed = when

        # If the new status is equal to or higher
        # than FIXRELEASED, we record a `date_fixreleased`
        # to mark the fact that the task has passed
        # through this status.
        if (old_status < BugTaskStatus.FIXRELEASED and
            new_status >= BugTaskStatus.FIXRELEASED):
            # This task is now marked as FIXRELEASED
            self.date_fix_released = when

        # Bugs can jump in and out of 'incomplete' status
        # and for just as long as they're marked incomplete
        # we keep a date_incomplete recorded for them.
        if new_status == BugTaskStatus.INCOMPLETE:
            self.date_incomplete = when
        else:
            self.date_incomplete = None

        if ((old_status in UNRESOLVED_BUGTASK_STATUSES) and
            (new_status in RESOLVED_BUGTASK_STATUSES)):
            self.date_closed = when

        if ((old_status in RESOLVED_BUGTASK_STATUSES) and
            (new_status in UNRESOLVED_BUGTASK_STATUSES)):
            self.date_left_closed = when

        # Ensure that we don't have dates recorded for state
        # transitions, if the bugtask has regressed to an earlier
        # workflow state. We want to ensure that, for example, a
        # bugtask that went New => Confirmed => New
        # has a dateconfirmed value of None.
        if new_status in UNRESOLVED_BUGTASK_STATUSES:
            self.date_closed = None

        if new_status < BugTaskStatus.CONFIRMED:
            self.date_confirmed = None

        if new_status < BugTaskStatus.INPROGRESS:
            self.date_inprogress = None

        if new_status < BugTaskStatus.TRIAGED:
            self.date_triaged = None

        if new_status < BugTaskStatus.FIXCOMMITTED:
            self.date_fix_committed = None

        if new_status < BugTaskStatus.FIXRELEASED:
            self.date_fix_released = None

    def _userCanSetAssignee(self, user):
        """Used by methods to check if user can assign or unassign bugtask."""
        celebrities = getUtility(ILaunchpadCelebrities)
        return (
            user.inTeam(self.pillar.bug_supervisor) or
            user.inTeam(self.pillar.owner) or
            user.inTeam(self.pillar.driver) or
            (self.distroseries is not None and
             user.inTeam(self.distroseries.driver)) or
            (self.productseries is not None and
             user.inTeam(self.productseries.driver)) or
            user.inTeam(celebrities.admin)
            or user == celebrities.bug_importer)

    def userCanSetAnyAssignee(self, user):
        """See `IBugTask`."""
        if user is None:
            return False
        elif self.pillar.bug_supervisor is None:
            return True
        else:
            return self._userCanSetAssignee(user)

    def userCanUnassign(self, user):
        """True if user can set the assignee to None.

        This option not shown for regular users unless they or their teams
        are the assignees. Project owners, drivers, bug supervisors and
        Launchpad admins can always unassign.
        """
        return user is not None and (
            user.inTeam(self.assignee) or self._userCanSetAssignee(user))

    def canTransitionToAssignee(self, assignee):
        """See `IBugTask`."""
        # All users can assign and unassign themselves and their teams,
        # but only project owners, bug supervisors, project/distribution
        # drivers and Launchpad admins can assign others.
        user = getUtility(ILaunchBag).user
        return (
            user is not None and (
                user.inTeam(assignee) or
                (assignee is None and self.userCanUnassign(user)) or
                self.userCanSetAnyAssignee(user)))

    def transitionToAssignee(self, assignee):
        """See `IBugTask`."""
        if assignee == self.assignee:
            # No change to the assignee, so nothing to do.
            return

        if not self.canTransitionToAssignee(assignee):
            raise UserCannotEditBugTaskAssignee(
                'Regular users can assign and unassign only themselves and '
                'their teams. Only project owners, bug supervisors, drivers '
                'and release managers can assign others.')

        now = datetime.datetime.now(pytz.UTC)
        if self.assignee and not assignee:
            # The assignee is being cleared, so clear the date_assigned
            # value.
            self.date_assigned = None
        if not self.assignee and assignee:
            # The task is going from not having an assignee to having
            # one, so record when this happened
            self.date_assigned = now

        self.assignee = assignee

    def transitionToTarget(self, target):
        """See `IBugTask`.

        This method allows changing the target of some bug
        tasks. The rules it follows are similar to the ones
        enforced implicitly by the code in
        lib/canonical/launchpad/browser/bugtask.py#BugTaskEditView.
        """

        target_before_change = self.target

        if (self.milestone is not None and
            self.milestone.target != target):
            # If the milestone for this bugtask is set, we
            # have to make sure that it's a milestone of the
            # current target, or reset it to None
            self.milestone = None

        if IUpstreamBugTask.providedBy(self):
            if IProduct.providedBy(target):
                self.product = target
            else:
                raise IllegalTarget(
                    "Upstream bug tasks may only be re-targeted "
                    "to another project.")
        else:
            if (IDistributionSourcePackage.providedBy(target) and
                (target.distribution == self.target or
                 target.distribution == self.target.distribution)):
                self.sourcepackagename = target.sourcepackagename
            else:
                raise IllegalTarget(
                    "Distribution bug tasks may only be re-targeted "
                    "to a package in the same distribution.")

        # After the target has changed, we need to recalculate the maximum bug
        # heat for the new and old targets.
        if self.target != target_before_change:
            target_before_change.recalculateBugHeatCache()
            self.target.recalculateBugHeatCache()

    def updateTargetNameCache(self, newtarget=None):
        """See `IBugTask`."""
        if newtarget is None:
            newtarget = self.target
        targetname = newtarget.bugtargetdisplayname
        if self.targetnamecache != targetname:
            self.targetnamecache = targetname

    def getPackageComponent(self):
        """See `IBugTask`."""
        if ISourcePackage.providedBy(self.target):
            return self.target.latest_published_component
        if IDistributionSourcePackage.providedBy(self.target):
            spph = self.target.latest_overall_publication
            if spph:
                return spph.component
        return None

    def asEmailHeaderValue(self):
        """See `IBugTask`."""
        # Calculate an appropriate display value for the assignee.
        if self.assignee:
            if self.assignee.preferredemail:
                assignee_value = self.assignee.preferredemail.email
            else:
                # There is an assignee with no preferredemail, so we'll
                # "degrade" to the assignee.name. This might happen for teams
                # that don't have associated emails or when a bugtask was
                # imported from an external source and had its assignee set
                # automatically, even though the assignee may not even know
                # they have an account in Launchpad. :)
                assignee_value = self.assignee.name
        else:
            assignee_value = 'None'

        # Calculate an appropriate display value for the sourcepackage.
        if self.sourcepackagename:
            sourcepackagename_value = self.sourcepackagename.name
        else:
            # There appears to be no sourcepackagename associated with this
            # task.
            sourcepackagename_value = 'None'

        # Calculate an appropriate display value for the component, if the
        # target looks like some kind of source package.
        component = self.getPackageComponent()
        if component is None:
            component_name = 'None'
        else:
            component_name = component.name

        if IUpstreamBugTask.providedBy(self):
            header_value = 'product=%s;' % self.target.name
        elif IProductSeriesBugTask.providedBy(self):
            header_value = 'product=%s; productseries=%s;' % (
                self.productseries.product.name, self.productseries.name)
        elif IDistroBugTask.providedBy(self):
            header_value = ((
                'distribution=%(distroname)s; '
                'sourcepackage=%(sourcepackagename)s; '
                'component=%(componentname)s;') %
                {'distroname': self.distribution.name,
                 'sourcepackagename': sourcepackagename_value,
                 'componentname': component_name})
        elif IDistroSeriesBugTask.providedBy(self):
            header_value = ((
                'distribution=%(distroname)s; '
                'distroseries=%(distroseriesname)s; '
                'sourcepackage=%(sourcepackagename)s; '
                'component=%(componentname)s;') %
                {'distroname': self.distroseries.distribution.name,
                 'distroseriesname': self.distroseries.name,
                 'sourcepackagename': sourcepackagename_value,
                 'componentname': component_name})
        else:
            raise AssertionError('Unknown BugTask context: %r.' % self)

        # We only want to have a milestone field in the header if there's
        # a milestone set for the bug.
        if self.milestone:
            header_value += ' milestone=%s;' % self.milestone.name

        header_value += ((
            ' status=%(status)s; importance=%(importance)s; '
            'assignee=%(assignee)s;') %
            {'status': self.status.title,
             'importance': self.importance.title,
             'assignee': assignee_value})

        return header_value

    def getDelta(self, old_task):
        """See `IBugTask`."""
        valid_interfaces = [
            IUpstreamBugTask,
            IProductSeriesBugTask,
            IDistroBugTask,
            IDistroSeriesBugTask,
            ]

        # This tries to find a matching pair of bug tasks, i.e. where
        # both provide IUpstreamBugTask, or both IDistroBugTask.
        # Failing that, it drops off the bottom of the loop and raises
        # the TypeError.
        for interface in valid_interfaces:
            if interface.providedBy(self) and interface.providedBy(old_task):
                break
        else:
            raise TypeError(
                "Can't calculate delta on bug tasks of incompatible types: "
                "[%s, %s]." % (repr(old_task), repr(self)))

        # calculate the differences in the fields that both types of tasks
        # have in common
        changes = {}
        for field_name in ("target", "status", "importance",
                           "assignee", "bugwatch", "milestone"):
            old_val = getattr(old_task, field_name)
            new_val = getattr(self, field_name)
            if old_val != new_val:
                changes[field_name] = {}
                changes[field_name]["old"] = old_val
                changes[field_name]["new"] = new_val

        if changes:
            changes["bugtask"] = self
            return BugTaskDelta(**changes)
        else:
            return None

    def _userIsPillarEditor(self, user):
        """Can the user edit this tasks's pillar?"""
        if user is None:
            return False
        if IUpstreamBugTask.providedBy(self):
            pillar = self.product
        elif IProductSeriesBugTask.providedBy(self):
            pillar = self.productseries.product
        elif IDistroBugTask.providedBy(self):
            pillar = self.distribution
        else:
            pillar = self.distroseries.distribution
        return ((pillar.bug_supervisor is not None and
                 user.inTeam(pillar.bug_supervisor)) or
                pillar.userCanEdit(user))

    def userCanEditMilestone(self, user):
        """See `IBugTask`."""
        return self._userIsPillarEditor(user)

    def userCanEditImportance(self, user):
        """See `IBugTask`."""
        celebs = getUtility(ILaunchpadCelebrities)
        return (self._userIsPillarEditor(user) or
                user == celebs.bug_watch_updater or
                user == celebs.bug_importer)


def search_value_to_where_condition(search_value):
    """Convert a search value to a WHERE condition.

        >>> search_value_to_where_condition(any(1, 2, 3))
        'IN (1,2,3)'
        >>> search_value_to_where_condition(any()) is None
        True
        >>> search_value_to_where_condition(not_equals('foo'))
        "!= 'foo'"
        >>> search_value_to_where_condition(greater_than('foo'))
        "> 'foo'"
        >>> search_value_to_where_condition(1)
        '= 1'
        >>> search_value_to_where_condition(NULL)
        'IS NULL'

    """
    if zope_isinstance(search_value, any):
        # When an any() clause is provided, the argument value
        # is a list of acceptable filter values.
        if not search_value.query_values:
            return None
        return "IN (%s)" % ",".join(sqlvalues(*search_value.query_values))
    elif zope_isinstance(search_value, not_equals):
        return "!= %s" % sqlvalues(search_value.value)
    elif zope_isinstance(search_value, greater_than):
        return "> %s" % sqlvalues(search_value.value)
    elif search_value is not NULL:
        return "= %s" % sqlvalues(search_value)
    else:
        # The argument value indicates we should match
        # only NULL values for the column named by
        # arg_name.
        return "IS NULL"


def get_bug_privacy_filter(user):
    """An SQL filter for search results that adds privacy-awareness."""
    return get_bug_privacy_filter_with_decorator(user)[0]


def _nocache_bug_decorator(obj):
    """A pass through decorator for consistency.

    :seealso: get_bug_privacy_filter_with_decorator
    """
    return obj


def _make_cache_user_can_view_bug(user):
    """Curry a decorator for bugtask queries to cache permissions.

    :seealso: get_bug_privacy_filter_with_decorator
    """
    userid = user.id
    def cache_user_can_view_bug(bugtask):
        get_property_cache(bugtask.bug)._known_viewers = set([userid])
        return bugtask
    return cache_user_can_view_bug


def get_bug_privacy_filter_with_decorator(user):
    """Return a SQL filter to limit returned bug tasks.

    :return: A SQL filter, a decorator to cache visibility in a resultset that
        returns BugTask objects.
    """
    if user is None:
        return "Bug.private = FALSE", _nocache_bug_decorator
    admin_team = getUtility(ILaunchpadCelebrities).admin
    if user.inTeam(admin_team):
        return "", _nocache_bug_decorator
    # A subselect is used here because joining through
    # TeamParticipation is only relevant to the "user-aware"
    # part of the WHERE condition (i.e. the bit below.) The
    # other half of this condition (see code above) does not
    # use TeamParticipation at all.
    return ("""
        (Bug.private = FALSE OR EXISTS (
             SELECT BugSubscription.bug
             FROM BugSubscription, TeamParticipation
             WHERE TeamParticipation.person = %(personid)s AND
                   BugSubscription.person = TeamParticipation.team AND
                   BugSubscription.bug = Bug.id))
                     """ % sqlvalues(personid=user.id),
        _make_cache_user_can_view_bug(user))


def build_tag_set_query(joiner, tags):
    """Return an SQL snippet to find bugs matching the given tags.

    The tags are sorted so that testing the generated queries is
    easier and more reliable.

    :param joiner: The SQL set term used to join the individual tag
        clauses, typically "INTERSECT" or "UNION".
    :param tags: An iterable of valid tag names (not prefixed minus
        signs, not wildcards).
    """
    joiner = " %s " % joiner
    return joiner.join(
        "SELECT bug FROM BugTag WHERE tag = %s" % quote(tag)
        for tag in sorted(tags))


def build_tag_search_clause(tags_spec):
    """Return a tag search clause.

    :param tags_spec: An instance of `any` or `all` containing tag
        "specifications". A tag specification is a valid tag name
        optionally prefixed by a minus sign (denoting "not"), or an
        asterisk (denoting "any tag"), again optionally prefixed by a
        minus sign (and thus denoting "not any tag").
    """
    tags = set(tags_spec.query_values)
    wildcards = [tag for tag in tags if tag in ('*', '-*')]
    tags.difference_update(wildcards)
    include = [tag for tag in tags if not tag.startswith('-')]
    exclude = [tag[1:] for tag in tags if tag.startswith('-')]

    # Should we search for all specified tags or any of them?
    find_all = zope_isinstance(tags_spec, all)

    if find_all:
        # How to combine an include clause and an exclude clause when
        # both are generated.
        combine_with = 'AND'
        # The set of bugs that have *all* of the tags requested for
        # *inclusion*.
        include_clause = build_tag_set_query("INTERSECT", include)
        # The set of bugs that have *any* of the tags requested for
        # *exclusion*.
        exclude_clause = build_tag_set_query("UNION", exclude)
    else:
        # How to combine an include clause and an exclude clause when
        # both are generated.
        combine_with = 'OR'
        # The set of bugs that have *any* of the tags requested for
        # inclusion.
        include_clause = build_tag_set_query("UNION", include)
        # The set of bugs that have *all* of the tags requested for
        # exclusion.
        exclude_clause = build_tag_set_query("INTERSECT", exclude)

    # Search for the *presence* of any tag.
    if '*' in wildcards:
        # Only clobber the clause if not searching for all tags.
        if len(include_clause) == 0 or not find_all:
            include_clause = "SELECT bug FROM BugTag"

    # Search for the *absence* of any tag.
    if '-*' in wildcards:
        # Only clobber the clause if searching for all tags.
        if len(exclude_clause) == 0 or find_all:
            exclude_clause = "SELECT bug FROM BugTag"

    # Combine the include and exclude sets.
    if len(include_clause) > 0 and len(exclude_clause) > 0:
        return "(BugTask.bug IN (%s) %s BugTask.bug NOT IN (%s))" % (
            include_clause, combine_with, exclude_clause)
    elif len(include_clause) > 0:
        return "BugTask.bug IN (%s)" % include_clause
    elif len(exclude_clause) > 0:
        return "BugTask.bug NOT IN (%s)" % exclude_clause
    else:
        # This means that there were no tags (wildcard or specific) to
        # search for (which is allowed, even if it's a bit weird).
        return None


class BugTaskSet:
    """See `IBugTaskSet`."""
    implements(IBugTaskSet)

    _ORDERBY_COLUMN = None

    _open_resolved_upstream = """
                EXISTS (
                    SELECT TRUE FROM BugTask AS RelatedBugTask
                    WHERE RelatedBugTask.bug = BugTask.bug
                        AND RelatedBugTask.id != BugTask.id
                        AND ((
                            RelatedBugTask.bugwatch IS NOT NULL AND
                            RelatedBugTask.status %s)
                            OR (
                            RelatedBugTask.product IS NOT NULL AND
                            RelatedBugTask.bugwatch IS NULL AND
                            RelatedBugTask.status %s))
                    )
                """

    title = "A set of bug tasks"

    def get(self, task_id):
        """See `IBugTaskSet`."""
        # XXX: JSK: 2007-12-19: This method should probably return
        # None when task_id is not present. See:
        # https://bugs.launchpad.net/launchpad/+bug/123592
        try:
            bugtask = BugTask.get(task_id)
        except SQLObjectNotFound:
            raise NotFoundError("BugTask with ID %s does not exist." %
                                str(task_id))
        return bugtask

    def getBugTasks(self, bug_ids):
        """See `IBugTaskSet`."""
        from lp.bugs.model.bug import Bug
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        origin = [BugTask, Join(Bug, BugTask.bug == Bug.id)]
        columns = (Bug, BugTask)
        result = store.using(*origin).find(columns, Bug.id.is_in(bug_ids))
        bugs_and_tasks = {}
        for bug, task in result:
            if bug not in bugs_and_tasks:
                bugs_and_tasks[bug] = []
            bugs_and_tasks[bug].append(task)
        return bugs_and_tasks

    def getBugTaskBadgeProperties(self, bugtasks):
        """See `IBugTaskSet`."""
        # Import locally to avoid circular imports.
        from lp.blueprints.model.specificationbug import SpecificationBug
        from lp.bugs.model.bug import Bug
        from lp.bugs.model.bugbranch import BugBranch
        from lp.registry.model.mentoringoffer import MentoringOffer

        bug_ids = list(set(bugtask.bugID for bugtask in bugtasks))
        bug_ids_with_mentoring_offers = set(IStore(MentoringOffer).find(
                MentoringOffer.bugID, In(MentoringOffer.bugID, bug_ids)))
        bug_ids_with_specifications = set(IStore(SpecificationBug).find(
                SpecificationBug.bugID, In(SpecificationBug.bugID, bug_ids)))
        bug_ids_with_branches = set(IStore(BugBranch).find(
                BugBranch.bugID, In(BugBranch.bugID, bug_ids)))

        # Cache all bugs at once to avoid one query per bugtask. We
        # could rely on the Storm cache, but this is explicit.
        bugs = dict(IStore(Bug).find((Bug.id, Bug), In(Bug.id, bug_ids)))

        badge_properties = {}
        for bugtask in bugtasks:
            bug = bugs[bugtask.bugID]
            badge_properties[bugtask] = {
                'has_mentoring_offer':
                    bug.id in bug_ids_with_mentoring_offers,
                'has_specification':
                    bug.id in bug_ids_with_specifications,
                'has_branch':
                    bug.id in bug_ids_with_branches,
                'has_patch':
                    bug.latest_patch_uploaded is not None,
                }

        return badge_properties

    def getMultiple(self, task_ids):
        """See `IBugTaskSet`."""
        # Ensure we have a sequence of bug task IDs:
        task_ids = [int(task_id) for task_id in task_ids]
        # Query the database, returning the results in a dictionary:
        if len(task_ids) > 0:
            tasks = BugTask.select('id in %s' % sqlvalues(task_ids))
            return dict([(task.id, task) for task in tasks])
        else:
            return {}

    def findSimilar(self, user, summary, product=None, distribution=None,
                    sourcepackagename=None):
        """See `IBugTaskSet`."""
        if not summary:
            return EmptyResultSet()
        # Avoid circular imports.
        from lp.bugs.model.bug import Bug
        search_params = BugTaskSearchParams(user)
        constraint_clauses = ['BugTask.bug = Bug.id']
        if product:
            search_params.setProduct(product)
            constraint_clauses.append(
                'BugTask.product = %s' % sqlvalues(product))
        elif distribution:
            search_params.setDistribution(distribution)
            constraint_clauses.append(
                'BugTask.distribution = %s' % sqlvalues(distribution))
            if sourcepackagename:
                search_params.sourcepackagename = sourcepackagename
                constraint_clauses.append(
                    'BugTask.sourcepackagename = %s' % sqlvalues(
                        sourcepackagename))
        else:
            raise AssertionError('Need either a product or distribution.')

        search_params.fast_searchtext = nl_phrase_search(
            summary, Bug, ' AND '.join(constraint_clauses), ['BugTask'])
        return self.search(search_params, _noprejoins=True)

    def _buildStatusClause(self, status):
        """Return the SQL query fragment for search by status.

        Called from `buildQuery` or recursively."""
        if zope_isinstance(status, any):
            return '(' + ' OR '.join(
                self._buildStatusClause(dbitem)
                for dbitem
                in status.query_values) + ')'
        elif zope_isinstance(status, not_equals):
            return '(NOT %s)' % self._buildStatusClause(status.value)
        elif zope_isinstance(status, DBItem):
            with_response = (
                status == BugTaskStatusSearch.INCOMPLETE_WITH_RESPONSE)
            without_response = (
                status == BugTaskStatusSearch.INCOMPLETE_WITHOUT_RESPONSE)
            if with_response or without_response:
                status_clause = (
                    '(BugTask.status = %s) ' %
                    sqlvalues(BugTaskStatus.INCOMPLETE))
                if with_response:
                    status_clause += ("""
                        AND (Bug.date_last_message IS NOT NULL
                             AND BugTask.date_incomplete <=
                                 Bug.date_last_message)
                        """)
                elif without_response:
                    status_clause += ("""
                        AND (Bug.date_last_message IS NULL
                             OR BugTask.date_incomplete >
                                Bug.date_last_message)
                        """)
                else:
                    assert with_response != without_response
                return status_clause
            else:
                return '(BugTask.status = %s)' % sqlvalues(status)
        else:
            raise AssertionError(
                'Unrecognized status value: %s' % repr(status))

    def buildQuery(self, params):
        """Build and return an SQL query with the given parameters.

        Also return the clauseTables and orderBy for the generated query.

        :return: A query, the tables to query, ordering expression and a
            decorator to call on each returned row.
        """
        assert isinstance(params, BugTaskSearchParams)
        from lp.bugs.model.bug import Bug
        extra_clauses = ['Bug.id = BugTask.bug']
        clauseTables = [BugTask, Bug]
        decorators = []

        # These arguments can be processed in a loop without any other
        # special handling.
        standard_args = {
            'bug': params.bug,
            'importance': params.importance,
            'product': params.product,
            'distribution': params.distribution,
            'distroseries': params.distroseries,
            'productseries': params.productseries,
            'assignee': params.assignee,
            'sourcepackagename': params.sourcepackagename,
            'owner': params.owner,
            'date_closed': params.date_closed,
        }

        # Loop through the standard, "normal" arguments and build the
        # appropriate SQL WHERE clause. Note that arg_value will be one
        # of:
        #
        # * a searchbuilder.any object, representing a set of acceptable
        #   filter values
        # * a searchbuilder.NULL object
        # * an sqlobject
        # * a dbschema item
        # * None (meaning no filter criteria specified for that arg_name)
        #
        # XXX: kiko 2006-03-16:
        # Is this a good candidate for becoming infrastructure in
        # canonical.database.sqlbase?
        for arg_name, arg_value in standard_args.items():
            if arg_value is None:
                continue
            where_cond = search_value_to_where_condition(arg_value)
            if where_cond is not None:
                extra_clauses.append("BugTask.%s %s" % (arg_name, where_cond))

        if params.status is not None:
            extra_clauses.append(self._buildStatusClause(params.status))

        if params.milestone:
            if IProjectGroupMilestone.providedBy(params.milestone):
                where_cond = """
                    IN (SELECT Milestone.id
                        FROM Milestone, Product
                        WHERE Milestone.product = Product.id
                            AND Product.project = %s
                            AND Milestone.name = %s)
                """ % sqlvalues(params.milestone.target,
                                params.milestone.name)
            else:
                where_cond = search_value_to_where_condition(params.milestone)
            extra_clauses.append("BugTask.milestone %s" % where_cond)

        if params.project:
            # Circular.
            from lp.registry.model.product import Product
            clauseTables.append(Product)
            extra_clauses.append("BugTask.product = Product.id")
            if isinstance(params.project, any):
                extra_clauses.append("Product.project IN (%s)" % ",".join(
                    [str(proj.id) for proj in params.project.query_values]))
            elif params.project is NULL:
                extra_clauses.append("Product.project IS NULL")
            else:
                extra_clauses.append("Product.project = %d" %
                                     params.project.id)

        if params.omit_dupes:
            extra_clauses.append("Bug.duplicateof is NULL")

        if params.omit_targeted:
            extra_clauses.append("BugTask.distroseries is NULL AND "
                                 "BugTask.productseries is NULL")

        if params.has_cve:
            extra_clauses.append("BugTask.bug IN "
                                 "(SELECT DISTINCT bug FROM BugCve)")

        if params.attachmenttype is not None:
            if params.attachmenttype == BugAttachmentType.PATCH:
                extra_clauses.append("Bug.latest_patch_uploaded IS NOT NULL")
            else:
                attachment_clause = (
                    "Bug.id IN (SELECT bug from BugAttachment WHERE %s)")
                if isinstance(params.attachmenttype, any):
                    where_cond = "BugAttachment.type IN (%s)" % ", ".join(
                        sqlvalues(*params.attachmenttype.query_values))
                else:
                    where_cond = "BugAttachment.type = %s" % sqlvalues(
                        params.attachmenttype)
                extra_clauses.append(attachment_clause % where_cond)

        if params.searchtext:
            extra_clauses.append(self._buildSearchTextClause(params))

        if params.fast_searchtext:
            extra_clauses.append(self._buildFastSearchTextClause(params))

        if params.subscriber is not None:
            clauseTables.append(BugSubscription)
            extra_clauses.append("""Bug.id = BugSubscription.bug AND
                    BugSubscription.person = %(personid)s""" %
                    sqlvalues(personid=params.subscriber.id))

        if params.structural_subscriber is not None:
            structural_subscriber_clause = ("""BugTask.id IN (
                SELECT BugTask.id FROM BugTask, StructuralSubscription
                WHERE BugTask.product = StructuralSubscription.product
                  AND StructuralSubscription.subscriber = %(personid)s
                UNION ALL
                SELECT BugTask.id FROM BugTask, StructuralSubscription
                WHERE
                  BugTask.distribution = StructuralSubscription.distribution
                  AND BugTask.sourcepackagename =
                      StructuralSubscription.sourcepackagename
                  AND StructuralSubscription.subscriber = %(personid)s
                UNION ALL
                SELECT BugTask.id FROM BugTask, StructuralSubscription
                WHERE
                  BugTask.distroseries = StructuralSubscription.distroseries
                  AND StructuralSubscription.subscriber = %(personid)s
                UNION ALL
                SELECT BugTask.id FROM BugTask, StructuralSubscription
                WHERE
                  BugTask.milestone = StructuralSubscription.milestone
                  AND StructuralSubscription.subscriber = %(personid)s
                UNION ALL
                SELECT BugTask.id FROM BugTask, StructuralSubscription
                WHERE
                  BugTask.productseries = StructuralSubscription.productseries
                  AND StructuralSubscription.subscriber = %(personid)s
                UNION ALL
                SELECT BugTask.id FROM BugTask, StructuralSubscription, Product
                WHERE
                  BugTask.product = Product.id
                  AND Product.project = StructuralSubscription.project
                  AND StructuralSubscription.subscriber = %(personid)s
                UNION ALL
                SELECT BugTask.id FROM BugTask, StructuralSubscription
                WHERE
                  BugTask.distribution = StructuralSubscription.distribution
                  AND StructuralSubscription.sourcepackagename is NULL
                  AND StructuralSubscription.subscriber = %(personid)s)""" %
                sqlvalues(personid=params.structural_subscriber))
            extra_clauses.append(structural_subscriber_clause)

        if params.component:
            clauseTables += [SourcePackagePublishingHistory,
                             SourcePackageRelease]
            distroseries = None
            if params.distribution:
                distroseries = params.distribution.currentseries
            elif params.distroseries:
                distroseries = params.distroseries
            assert distroseries, (
                "Search by component requires a context with a distribution "
                "or distroseries.")

            if zope_isinstance(params.component, any):
                component_ids = sqlvalues(*params.component.query_values)
            else:
                component_ids = sqlvalues(params.component)

            distro_archive_ids = [
                archive.id
                for archive in distroseries.distribution.all_distro_archives]
            extra_clauses.extend(["""
            BugTask.sourcepackagename =
                SourcePackageRelease.sourcepackagename AND
            SourcePackageRelease.id =
                SourcePackagePublishingHistory.sourcepackagerelease AND
            SourcePackagePublishingHistory.distroseries = %s AND
            SourcePackagePublishingHistory.archive IN %s AND
            SourcePackagePublishingHistory.component IN %s AND
            SourcePackagePublishingHistory.status = %s
            """ % sqlvalues(distroseries,
                            distro_archive_ids,
                            component_ids,
                            PackagePublishingStatus.PUBLISHED)])

        upstream_clause = self._buildUpstreamClause(params)
        if upstream_clause:
            extra_clauses.append(upstream_clause)

        if params.tag:
            tag_clause = build_tag_search_clause(params.tag)
            if tag_clause is not None:
                extra_clauses.append(tag_clause)

        # XXX Tom Berger 2008-02-14:
        # We use StructuralSubscription to determine
        # the bug supervisor relation for distribution source
        # packages, following a conversion to use this object.
        # We know that the behaviour remains the same, but we
        # should change the terminology, or re-instate
        # PackageBugSupervisor, since the use of this relation here
        # is not for subscription to notifications.
        # See bug #191809
        if params.bug_supervisor:
            bug_supervisor_clause = """BugTask.id IN (
                SELECT BugTask.id FROM BugTask, Product
                WHERE BugTask.product = Product.id
                    AND Product.bug_supervisor = %(bug_supervisor)s
                UNION ALL
                SELECT BugTask.id
                FROM BugTask, StructuralSubscription
                WHERE
                  BugTask.distribution = StructuralSubscription.distribution
                    AND BugTask.sourcepackagename =
                        StructuralSubscription.sourcepackagename
                    AND StructuralSubscription.subscriber = %(bug_supervisor)s
                UNION ALL
                SELECT BugTask.id FROM BugTask, Distribution
                WHERE BugTask.distribution = Distribution.id
                    AND Distribution.bug_supervisor = %(bug_supervisor)s
                )""" % sqlvalues(bug_supervisor=params.bug_supervisor)
            extra_clauses.append(bug_supervisor_clause)

        if params.bug_reporter:
            bug_reporter_clause = (
                "BugTask.bug = Bug.id AND Bug.owner = %s" % sqlvalues(
                    params.bug_reporter))
            extra_clauses.append(bug_reporter_clause)

        if params.bug_commenter:
            bug_commenter_clause = """
            BugTask.id IN (
                SELECT BugTask.id FROM BugTask, BugMessage, Message
                WHERE Message.owner = %(bug_commenter)s
                    AND Message.id = BugMessage.message
                    AND BugTask.bug = BugMessage.bug
                    AND Message.id NOT IN (
                        SELECT BugMessage.message FROM BugMessage
                        WHERE BugMessage.bug = BugTask.bug
                        ORDER BY BugMessage.id
                        LIMIT 1
                    )
            )
            """ % sqlvalues(bug_commenter=params.bug_commenter)
            extra_clauses.append(bug_commenter_clause)

        if params.affects_me:
            params.affected_user = params.user
        if params.affected_user:
            affected_user_clause = """
            BugTask.id IN (
                SELECT BugTask.id FROM BugTask, BugAffectsPerson
                WHERE BugTask.bug = BugAffectsPerson.bug
                AND BugAffectsPerson.person = %(affected_user)s
                AND BugAffectsPerson.affected = TRUE
            )
            """ % sqlvalues(affected_user=params.affected_user)
            extra_clauses.append(affected_user_clause)

        if params.nominated_for:
            mappings = sqlvalues(
                target=params.nominated_for,
                nomination_status=BugNominationStatus.PROPOSED)
            if IDistroSeries.providedBy(params.nominated_for):
                mappings['target_column'] = 'distroseries'
            elif IProductSeries.providedBy(params.nominated_for):
                mappings['target_column'] = 'productseries'
            else:
                raise AssertionError(
                    'Unknown nomination target: %r.' % params.nominated_for)
            nominated_for_clause = """
                BugNomination.bug = BugTask.bug AND
                BugNomination.%(target_column)s = %(target)s AND
                BugNomination.status = %(nomination_status)s
                """ % mappings
            extra_clauses.append(nominated_for_clause)
            clauseTables.append(BugNomination)

        clause, decorator = get_bug_privacy_filter_with_decorator(params.user)
        if clause:
            extra_clauses.append(clause)
            decorators.append(decorator)

        hw_clause = self._buildHardwareRelatedClause(params)
        if hw_clause is not None:
            extra_clauses.append(hw_clause)

        if params.linked_branches == BugBranchSearch.BUGS_WITH_BRANCHES:
            extra_clauses.append(
                """EXISTS (
                    SELECT id FROM BugBranch WHERE BugBranch.bug=Bug.id)
                """)
        elif params.linked_branches == BugBranchSearch.BUGS_WITHOUT_BRANCHES:
            extra_clauses.append(
                """NOT EXISTS (
                    SELECT id FROM BugBranch WHERE BugBranch.bug=Bug.id)
                """)
        else:
            # If no branch specific search restriction is specified,
            # we don't need to add any clause.
            pass

        if params.modified_since:
            extra_clauses.append(
                "Bug.date_last_updated > %s" % (
                    sqlvalues(params.modified_since,)))

        if params.created_since:
            extra_clauses.append(
                "BugTask.datecreated > %s" % (
                    sqlvalues(params.created_since,)))

        orderby_arg = self._processOrderBy(params)

        query = " AND ".join(extra_clauses)

        if not decorators:
            decorator = lambda x: x
        else:
            def decorator(obj):
                for decor in decorators:
                    obj = decor(obj)
                return obj
        return query, clauseTables, orderby_arg, decorator

    def _buildUpstreamClause(self, params):
        """Return an clause for returning upstream data if the data exists.

        This method will handles BugTasks that do not have upstream BugTasks
        as well as thoses that do.
        """
        upstream_clauses = []
        if params.pending_bugwatch_elsewhere:
            if params.product:
                # Include only bugtasks that do no have bug watches that
                # belong to a product that does not use Malone.
                pending_bugwatch_elsewhere_clause = """
                    EXISTS (
                        SELECT TRUE
                        FROM BugTask AS RelatedBugTask
                            LEFT OUTER JOIN Product AS OtherProduct
                                ON RelatedBugTask.product = OtherProduct.id
                        WHERE RelatedBugTask.bug = BugTask.bug
                            AND RelatedBugTask.id = BugTask.id
                            AND RelatedBugTask.bugwatch IS NULL
                            AND OtherProduct.official_malone IS FALSE
                            AND RelatedBugTask.status != %s)
                    """ % sqlvalues(BugTaskStatus.INVALID)
            else:
                # Include only bugtasks that have other bugtasks on targets
                # not using Malone, which are not Invalid, and have no bug
                # watch.
                pending_bugwatch_elsewhere_clause = """
                    EXISTS (
                        SELECT TRUE
                        FROM BugTask AS RelatedBugTask
                            LEFT OUTER JOIN Distribution AS OtherDistribution
                                ON RelatedBugTask.distribution =
                                    OtherDistribution.id
                            LEFT OUTER JOIN Product AS OtherProduct
                                ON RelatedBugTask.product = OtherProduct.id
                        WHERE RelatedBugTask.bug = BugTask.bug
                            AND RelatedBugTask.id != BugTask.id
                            AND RelatedBugTask.bugwatch IS NULL
                            AND (
                                OtherDistribution.official_malone IS FALSE
                                OR OtherProduct.official_malone IS FALSE)
                            AND RelatedBugTask.status != %s)
                    """ % sqlvalues(BugTaskStatus.INVALID)

            upstream_clauses.append(pending_bugwatch_elsewhere_clause)

        if params.has_no_upstream_bugtask:
            # Find all bugs that has no product bugtask. We limit the
            # SELECT by matching against BugTask.bug to make the query
            # faster.
            has_no_upstream_bugtask_clause = """
                NOT EXISTS (SELECT TRUE
                            FROM BugTask AS OtherBugTask
                            WHERE OtherBugTask.bug = BugTask.bug
                                AND OtherBugTask.product IS NOT NULL)
            """
            upstream_clauses.append(has_no_upstream_bugtask_clause)

        # Our definition of "resolved upstream" means:
        #
        # * bugs with bugtasks linked to watches that are invalid,
        #   fixed committed or fix released
        #
        # * bugs with upstream bugtasks that are fix committed or fix released
        #
        # This definition of "resolved upstream" should address the use
        # cases we gathered at UDS Paris (and followup discussions with
        # seb128, sfllaw, et al.)
        if params.resolved_upstream:
            statuses_for_watch_tasks = [
                BugTaskStatus.INVALID,
                BugTaskStatus.FIXCOMMITTED,
                BugTaskStatus.FIXRELEASED]
            statuses_for_upstream_tasks = [
                BugTaskStatus.FIXCOMMITTED,
                BugTaskStatus.FIXRELEASED]

            only_resolved_upstream_clause = self._open_resolved_upstream % (
                    search_value_to_where_condition(
                        any(*statuses_for_watch_tasks)),
                    search_value_to_where_condition(
                        any(*statuses_for_upstream_tasks)))
            upstream_clauses.append(only_resolved_upstream_clause)
        if params.open_upstream:
            statuses_for_open_tasks = [
                BugTaskStatus.NEW,
                BugTaskStatus.INCOMPLETE,
                BugTaskStatus.CONFIRMED,
                BugTaskStatus.INPROGRESS,
                BugTaskStatus.UNKNOWN]
            only_open_upstream_clause = self._open_resolved_upstream % (
                    search_value_to_where_condition(
                        any(*statuses_for_open_tasks)),
                    search_value_to_where_condition(
                        any(*statuses_for_open_tasks)))
            upstream_clauses.append(only_open_upstream_clause)

        if upstream_clauses:
            upstream_clause = " OR ".join(upstream_clauses)
            return '(%s)' % upstream_clause
        return None

    def _buildSearchTextClause(self, params):
        """Build the clause for searchtext."""
        assert params.fast_searchtext is None, (
            'Cannot use fast_searchtext at the same time as searchtext.')

        searchtext_quoted = quote(params.searchtext)
        searchtext_like_quoted = quote_like(params.searchtext)

        if params.orderby is None:
            # Unordered search results aren't useful, so sort by relevance
            # instead.
            params.orderby = [
                SQLConstant("-rank(Bug.fti, ftq(%s))" % searchtext_quoted),
                SQLConstant(
                    "-rank(BugTask.fti, ftq(%s))" % searchtext_quoted)]

        comment_clause = """BugTask.id IN (
            SELECT BugTask.id
            FROM BugTask, BugMessage,Message, MessageChunk
            WHERE BugMessage.bug = BugTask.bug
                AND BugMessage.message = Message.id
                AND Message.id = MessageChunk.message
                AND MessageChunk.fti @@ ftq(%s))""" % searchtext_quoted
        text_search_clauses = [
            "Bug.fti @@ ftq(%s)" % searchtext_quoted,
            "BugTask.fti @@ ftq(%s)" % searchtext_quoted,
            "BugTask.targetnamecache ILIKE '%%' || %s || '%%'" % (
                searchtext_like_quoted)]
        # Due to performance problems, whether to search in comments is
        # controlled by a config option.
        if config.malone.search_comments:
            text_search_clauses.append(comment_clause)
        return "(%s)" % " OR ".join(text_search_clauses)

    def _buildFastSearchTextClause(self, params):
        """Build the clause to use for the fast_searchtext criteria."""
        assert params.searchtext is None, (
            'Cannot use searchtext at the same time as fast_searchtext.')

        fast_searchtext_quoted = quote(params.fast_searchtext)

        if params.orderby is None:
            # Unordered search results aren't useful, so sort by relevance
            # instead.
            params.orderby = [
                SQLConstant("-rank(Bug.fti, ftq(%s))" %
                fast_searchtext_quoted)]

        return "Bug.fti @@ ftq(%s)" % fast_searchtext_quoted

    def _buildHardwareRelatedClause(self, params):
        """Hardware related SQL expressions and tables for bugtask searches.

        :return: (tables, clauses) where clauses is a list of SQL expressions
            which limit a bugtask search to bugs related to a device or
            driver specified in search_params. If search_params contains no
            hardware related data, empty lists are returned.
        :param params: A `BugTaskSearchParams` instance.

        Device related WHERE clauses are returned if
        params.hardware_bus, params.hardware_vendor_id,
        params.hardware_product_id are all not None.
        """
        # Avoid cyclic imports.
        from lp.hardwaredb.model.hwdb import (
            HWSubmission, HWSubmissionBug, HWSubmissionDevice,
            _userCanAccessSubmissionStormClause,
            make_submission_device_statistics_clause)
        from lp.bugs.model.bug import Bug, BugAffectsPerson

        bus = params.hardware_bus
        vendor_id = params.hardware_vendor_id
        product_id = params.hardware_product_id
        driver_name = params.hardware_driver_name
        package_name = params.hardware_driver_package_name

        if (bus is not None and vendor_id is not None and
            product_id is not None):
            tables, clauses = make_submission_device_statistics_clause(
                bus, vendor_id, product_id, driver_name, package_name, False)
        elif driver_name is not None or package_name is not None:
            tables, clauses = make_submission_device_statistics_clause(
                None, None, None, driver_name, package_name, False)
        else:
            return None

        tables.append(HWSubmission)
        tables.append(Bug)
        clauses.append(HWSubmissionDevice.submission == HWSubmission.id)
        bug_link_clauses = []
        if params.hardware_owner_is_bug_reporter:
            bug_link_clauses.append(
                HWSubmission.ownerID == Bug.ownerID)
        if params.hardware_owner_is_affected_by_bug:
            bug_link_clauses.append(
                And(BugAffectsPerson.personID == HWSubmission.ownerID,
                    BugAffectsPerson.bug == Bug.id,
                    BugAffectsPerson.affected))
            tables.append(BugAffectsPerson)
        if params.hardware_owner_is_subscribed_to_bug:
            bug_link_clauses.append(
                And(BugSubscription.person_id == HWSubmission.ownerID,
                    BugSubscription.bug_id == Bug.id))
            tables.append(BugSubscription)
        if params.hardware_is_linked_to_bug:
            bug_link_clauses.append(
                And(HWSubmissionBug.bugID == Bug.id,
                    HWSubmissionBug.submissionID == HWSubmission.id))
            tables.append(HWSubmissionBug)

        if len(bug_link_clauses) == 0:
            return None

        clauses.append(Or(*bug_link_clauses))
        clauses.append(_userCanAccessSubmissionStormClause(params.user))

        tables = [convert_storm_clause_to_string(table) for table in tables]
        clauses = ['(%s)' % convert_storm_clause_to_string(clause)
                   for clause in clauses]
        clause = 'Bug.id IN (SELECT DISTINCT Bug.id from %s WHERE %s)' % (
            ', '.join(tables), ' AND '.join(clauses))
        return clause

    def search(self, params, *args, **kwargs):
        """See `IBugTaskSet`.

        :param _noprejoins: Private internal parameter to BugTaskSet which
            disables all use of prejoins : consolidated from code paths that
            claim they were inefficient and unwanted.
        """
        # Circular.
        from lp.registry.model.product import Product
        from lp.bugs.model.bug import Bug
        _noprejoins = kwargs.get('_noprejoins', False)
        store = IStore(BugTask)
        query, clauseTables, orderby, bugtask_decorator = self.buildQuery(
            params)
        if len(args) == 0:
            if _noprejoins:
                resultset = store.find(BugTask,
                    AutoTables(SQL("1=1"), clauseTables),
                    query)
                decorator = bugtask_decorator
            else:
                tables = clauseTables + [Product, SourcePackageName]
                origin = [
                    BugTask,
                    LeftJoin(Bug, BugTask.bug == Bug.id),
                    LeftJoin(Product, BugTask.product == Product.id),
                    LeftJoin(
                        SourcePackageName,
                        BugTask.sourcepackagename == SourcePackageName.id),
                    ]
                # NB: these may work with AutoTables, but its hard to tell,
                # this way is known to work.
                if BugNomination in tables:
                    # The relation is already in query.
                    origin.append(BugNomination)
                if BugSubscription in tables:
                    # The relation is already in query.
                    origin.append(BugSubscription)
                if SourcePackageRelease in tables:
                    origin.append(SourcePackageRelease)
                if SourcePackagePublishingHistory in tables:
                    origin.append(SourcePackagePublishingHistory)
                resultset = store.using(*origin).find(
                    (BugTask, Product, SourcePackageName, Bug),
                    AutoTables(SQL("1=1"), tables),
                    query)
                decorator=lambda row: bugtask_decorator(row[0])
            resultset.order_by(orderby)
            return DecoratedResultSet(resultset, result_decorator=decorator)

        bugtask_fti = SQL('BugTask.fti')
        result = store.find((BugTask, bugtask_fti), query,
                            AutoTables(SQL("1=1"), clauseTables))
        decorators = [bugtask_decorator]
        for arg in args:
            query, clauseTables, dummy, decorator = self.buildQuery(arg)
            result = result.union(
                store.find((BugTask, bugtask_fti), query,
                           AutoTables(SQL("1=1"), clauseTables)))
            # NB: assumes the decorators are all compatible.
            # This may need revisiting if e.g. searches on behalf of different
            # users are combined.
            decorators.append(decorator)
        def decorator(row):
            bugtask = row[0]
            for decorator in decorators:
                bugtask = decorator(bugtask)
            return bugtask

        # Build up the joins.
        # TODO: implement _noprejoins for this code path: as of 20100818 it
        # has been silently disabled because clients of the API were setting
        # prejoins=[] which had no effect; this TODO simply notes the reality
        # already existing when it was added.
        joins = Alias(result._get_select(), "BugTask")
        joins = Join(joins, Bug, BugTask.bug == Bug.id)
        joins = LeftJoin(joins, Product, BugTask.product == Product.id)
        joins = LeftJoin(joins, SourcePackageName,
                         BugTask.sourcepackagename == SourcePackageName.id)

        result = store.using(joins).find(
            (BugTask, Bug, Product, SourcePackageName))
        result.order_by(orderby)
        return DecoratedResultSet(result, result_decorator=decorator)

    def searchBugIds(self, params):
        """See `IBugTaskSet`."""
        query, clauseTables, orderby, decorator = self.buildQuery(
            params)
        store = IStore(BugTask)
        resultset = store.find(BugTask.bugID,
            AutoTables(SQL("1=1"), clauseTables), query)
        resultset.order_by(orderby)
        return resultset

    def getAssignedMilestonesFromSearch(self, search_results):
        """See `IBugTaskSet`."""
        # XXX: Gavin Panella 2009-03-05 bug=338184: There is currently
        # no clean way to get the underlying Storm ResultSet from an
        # SQLObjectResultSet, so we must remove the security proxy for
        # a moment.
        if ISQLObjectResultSet.providedBy(search_results):
            search_results = removeSecurityProxy(search_results)._result_set
        # Check that we have a Storm result set before we start doing
        # things with it.
        assert IResultSet.providedBy(search_results), (
            "search_results must provide IResultSet or ISQLObjectResultSet")
        # Remove ordering and make distinct.
        search_results = search_results.order_by().config(distinct=True)
        # Get milestone IDs.
        milestone_ids = [
            milestone_id for milestone_id in (
                search_results.values(BugTask.milestoneID))
            if milestone_id is not None]
        # Query for milestones.
        if len(milestone_ids) == 0:
            return []
        else:
            # Import here because of cyclic references.
            from lp.registry.model.milestone import (
                Milestone, milestone_sort_key)
            # We need the store that was used, we have no objects to key off
            # of other than the search result, and Store.of() doesn't
            # currently work on result sets. Additionally it may be a
            # DecoratedResultSet.
            if zope_isinstance(search_results, DecoratedResultSet):
                store = removeSecurityProxy(search_results).result_set._store
            else:
                store = search_results._store
            milestones = store.find(
                Milestone, In(Milestone.id, milestone_ids))
            return sorted(milestones, key=milestone_sort_key, reverse=True)

    def createTask(self, bug, owner, product=None, productseries=None,
                   distribution=None, distroseries=None,
                   sourcepackagename=None,
                   status=IBugTask['status'].default,
                   importance=IBugTask['importance'].default,
                   assignee=None, milestone=None):
        """See `IBugTaskSet`."""
        if not status:
            status = IBugTask['status'].default
        if not importance:
            importance = IBugTask['importance'].default
        if not assignee:
            assignee = None
        if not milestone:
            milestone = None

        if not bug.private and bug.security_related:
            if product and product.security_contact:
                bug.subscribe(product.security_contact, owner)
            elif distribution and distribution.security_contact:
                bug.subscribe(distribution.security_contact, owner)

        assert (product or productseries or distribution or distroseries), (
            'Got no bugtask target.')

        non_target_create_params = dict(
            bug=bug,
            status=status,
            importance=importance,
            assignee=assignee,
            owner=owner,
            milestone=milestone)
        bugtask = BugTask(
            product=product,
            productseries=productseries,
            distribution=distribution,
            distroseries=distroseries,
            sourcepackagename=sourcepackagename,
            **non_target_create_params)

        if distribution:
            # Create tasks for accepted nominations if this is a source
            # package addition.
            accepted_nominations = [
                nomination for nomination in bug.getNominations(distribution)
                if nomination.isApproved()]
            for nomination in accepted_nominations:
                accepted_series_task = BugTask(
                    distroseries=nomination.distroseries,
                    sourcepackagename=sourcepackagename,
                    **non_target_create_params)
                accepted_series_task.updateTargetNameCache()

        if bugtask.conjoined_slave:
            bugtask._syncFromConjoinedSlave()

        bugtask.updateTargetNameCache()
        del get_property_cache(bug).bugtasks
        # Because of block_implicit_flushes, it is possible for a new bugtask
        # to be queued in appropriately, which leads to Bug.bugtasks not
        # finding the bugtask.
        Store.of(bugtask).flush()
        return bugtask

    def getStatusCountsForProductSeries(self, user, product_series):
        """See `IBugTaskSet`."""
        bug_privacy_filter = get_bug_privacy_filter(user)
        if bug_privacy_filter != "":
            bug_privacy_filter = 'AND ' + bug_privacy_filter
        cur = cursor()

        # The union is actually much faster than a LEFT JOIN with the
        # Milestone table, since postgres optimizes it to perform index
        # scans instead of sequential scans on the BugTask table.
        query = """
            SELECT status, count(*)
            FROM (
                SELECT BugTask.status
                FROM BugTask
                    JOIN Bug ON BugTask.bug = Bug.id
                WHERE
                    BugTask.productseries = %(series)s
                    %(privacy)s

                UNION ALL

                SELECT BugTask.status
                FROM BugTask
                    JOIN Bug ON BugTask.bug = Bug.id
                    JOIN Milestone ON BugTask.milestone = Milestone.id
                WHERE
                    BugTask.productseries IS NULL
                    AND Milestone.productseries = %(series)s
                    %(privacy)s
                ) AS subquery
            GROUP BY status
            """ % dict(series=quote(product_series),
                       privacy=bug_privacy_filter)

        cur.execute(query)
        return cur.fetchall()

    def findExpirableBugTasks(self, min_days_old, user,
                              bug=None, target=None):
        """See `IBugTaskSet`.

        The list of Incomplete bugtasks is selected from products and
        distributions that use Launchpad to track bugs. To qualify for
        expiration, the bug and its bugtasks meet the follow conditions:

        1. The bug is inactive; the last update of the is older than
            Launchpad expiration age.
        2. The bug is not a duplicate.
        3. The bug does not have any other valid bugtasks.
        4. The bugtask belongs to a project with enable_bug_expiration set
           to True.
        5. The bugtask has the status Incomplete.
        6. The bugtask is not assigned to anyone.
        7. The bugtask does not have a milestone.

        Bugtasks cannot transition to Invalid automatically unless they meet
        all the rules stated above.

        This implementation returns the master of the master-slave conjoined
        pairs of bugtasks. Slave conjoined bugtasks are not included in the
        list because they can only be expired by calling the master bugtask's
        transitionToStatus() method. See 'Conjoined Bug Tasks' in
        c.l.doc/bugtasks.txt.

        Only bugtasks the specified user has permission to view are
        returned. The Janitor celebrity has permission to view all bugs.
        """
        if bug is None:
            bug_clause = ''
        else:
            bug_clause = 'AND Bug.id = %s' % sqlvalues(bug)

        if user == getUtility(ILaunchpadCelebrities).janitor:
            # The janitor needs access to all bugs.
            bug_privacy_filter = ''
        else:
            bug_privacy_filter = get_bug_privacy_filter(user)
            if bug_privacy_filter != '':
                bug_privacy_filter = "AND " + bug_privacy_filter
        unconfirmed_bug_condition = self._getUnconfirmedBugCondition()
        (target_join, target_clause) = self._getTargetJoinAndClause(target)
        expirable_bugtasks = BugTask.select("""
            BugTask.bug = Bug.id
            AND BugTask.id IN (
                SELECT BugTask.id
                FROM BugTask
                    JOIN Bug ON BugTask.bug = Bug.id
                    LEFT JOIN BugWatch on Bug.id = BugWatch.bug
                """ + target_join + """
                WHERE
                """ + target_clause + """
                """ + bug_clause + """
                """ + bug_privacy_filter + """
                    AND BugTask.status = %s
                    AND BugTask.assignee IS NULL
                    AND BugTask.milestone IS NULL
                    AND Bug.duplicateof IS NULL
                    AND Bug.date_last_updated < CURRENT_TIMESTAMP
                        AT TIME ZONE 'UTC' - interval '%s days'
                    AND BugWatch.id IS NULL
            )""" % sqlvalues(BugTaskStatus.INCOMPLETE, min_days_old) +
            unconfirmed_bug_condition,
            clauseTables=['Bug'],
            orderBy='Bug.date_last_updated')

        return expirable_bugtasks

    def _getUnconfirmedBugCondition(self):
        """Return the SQL to filter out BugTasks that has been confirmed

        A bugtasks cannot expire if the bug is, has been, or
        will be, confirmed to be legitimate. Once the bug is considered
        valid for one target, it is valid for all targets.
        """
        statuses_not_preventing_expiration = [
            BugTaskStatus.INVALID, BugTaskStatus.INCOMPLETE,
            BugTaskStatus.WONTFIX]

        unexpirable_status_list = [
            status for status in BugTaskStatus.items
            if status not in statuses_not_preventing_expiration]

        return """
             AND NOT EXISTS (
                SELECT TRUE
                FROM BugTask AS RelatedBugTask
                WHERE RelatedBugTask.bug = BugTask.bug
                    AND RelatedBugTask.status IN %s)
            """ % sqlvalues(unexpirable_status_list)

    def _getTargetJoinAndClause(self, target):
        """Return a SQL join clause to a `BugTarget`.

        :param target: A supported BugTarget or None. The target param must
            be either a Distribution, DistroSeries, Product, or ProductSeries.
            If target is None, the clause joins BugTask to all the supported
            BugTarget tables.
        :raises NotImplementedError: If the target is an IProjectGroup,
            ISourcePackage, or an IDistributionSourcePackage.
        :raises AssertionError: If the target is not a known implementer of
            `IBugTarget`
        """
        target_join = """
            JOIN (
                -- We create this rather bizarre looking structure
                -- because we must replicate the behaviour of BugTask since
                -- we are joining to it. So when distroseries is set,
                -- distribution should be NULL. The two pillar columns will
                -- be used in the WHERE clause.
                SELECT 0 AS distribution, 0 AS distroseries,
                       0 AS product , 0 AS productseries,
                       0 AS distribution_pillar, 0 AS product_pillar
                UNION
                    SELECT Distribution.id, NULL, NULL, NULL,
                        Distribution.id, NULL
                    FROM Distribution
                    WHERE Distribution.enable_bug_expiration IS TRUE
                UNION
                    SELECT NULL, DistroSeries.id, NULL, NULL,
                        Distribution.id, NULL
                    FROM DistroSeries
                        JOIN Distribution
                            ON DistroSeries.distribution = Distribution.id
                    WHERE Distribution.enable_bug_expiration IS TRUE
                UNION
                    SELECT NULL, NULL, Product.id, NULL,
                        NULL, Product.id
                    FROM Product
                    WHERE Product.enable_bug_expiration IS TRUE
                UNION
                    SELECT NULL, NULL, NULL, ProductSeries.id,
                        NULL, Product.id
                    FROM ProductSeries
                        JOIN Product
                            ON ProductSeries.Product = Product.id
                    WHERE Product.enable_bug_expiration IS TRUE) target
                ON (BugTask.distribution = target.distribution
                    OR BugTask.distroseries = target.distroseries
                    OR BugTask.product = target.product
                    OR BugTask.productseries = target.productseries)"""
        if target is None:
            target_clause = "TRUE IS TRUE"
        elif IDistribution.providedBy(target):
            target_clause = "target.distribution_pillar = %s" % sqlvalues(
                target)
        elif IDistroSeries.providedBy(target):
            target_clause = "BugTask.distroseries = %s" % sqlvalues(target)
        elif IProduct.providedBy(target):
            target_clause = "target.product_pillar = %s" % sqlvalues(target)
        elif IProductSeries.providedBy(target):
            target_clause = "BugTask.productseries = %s" % sqlvalues(target)
        elif (IProjectGroup.providedBy(target)
              or ISourcePackage.providedBy(target)
              or IDistributionSourcePackage.providedBy(target)):
            raise NotImplementedError(
                "BugTarget %s is not supported by ." % target)
        else:
            raise AssertionError("Unknown BugTarget type.")

        return (target_join, target_clause)

    def maintainedBugTasks(self, person, minimportance=None,
                           showclosed=False, orderBy=None, user=None):
        """See `IBugTaskSet`."""
        filters = ['BugTask.bug = Bug.id',
                   'BugTask.product = Product.id',
                   'Product.owner = TeamParticipation.team',
                   'TeamParticipation.person = %s' % person.id]

        if not showclosed:
            committed = BugTaskStatus.FIXCOMMITTED
            filters.append('BugTask.status < %s' % sqlvalues(committed))

        if minimportance is not None:
            filters.append(
                'BugTask.importance >= %s' % sqlvalues(minimportance))

        privacy_filter = get_bug_privacy_filter(user)
        if privacy_filter:
            filters.append(privacy_filter)

        # We shouldn't show duplicate bug reports.
        filters.append('Bug.duplicateof IS NULL')

        return BugTask.select(" AND ".join(filters),
            clauseTables=['Product', 'TeamParticipation', 'BugTask', 'Bug'])

    def getOpenBugTasksPerProduct(self, user, products):
        """See `IBugTaskSet`."""
        # Local import of Bug to avoid import loop.
        from lp.bugs.model.bug import Bug
        store = getUtility(IStoreSelector).get(MAIN_STORE, DEFAULT_FLAVOR)
        origin = [
            Bug,
            Join(BugTask, BugTask.bug == Bug.id),
            ]

        product_ids = [product.id for product in products]
        conditions = And(BugTask.status.is_in(UNRESOLVED_BUGTASK_STATUSES),
                         Bug.duplicateof == None,
                         BugTask.productID.is_in(product_ids))

        privacy_filter = get_bug_privacy_filter(user)
        if privacy_filter != '':
            conditions = And(conditions, privacy_filter)
        result = store.using(*origin).find(
            (BugTask.productID, SQL('COUNT(*)')),
            conditions)

        result = result.group_by(BugTask.productID)
        # The result will return a list of product ids and counts,
        # which will be converted into key-value pairs in the dictionary.
        return dict(result)

    def getOrderByColumnDBName(self, col_name):
        """See `IBugTaskSet`."""
        if BugTaskSet._ORDERBY_COLUMN is None:
            # Local import of Bug to avoid import loop.
            from lp.bugs.model.bug import Bug
            BugTaskSet._ORDERBY_COLUMN = {
                "id": BugTask.bugID,
                "importance": BugTask.importance,
                # TODO: sort by their name?
                "assignee": BugTask.assigneeID,
                "targetname": BugTask.targetnamecache,
                "status": BugTask.status,
                "title": Bug.title,
                "milestone": BugTask.milestoneID,
                "dateassigned": BugTask.date_assigned,
                "datecreated": BugTask.datecreated,
                "date_last_updated": Bug.date_last_updated,
                "date_closed": BugTask.date_closed,
                "number_of_duplicates": Bug.number_of_duplicates,
                "message_count": Bug.message_count,
                "users_affected_count": Bug.users_affected_count,
                "heat": Bug.heat,
                "latest_patch_uploaded": Bug.latest_patch_uploaded,
                }
        return BugTaskSet._ORDERBY_COLUMN[col_name]

    def _processOrderBy(self, params):
        """Process the orderby parameter supplied to search().

        This method ensures the sort order will be stable, and converting
        the string supplied to actual column names.

        :return: A Storm order_by tuple.
        """
        # Local import of Bug to avoid import loop.
        from lp.bugs.model.bug import Bug
        orderby = params.orderby
        if orderby is None:
            orderby = []
        elif not zope_isinstance(orderby, (list, tuple)):
            orderby = [orderby]

        orderby_arg = []
        # This set contains columns which are, in practical terms,
        # unique. When these columns are used as sort keys, they ensure
        # the sort will be consistent. These columns will be used to
        # decide whether we need to add the BugTask.bug and BugTask.id
        # columns to make the sort consistent over runs -- which is good
        # for the user and essential for the test suite.
        unambiguous_cols = set([
            BugTask.date_assigned,
            BugTask.datecreated,
            Bug.datecreated,
            Bug.date_last_updated])
        # Bug ID is unique within bugs on a product or source package.
        if (params.product or
            (params.distribution and params.sourcepackagename) or
            (params.distroseries and params.sourcepackagename)):
            in_unique_context = True
        else:
            in_unique_context = False

        if in_unique_context:
            unambiguous_cols.add(BugTask.bug)

        # Translate orderby keys into corresponding Table.attribute
        # strings.
        ambiguous = True
        for orderby_col in orderby:
            if isinstance(orderby_col, SQLConstant):
                orderby_arg.append(orderby_col)
                continue
            if orderby_col.startswith("-"):
                col = self.getOrderByColumnDBName(orderby_col[1:])
                order_clause = Desc(col)
            else:
                col = self.getOrderByColumnDBName(orderby_col)
                order_clause = col
            if col in unambiguous_cols:
                ambiguous = False
            orderby_arg.append(order_clause)

        if ambiguous:
            if in_unique_context:
                orderby_arg.append(BugTask.bugID)
            else:
                orderby_arg.append(BugTask.id)

        return tuple(orderby_arg)

    def dangerousGetAllTasks(self):
        """DO NOT USE THIS METHOD. For details, see `IBugTaskSet`"""
        return BugTask.select(orderBy='id')

    def getBugCountsForPackages(self, user, packages):
        """See `IBugTaskSet`."""
        distributions = sorted(
            set(package.distribution for package in packages),
            key=attrgetter('name'))
        counts = []
        for distribution in distributions:
            counts.extend(self._getBugCountsForDistribution(
                user, distribution, packages))
        return counts

    def _getBugCountsForDistribution(self, user, distribution, packages):
        """Get bug counts by package, belonging to the given distribution.

        See `IBugTask.getBugCountsForPackages` for more information.
        """
        packages = [
            package for package in packages
            if package.distribution == distribution]
        package_name_ids = [
            package.sourcepackagename.id for package in packages]

        open_bugs_cond = (
            'BugTask.status %s' % search_value_to_where_condition(
                any(*UNRESOLVED_BUGTASK_STATUSES)))

        sum_template = "SUM(CASE WHEN %s THEN 1 ELSE 0 END) AS %s"
        sums = [
            sum_template % (open_bugs_cond, 'open_bugs'),
            sum_template % (
                'BugTask.importance %s' % search_value_to_where_condition(
                    BugTaskImportance.CRITICAL), 'open_critical_bugs'),
            sum_template % (
                'BugTask.assignee IS NULL', 'open_unassigned_bugs'),
            sum_template % (
                'BugTask.status %s' % search_value_to_where_condition(
                    BugTaskStatus.INPROGRESS), 'open_inprogress_bugs'),
            sum_template % (
                'BugTask.importance %s' % search_value_to_where_condition(
                    BugTaskImportance.HIGH), 'open_high_bugs'),
            ]

        conditions = [
            'Bug.id = BugTask.bug',
            open_bugs_cond,
            'BugTask.sourcepackagename IN %s' % sqlvalues(package_name_ids),
            'BugTask.distribution = %s' % sqlvalues(distribution),
            'Bug.duplicateof is NULL',
            ]
        privacy_filter = get_bug_privacy_filter(user)
        if privacy_filter:
            conditions.append(privacy_filter)

        query = """SELECT BugTask.distribution,
                          BugTask.sourcepackagename,
                          %(sums)s
                   FROM BugTask, Bug
                   WHERE %(conditions)s
                   GROUP BY BugTask.distribution, BugTask.sourcepackagename"""
        cur = cursor()
        cur.execute(query % dict(
            sums=', '.join(sums), conditions=' AND '.join(conditions)))
        distribution_set = getUtility(IDistributionSet)
        sourcepackagename_set = getUtility(ISourcePackageNameSet)
        packages_with_bugs = set()
        counts = []
        for (distro_id, spn_id, open_bugs,
             open_critical_bugs, open_unassigned_bugs,
             open_inprogress_bugs,
             open_high_bugs) in shortlist(cur.fetchall()):
            distribution = distribution_set.get(distro_id)
            sourcepackagename = sourcepackagename_set.get(spn_id)
            source_package = distribution.getSourcePackage(sourcepackagename)
            # XXX: Bjorn Tillenius 2006-12-15:
            # Add a tuple instead of the distribution package
            # directly, since DistributionSourcePackage doesn't define a
            # __hash__ method.
            packages_with_bugs.add((distribution, sourcepackagename))
            package_counts = dict(
                package=source_package,
                open=open_bugs,
                open_critical=open_critical_bugs,
                open_unassigned=open_unassigned_bugs,
                open_inprogress=open_inprogress_bugs,
                open_high=open_high_bugs,
                )
            counts.append(package_counts)

        # Only packages with open bugs were included in the query. Let's
        # add the rest of the packages as well.
        all_packages = set(
            (distro_package.distribution, distro_package.sourcepackagename)
            for distro_package in packages)
        for distribution, sourcepackagename in all_packages.difference(
                packages_with_bugs):
            package_counts = dict(
                package=distribution.getSourcePackage(sourcepackagename),
                open=0, open_critical=0, open_unassigned=0,
                open_inprogress=0, open_high=0)
            counts.append(package_counts)

        return counts

    def getStructuralSubscribers(self, bugtasks, recipients=None, level=None):
        """See `IBugTaskSet`."""
        query_arguments = []
        for bugtask in bugtasks:
            if IStructuralSubscriptionTarget.providedBy(bugtask.target):
                query_arguments.append((bugtask.target, bugtask))
                if bugtask.target.parent_subscription_target is not None:
                    query_arguments.append(
                        (bugtask.target.parent_subscription_target, bugtask))
            if ISourcePackage.providedBy(bugtask.target):
                # Distribution series bug tasks with a package have the source
                # package set as their target, so we add the distroseries
                # explicitly to the set of subscription targets.
                query_arguments.append((bugtask.distroseries, bugtask))
            if bugtask.milestone is not None:
                query_arguments.append((bugtask.milestone, bugtask))

        if len(query_arguments) == 0:
            return EmptyResultSet()

        if level is None:
            # If level is not specified, default to NOTHING so that all
            # subscriptions are found.
            level = BugNotificationLevel.NOTHING

        # Build the query.
        union = lambda left, right: (
            removeSecurityProxy(left).union(
                removeSecurityProxy(right)))
        queries = (
            target.getSubscriptionsForBugTask(bugtask, level)
            for target, bugtask in query_arguments)
        subscriptions = reduce(union, queries)

        # Pull all the subscriptions in.
        subscriptions = list(subscriptions)

        # Prepare a query for the subscribers.
        from lp.registry.model.person import Person
        subscribers = IStore(Person).find(
            Person, Person.id.is_in(
                removeSecurityProxy(subscription).subscriberID
                for subscription in subscriptions))

        if recipients is not None:
            # We need to process subscriptions, so pull all the subscribes into
            # the cache, then update recipients with the subscriptions.
            subscribers = list(subscribers)
            for subscription in subscriptions:
                recipients.addStructuralSubscriber(
                    subscription.subscriber, subscription.target)

        return subscribers
