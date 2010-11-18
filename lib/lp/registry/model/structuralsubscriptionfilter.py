# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type
__all__ = [
    'BugFilterSetBuilder',
    ]

from storm.expr import (
    Alias,
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

from canonical.database.sqlbase import quote
from lp.bugs.model.bugsubscriptionfilter import BugSubscriptionFilter
from lp.bugs.model.bugsubscriptionfilterimportance import (
    BugSubscriptionFilterImportance,
    )
from lp.bugs.model.bugsubscriptionfilterstatus import (
    BugSubscriptionFilterStatus,
    )
from lp.bugs.model.bugsubscriptionfiltertag import BugSubscriptionFilterTag
from lp.registry.model.structuralsubscription import StructuralSubscription


class ArrayAgg(NamedFunc):
    __slots__ = ()
    name = "ARRAY_AGG"


class ArrayContains(CompoundOper):
    __slots__ = ()
    oper = "@>"


class BugFilterSetBuilder:
    """A convenience class to build queries for getSubscriptionsForBugTask."""

    def __init__(self, bugtask, level, join_condition):
        self.status = bugtask.status
        self.importance = bugtask.importance
        # The list() gets around some weirdness with security proxies; Storm
        # does not know how to compile an expression with a proxied list.
        self.tags = list(bugtask.bug.tags)
        # Set up common conditions.
        self.base_conditions = And(
            StructuralSubscription.bug_notification_level >= level,
            join_condition)
        # Set up common filter conditions.
        if len(self.tags) == 0:
            self.filter_conditions = And(
                BugSubscriptionFilter.include_any_tags == False,
                self.base_conditions)
        else:
            self.filter_conditions = And(
                BugSubscriptionFilter.exclude_any_tags == False,
                self.base_conditions)

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

    def _filters_matching_x(self, join, where_condition, **extra):
        # The expressions returned by this function are used in set (union,
        # intersect, except) operations at the *filter* level. However, the
        # interesting result of these set operations is the structural
        # subscription, hence both columns are included in the expressions
        # generated. Since a structural subscription can have zero or more
        # filters, and a filter can never be associated with more than one
        # subscription, the set operations are unaffected.
        return Select(
            columns=(
                # Alias this column so it can be selected in
                # subscriptions_matching.
                Alias(
                    BugSubscriptionFilter.structural_subscription_id,
                    "structural_subscription_id"),
                BugSubscriptionFilter.id),
            tables=(
                StructuralSubscription, BugSubscriptionFilter, join),
            where=And(
                BugSubscriptionFilter.structural_subscription_id == (
                    StructuralSubscription.id),
                self.filter_conditions,
                where_condition),
            **extra)

    @property
    def filters_matching_status(self):
        """Filters with the given bugtask's status."""
        join = LeftJoin(
            BugSubscriptionFilterStatus,
            BugSubscriptionFilterStatus.filter_id == (
                BugSubscriptionFilter.id))
        condition = Or(
            BugSubscriptionFilterStatus.id == None,
            BugSubscriptionFilterStatus.status == self.status)
        return self._filters_matching_x(join, condition)

    @property
    def filters_matching_importance(self):
        """Filters with the given bugtask's importance."""
        join = LeftJoin(
            BugSubscriptionFilterImportance,
            BugSubscriptionFilterImportance.filter_id == (
                BugSubscriptionFilter.id))
        condition = Or(
            BugSubscriptionFilterImportance.id == None,
            BugSubscriptionFilterImportance.importance == self.importance)
        return self._filters_matching_x(join, condition)

    @property
    def filters_without_include_tags(self):
        """Filters with no tags required."""
        join = LeftJoin(
            BugSubscriptionFilterTag,
            And(BugSubscriptionFilterTag.filter_id == (
                    BugSubscriptionFilter.id),
                BugSubscriptionFilterTag.include))
        return self._filters_matching_x(
            join, BugSubscriptionFilterTag.id == None)

    @property
    def filters_matching_any_include_tags(self):
        """Filters including any of the bug's tags."""
        condition = And(
            BugSubscriptionFilterTag.filter_id == (
                BugSubscriptionFilter.id),
            BugSubscriptionFilterTag.include,
            Not(BugSubscriptionFilter.find_all_tags),
            In(BugSubscriptionFilterTag.tag, self.tags))
        return self._filters_matching_x(
            BugSubscriptionFilterTag, condition)

    @property
    def filters_matching_any_exclude_tags(self):
        """Filters excluding any of the bug's tags."""
        condition = And(
            BugSubscriptionFilterTag.filter_id == (
                BugSubscriptionFilter.id),
            Not(BugSubscriptionFilterTag.include),
            Not(BugSubscriptionFilter.find_all_tags),
            In(BugSubscriptionFilterTag.tag, self.tags))
        return self._filters_matching_x(
            BugSubscriptionFilterTag, condition)

    def _filters_matching_all_x_tags(self, where_condition):
        tags_array = "ARRAY[%s]::TEXT[]" % ",".join(
            quote(tag) for tag in self.tags)
        return self._filters_matching_x(
            BugSubscriptionFilterTag,
            And(
                BugSubscriptionFilterTag.filter_id == (
                    BugSubscriptionFilter.id),
                BugSubscriptionFilter.find_all_tags,
                self.filter_conditions,
                where_condition),
            group_by=(
                BugSubscriptionFilter.structural_subscription_id,
                BugSubscriptionFilter.id),
            having=ArrayContains(
                SQL(tags_array), ArrayAgg(
                    BugSubscriptionFilterTag.tag)))

    @property
    def filters_matching_all_include_tags(self):
        """Filters including the bug's tags."""
        return self._filters_matching_all_x_tags(
            BugSubscriptionFilterTag.include)

    @property
    def filters_matching_all_exclude_tags(self):
        """Filters excluding the bug's tags."""
        return self._filters_matching_all_x_tags(
            Not(BugSubscriptionFilterTag.include))

    @property
    def filters_matching_include_tags(self):
        """Filters with tag filters including the bug."""
        return Union(
            self.filters_matching_any_include_tags,
            self.filters_matching_all_include_tags)

    @property
    def filters_matching_exclude_tags(self):
        """Filters with tag filters excluding the bug."""
        return Union(
            self.filters_matching_any_exclude_tags,
            self.filters_matching_all_exclude_tags)

    @property
    def filters_matching_tags(self):
        """Filters with tag filters matching the bug."""
        if len(self.tags) == 0:
            # The filter's required tags must be an empty set. The filter's
            # excluded tags can be anything so no condition is needed.
            return self.filters_without_include_tags
        else:
            return Except(
                Union(self.filters_without_include_tags,
                      self.filters_matching_include_tags),
                self.filters_matching_exclude_tags)

    @property
    def filters_matching(self):
        """Filters matching the bug."""
        return Intersect(
            self.filters_matching_status,
            self.filters_matching_importance,
            self.filters_matching_tags)

    @property
    def subscriptions_matching(self):
        """Subscriptions with one or more filters matching the bug."""
        return Select(
            # I don't know of a more Storm-like way of doing this.
            SQL("filters_matching.structural_subscription_id"),
            tables=Alias(self.filters_matching, "filters_matching"))

    @property
    def subscriptions(self):
        return Union(
            self.subscriptions_without_filters,
            self.subscriptions_matching)
