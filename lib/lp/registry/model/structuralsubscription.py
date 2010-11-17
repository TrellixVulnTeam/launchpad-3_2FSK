# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = ['StructuralSubscription',
           'StructuralSubscriptionTargetMixin']

from sqlobject import ForeignKey
from storm.expr import (
    And,
    CompoundOper,
    Except,
    In,
    Intersect,
    LeftJoin,
    NamedFunc,
    Not,
    Or,
    Select,
    SQL,
    Union,
    )
from storm.store import Store
from zope.component import (
    adapts,
    getUtility,
    )
from zope.interface import implements

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import (
    quote,
    SQLBase,
    )
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.interfaces.lpstorm import IStore
from lp.bugs.model.bugsubscriptionfilter import BugSubscriptionFilter
from lp.bugs.model.bugsubscriptionfilterimportance import (
    BugSubscriptionFilterImportance,
    )
from lp.bugs.model.bugsubscriptionfilterstatus import (
    BugSubscriptionFilterStatus,
    )
from lp.bugs.model.bugsubscriptionfiltertag import BugSubscriptionFilterTag
from lp.registry.enum import BugNotificationLevel
from lp.registry.errors import (
    DeleteSubscriptionError,
    UserCannotSubscribePerson,
    )
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distributionsourcepackage import (
    IDistributionSourcePackage,
    )
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.milestone import IMilestone
from lp.registry.interfaces.person import (
    validate_person,
    validate_public_person,
    )
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.projectgroup import IProjectGroup
from lp.registry.interfaces.structuralsubscription import (
    BlueprintNotificationLevel,
    IStructuralSubscription,
    IStructuralSubscriptionTarget,
    IStructuralSubscriptionTargetHelper,
    )
from lp.services.propertycache import cachedproperty


class StructuralSubscription(SQLBase):
    """A subscription to a Launchpad structure."""

    implements(IStructuralSubscription)

    _table = 'StructuralSubscription'

    product = ForeignKey(
        dbName='product', foreignKey='Product', notNull=False, default=None)
    productseries = ForeignKey(
        dbName='productseries', foreignKey='ProductSeries', notNull=False,
        default=None)
    project = ForeignKey(
        dbName='project', foreignKey='ProjectGroup', notNull=False,
        default=None)
    milestone = ForeignKey(
        dbName='milestone', foreignKey='Milestone', notNull=False,
        default=None)
    distribution = ForeignKey(
        dbName='distribution', foreignKey='Distribution', notNull=False,
        default=None)
    distroseries = ForeignKey(
        dbName='distroseries', foreignKey='DistroSeries', notNull=False,
        default=None)
    sourcepackagename = ForeignKey(
        dbName='sourcepackagename', foreignKey='SourcePackageName',
        notNull=False, default=None)
    subscriber = ForeignKey(
        dbName='subscriber', foreignKey='Person',
        storm_validator=validate_person, notNull=True)
    subscribed_by = ForeignKey(
        dbName='subscribed_by', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    bug_notification_level = EnumCol(
        enum=BugNotificationLevel,
        default=BugNotificationLevel.NOTHING,
        notNull=True)
    blueprint_notification_level = EnumCol(
        enum=BlueprintNotificationLevel,
        default=BlueprintNotificationLevel.NOTHING,
        notNull=True)
    date_created = UtcDateTimeCol(
        dbName='date_created', notNull=True, default=UTC_NOW)
    date_last_updated = UtcDateTimeCol(
        dbName='date_last_updated', notNull=True, default=UTC_NOW)

    @property
    def target(self):
        """See `IStructuralSubscription`."""
        if self.product is not None:
            return self.product
        elif self.productseries is not None:
            return self.productseries
        elif self.project is not None:
            return self.project
        elif self.milestone is not None:
            return self.milestone
        elif self.distribution is not None:
            if self.sourcepackagename is not None:
                # XXX intellectronica 2008-01-15:
                #   We're importing this pseudo db object
                #   here because importing it from the top
                #   doesn't play well with the loading
                #   sequence.
                from lp.registry.model.distributionsourcepackage import (
                    DistributionSourcePackage)
                return DistributionSourcePackage(
                    self.distribution, self.sourcepackagename)
            else:
                return self.distribution
        elif self.distroseries is not None:
            return self.distroseries
        else:
            raise AssertionError('StructuralSubscription has no target.')

    @property
    def bug_filters(self):
        """See `IStructuralSubscription`."""
        return IStore(BugSubscriptionFilter).find(
            BugSubscriptionFilter,
            BugSubscriptionFilter.structural_subscription == self)

    def newBugFilter(self):
        """See `IStructuralSubscription`."""
        bug_filter = BugSubscriptionFilter()
        bug_filter.structural_subscription = self
        return bug_filter


class DistroSeriesTargetHelper:
    """A helper for `IDistroSeries`s."""

    implements(IStructuralSubscriptionTargetHelper)
    adapts(IDistroSeries)

    target_type_display = 'distribution series'

    def __init__(self, target):
        self.target = target
        self.target_parent = target.distribution
        self.target_arguments = {"distroseries": target}
        self.pillar = target.distribution
        self.join = (StructuralSubscription.distroseries == target)


class ProjectGroupTargetHelper:
    """A helper for `IProjectGroup`s."""

    implements(IStructuralSubscriptionTargetHelper)
    adapts(IProjectGroup)

    target_type_display = 'project group'

    def __init__(self, target):
        self.target = target
        self.target_parent = None
        self.target_arguments = {"project": target}
        self.pillar = target
        self.join = (StructuralSubscription.project == target)


class DistributionSourcePackageTargetHelper:
    """A helper for `IDistributionSourcePackage`s."""

    implements(IStructuralSubscriptionTargetHelper)
    adapts(IDistributionSourcePackage)

    target_type_display = 'package'

    def __init__(self, target):
        self.target = target
        self.target_parent = target.distribution
        self.target_arguments = {
            "distribution": target.distribution,
            "sourcepackagename": target.sourcepackagename,
            }
        self.pillar = target.distribution
        self.join = And(
            StructuralSubscription.distributionID == (
                target.distribution.id),
            StructuralSubscription.sourcepackagenameID == (
                target.sourcepackagename.id))


class MilestoneTargetHelper:
    """A helper for `IMilestone`s."""

    implements(IStructuralSubscriptionTargetHelper)
    adapts(IMilestone)

    target_type_display = 'milestone'

    def __init__(self, target):
        self.target = target
        self.target_parent = target.target
        self.target_arguments = {"milestone": target}
        self.pillar = target.target
        self.join = (StructuralSubscription.milestone == target)


class ProductTargetHelper:
    """A helper for `IProduct`s."""

    implements(IStructuralSubscriptionTargetHelper)
    adapts(IProduct)

    target_type_display = 'project'

    def __init__(self, target):
        self.target = target
        self.target_parent = target.project
        self.target_arguments = {"product": target}
        self.pillar = target
        self.join = (StructuralSubscription.product == target)


class ProductSeriesTargetHelper:
    """A helper for `IProductSeries`s."""

    implements(IStructuralSubscriptionTargetHelper)
    adapts(IProductSeries)

    target_type_display = 'project series'

    def __init__(self, target):
        self.target = target
        self.target_parent = target.product
        self.target_arguments = {"productseries": target}
        self.pillar = target.product
        self.join = (StructuralSubscription.productseries == target)


class DistributionTargetHelper:
    """A helper for `IDistribution`s."""

    implements(IStructuralSubscriptionTargetHelper)
    adapts(IDistribution)

    target_type_display = 'distribution'

    def __init__(self, target):
        self.target = target
        self.target_parent = None
        self.target_arguments = {
            "distribution": target,
            "sourcepackagename": None,
            }
        self.pillar = target
        self.join = And(
            StructuralSubscription.distributionID == target.id,
            StructuralSubscription.sourcepackagenameID == None)


class StructuralSubscriptionTargetMixin:
    """Mixin class for implementing `IStructuralSubscriptionTarget`."""

    @cachedproperty
    def __helper(self):
        """A `IStructuralSubscriptionTargetHelper` for this object.

        Eventually this helper object could become *the* way to work with
        structural subscriptions. For now it just provides a few bits that
        vary with the context.

        It is cached in a pseudo-private variable because this is a mixin
        class.
        """
        return IStructuralSubscriptionTargetHelper(self)

    @property
    def _target_args(self):
        """Target Arguments.

        Return a dictionary with the arguments representing this
        target in a call to the structural subscription constructor.
        """
        return self.__helper.target_arguments

    @property
    def parent_subscription_target(self):
        """See `IStructuralSubscriptionTarget`."""
        parent = self.__helper.target_parent
        assert (parent is None or
                IStructuralSubscriptionTarget.providedBy(parent))
        return parent

    @property
    def target_type_display(self):
        """See `IStructuralSubscriptionTarget`."""
        return self.__helper.target_type_display

    def userCanAlterSubscription(self, subscriber, subscribed_by):
        """See `IStructuralSubscriptionTarget`."""
        # A Launchpad administrator or the user can subscribe a user.
        # A Launchpad or team admin can subscribe a team.

        # Nobody else can, unless the context is a IDistributionSourcePackage,
        # in which case the drivers or owner can.
        if IDistributionSourcePackage.providedBy(self):
            for driver in self.distribution.drivers:
                if subscribed_by.inTeam(driver):
                    return True
            if subscribed_by.inTeam(self.distribution.owner):
                return True

        admins = getUtility(ILaunchpadCelebrities).admin
        return (subscriber == subscribed_by or
                subscriber in subscribed_by.getAdministratedTeams() or
                subscribed_by.inTeam(admins))

    def addSubscription(self, subscriber, subscribed_by):
        """See `IStructuralSubscriptionTarget`."""
        if subscriber is None:
            subscriber = subscribed_by

        if not self.userCanAlterSubscription(subscriber, subscribed_by):
            raise UserCannotSubscribePerson(
                '%s does not have permission to subscribe %s.' % (
                    subscribed_by.name, subscriber.name))

        existing_subscription = self.getSubscription(subscriber)

        if existing_subscription is not None:
            return existing_subscription
        else:
            return StructuralSubscription(
                subscriber=subscriber,
                subscribed_by=subscribed_by,
                **self._target_args)

    def userCanAlterBugSubscription(self, subscriber, subscribed_by):
        """See `IStructuralSubscriptionTarget`."""

        admins = getUtility(ILaunchpadCelebrities).admin
        # If the object to be structurally subscribed to for bug
        # notifications is a distribution and that distribution has a
        # bug supervisor then only the bug supervisor or a member of
        # that team or, of course, admins, can subscribe someone to it.
        if IDistribution.providedBy(self) and self.bug_supervisor is not None:
            if subscriber is None or subscribed_by is None:
                return False
            elif (subscriber != self.bug_supervisor
                and not subscriber.inTeam(self.bug_supervisor)
                and not subscribed_by.inTeam(admins)):
                return False
        return True

    def addBugSubscription(self, subscriber, subscribed_by,
                           bug_notification_level=None):
        """See `IStructuralSubscriptionTarget`."""
        # This is a helper method for creating a structural
        # subscription and immediately giving it a full
        # bug notification level. It is useful so long as
        # subscriptions are mainly used to implement bug contacts.

        if not self.userCanAlterBugSubscription(subscriber, subscribed_by):
            raise UserCannotSubscribePerson(
                '%s does not have permission to subscribe %s' % (
                    subscribed_by.name, subscriber.name))

        sub = self.addSubscription(subscriber, subscribed_by)
        if bug_notification_level is None:
            bug_notification_level = BugNotificationLevel.COMMENTS
        sub.bug_notification_level = bug_notification_level
        return sub

    def removeBugSubscription(self, subscriber, unsubscribed_by):
        """See `IStructuralSubscriptionTarget`."""
        if subscriber is None:
            subscriber = unsubscribed_by

        if not self.userCanAlterSubscription(subscriber, unsubscribed_by):
            raise UserCannotSubscribePerson(
                '%s does not have permission to unsubscribe %s.' % (
                    unsubscribed_by.name, subscriber.name))

        subscription_to_remove = None
        for subscription in self.getSubscriptions(
            min_bug_notification_level=BugNotificationLevel.METADATA):
            # Only search for bug subscriptions
            if subscription.subscriber == subscriber:
                subscription_to_remove = subscription
                break

        if subscription_to_remove is None:
            raise DeleteSubscriptionError(
                "%s is not subscribed to %s." % (
                subscriber.name, self.displayname))
        else:
            if (subscription_to_remove.blueprint_notification_level >
                BlueprintNotificationLevel.NOTHING):
                # This is a subscription to other application too
                # so only set the bug notification level
                subscription_to_remove.bug_notification_level = (
                    BugNotificationLevel.NOTHING)
            else:
                subscription_to_remove.destroySelf()

    def getSubscription(self, person):
        """See `IStructuralSubscriptionTarget`."""
        all_subscriptions = self.getSubscriptions()
        for subscription in all_subscriptions:
            if subscription.subscriber == person:
                return subscription
        return None

    def getSubscriptions(self,
                         min_bug_notification_level=
                         BugNotificationLevel.NOTHING,
                         min_blueprint_notification_level=
                         BlueprintNotificationLevel.NOTHING):
        """See `IStructuralSubscriptionTarget`."""
        clauses = [
            "StructuralSubscription.subscriber = Person.id",
            "StructuralSubscription.bug_notification_level "
            ">= %s" % quote(min_bug_notification_level),
            "StructuralSubscription.blueprint_notification_level "
            ">= %s" % quote(min_blueprint_notification_level),
            ]
        for key, value in self._target_args.iteritems():
            if value is None:
                clauses.append(
                    "StructuralSubscription.%s IS NULL" % (key,))
            else:
                clauses.append(
                    "StructuralSubscription.%s = %s" % (key, quote(value)))
        query = " AND ".join(clauses)
        return StructuralSubscription.select(
            query, orderBy='Person.displayname', clauseTables=['Person'])

    @property
    def bug_subscriptions(self):
        """See `IStructuralSubscriptionTarget`."""
        return self.getSubscriptions(
            min_bug_notification_level=BugNotificationLevel.METADATA)

    def userHasBugSubscriptions(self, user):
        """See `IStructuralSubscriptionTarget`."""
        bug_subscriptions = self.getSubscriptions(
            min_bug_notification_level=BugNotificationLevel.METADATA)
        if user is not None:
            for subscription in bug_subscriptions:
                if (subscription.subscriber == user or
                    user.inTeam(subscription.subscriber)):
                    # The user has a bug subscription
                    return True
        return False

    def getSubscriptionsForBugTask(self, bugtask, level):
        """See `IStructuralSubscriptionTarget`."""
        set_builder = FilterSetBuilder(
            bugtask, And(
                StructuralSubscription.bug_notification_level >= level,
                self.__helper.join))
        return Store.of(self.__helper.pillar).find(
            StructuralSubscription, In(
                StructuralSubscription.id,
                set_builder.subscriptions_matching))


class ArrayAgg(NamedFunc):
    __slots__ = ()
    name = "ARRAY_AGG"


class Contains(CompoundOper):
    __slots__ = ()
    oper = "@>"


class FilterSetBuilder:
    """A convenience class to build queries for getSubscriptionsForBugTask."""

    def __init__(self, bugtask, base_conditions):
        self.bugtask = bugtask
        self.base_conditions = base_conditions
        # Set up common filter conditions.
        if len(bugtask.bug.tags) == 0:
            self.filter_conditions = And(
                self.base_conditions,
                BugSubscriptionFilter.include_any_tags == False)
        else:
            self.filter_conditions = And(
                self.base_conditions,
                BugSubscriptionFilter.exclude_any_tags == False)
        # This gets around some weirdness with security proxies.
        self.tags = list(self.bugtask.bug.tags)

    @property
    def subscriptions_without_filters(self):
        """Subscriptions without filters."""
        return Select(
            StructuralSubscription.id,
            tables=(
                StructuralSubscription,
                LeftJoin(
                    BugSubscriptionFilter,
                    BugSubscriptionFilter.structural_subscription_id == (
                        StructuralSubscription.id))),
            where=And(
                BugSubscriptionFilter.id == None,
                self.base_conditions))

    def _subscriptions_matching_x(self, join, extra_condition, **extra):
        return Select(
            StructuralSubscription.id,
            tables=(StructuralSubscription, BugSubscriptionFilter, join),
            where=And(
                BugSubscriptionFilter.structural_subscription_id == (
                    StructuralSubscription.id),
                self.filter_conditions,
                extra_condition),
            **extra)

    @property
    def subscriptions_matching_status(self):
        """Subscriptions with the given bugtask's status."""
        join = LeftJoin(
            BugSubscriptionFilterStatus,
            BugSubscriptionFilterStatus.filter_id == (
                BugSubscriptionFilter.id))
        condition = Or(
            BugSubscriptionFilterStatus.id == None,
            BugSubscriptionFilterStatus.status == self.bugtask.status)
        return self._subscriptions_matching_x(join, condition)

    @property
    def subscriptions_matching_importance(self):
        """Subscriptions with the given bugtask's importance."""
        join = LeftJoin(
            BugSubscriptionFilterImportance,
            BugSubscriptionFilterImportance.filter_id == (
                BugSubscriptionFilter.id))
        condition = Or(
            BugSubscriptionFilterImportance.id == None,
            BugSubscriptionFilterImportance.importance == (
                self.bugtask.importance))
        return self._subscriptions_matching_x(join, condition)

    @property
    def subscriptions_tags_include_empty(self):
        """Subscriptions with no tags required."""
        join = LeftJoin(
            BugSubscriptionFilterTag,
            And(BugSubscriptionFilterTag.filter_id == (
                    BugSubscriptionFilter.id),
                BugSubscriptionFilterTag.include))
        return self._subscriptions_matching_x(
            join, BugSubscriptionFilterTag.id == None)

    @property
    def subscriptions_tags_include_match_any(self):
        """Subscriptions including any of the bug's tags."""
        condition = And(
            BugSubscriptionFilterTag.filter_id == (
                BugSubscriptionFilter.id),
            BugSubscriptionFilterTag.include,
            Not(BugSubscriptionFilter.find_all_tags),
            In(BugSubscriptionFilterTag.tag, self.tags))
        return self._subscriptions_matching_x(
            BugSubscriptionFilterTag, condition)

    @property
    def subscriptions_tags_exclude_match_any(self):
        """Subscriptions excluding any of the bug's tags."""
        condition = And(
            BugSubscriptionFilterTag.filter_id == (
                BugSubscriptionFilter.id),
            Not(BugSubscriptionFilterTag.include),
            Not(BugSubscriptionFilter.find_all_tags),
            In(BugSubscriptionFilterTag.tag, self.tags))
        return self._subscriptions_matching_x(
            BugSubscriptionFilterTag, condition)

    def _subscriptions_tags_match_all(self, extra_condition):
        tags_array = "ARRAY[%s]::TEXT[]" % ",".join(
            quote(tag) for tag in self.tags)
        return self._subscriptions_matching_x(
            BugSubscriptionFilterTag,
            And(
                BugSubscriptionFilterTag.filter_id == (
                    BugSubscriptionFilter.id),
                BugSubscriptionFilter.find_all_tags,
                self.filter_conditions,
                extra_condition),
            group_by=(
                StructuralSubscription.id,
                BugSubscriptionFilter.id),
            having=Contains(
                SQL(tags_array),
                ArrayAgg(BugSubscriptionFilterTag.tag)))

    @property
    def subscriptions_tags_include_match_all(self):
        """Subscriptions including the bug's tags."""
        return self._subscriptions_tags_match_all(
            BugSubscriptionFilterTag.include)

    @property
    def subscriptions_tags_exclude_match_all(self):
        """Subscriptions excluding the bug's tags."""
        return self._subscriptions_tags_match_all(
            Not(BugSubscriptionFilterTag.include))

    @property
    def subscriptions_tags_include(self):
        """Subscriptions with tag filters including the bug."""
        return Union(
            self.subscriptions_tags_include_empty,
            self.subscriptions_tags_include_match_any,
            self.subscriptions_tags_include_match_all)

    @property
    def subscriptions_tags_exclude(self):
        """Subscriptions with tag filters excluding the bug."""
        return Union(
            self.subscriptions_tags_exclude_match_any,
            self.subscriptions_tags_exclude_match_all)

    @property
    def subscriptions_tags_match(self):
        """Subscriptions with tag filters matching the bug."""
        if len(self.tags) == 0:
            # The subscription's required tags must be an empty set. The
            # subscription's excluded tags can be anything so no condition is
            # needed.
            return self.subscriptions_tags_include_empty
        else:
            return Except(
                self.subscriptions_tags_include,
                self.subscriptions_tags_exclude)

    @property
    def subscriptions_matching(self):
        """Subscriptions matching the bug."""
        return Union(
            self.subscriptions_without_filters,
            Intersect(
                self.subscriptions_matching_status,
                self.subscriptions_matching_importance,
                self.subscriptions_tags_match))
