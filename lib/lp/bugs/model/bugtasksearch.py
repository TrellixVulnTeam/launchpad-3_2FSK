# Copyright 2009-2012 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'get_bug_privacy_filter',
    'orderby_expression',
    'search_bugs',
    'search_value_to_where_condition',
    ]

from lazr.enum import BaseItem
from sqlobject.sqlbuilder import SQLConstant
from storm.expr import (
    Alias,
    And,
    Desc,
    In,
    Join,
    LeftJoin,
    Not,
    Or,
    Select,
    SQL,
    )
from storm.info import ClassAlias
from zope.component import getUtility
from zope.security.proxy import (
    isinstance as zope_isinstance,
    removeSecurityProxy,
    )

from lp.app.interfaces.launchpad import ILaunchpadCelebrities
from lp.blueprints.model.specification import Specification
from lp.bugs.interfaces.bugattachment import BugAttachmentType
from lp.bugs.interfaces.bugnomination import BugNominationStatus
from lp.bugs.interfaces.bugtask import (
    BugBlueprintSearch,
    BugBranchSearch,
    BugTaskSearchParams,
    BugTaskStatus,
    BugTaskStatusSearch,
    DB_INCOMPLETE_BUGTASK_STATUSES,
    )
from lp.bugs.model.bug import (
    Bug,
    BugTag,
    )
from lp.bugs.model.bugnomination import BugNomination
from lp.bugs.model.bugsubscription import BugSubscription
from lp.bugs.model.bugtask import BugTask
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.distroseries import IDistroSeries
from lp.registry.interfaces.milestone import IProjectGroupMilestone
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.model.milestone import Milestone
from lp.registry.model.person import Person
from lp.services import features
from lp.services.config import config
from lp.services.database.decoratedresultset import DecoratedResultSet
from lp.services.database.lpstorm import IStore
from lp.services.database.sqlbase import (
    convert_storm_clause_to_string,
    quote,
    quote_like,
    sqlvalues,
    )
from lp.services.propertycache import get_property_cache
from lp.services.searchbuilder import (
    all,
    any,
    greater_than,
    not_equals,
    NULL,
    )
from lp.soyuz.enums import PackagePublishingStatus


Assignee = ClassAlias(Person)
Reporter = ClassAlias(Person)
orderby_expression = {
    "task": (BugTask.id, []),
    "id": (BugTask.bugID, []),
    "importance": (BugTask.importance, []),
    # TODO: sort by their name?
    "assignee": (
        Assignee.name,
        [
            (Assignee,
                LeftJoin(Assignee, BugTask.assignee == Assignee.id))
            ]),
    "targetname": (BugTask.targetnamecache, []),
    "status": (BugTask._status, []),
    "title": (Bug.title, []),
    "milestone": (BugTask.milestoneID, []),
    "dateassigned": (BugTask.date_assigned, []),
    "datecreated": (BugTask.datecreated, []),
    "date_last_updated": (Bug.date_last_updated, []),
    "date_closed": (BugTask.date_closed, []),
    "number_of_duplicates": (Bug.number_of_duplicates, []),
    "message_count": (Bug.message_count, []),
    "users_affected_count": (Bug.users_affected_count, []),
    "heat": (BugTask.heat, []),
    "latest_patch_uploaded": (Bug.latest_patch_uploaded, []),
    "milestone_name": (
        Milestone.name,
        [
            (Milestone,
                LeftJoin(Milestone,
                        BugTask.milestone == Milestone.id))
            ]),
    "reporter": (
        Reporter.name,
        [
            (Bug, Join(Bug, BugTask.bug == Bug.id)),
            (Reporter, Join(Reporter, Bug.owner == Reporter.id))
            ]),
    "tag": (
        BugTag.tag,
        [
            (Bug, Join(Bug, BugTask.bug == Bug.id)),
            (BugTag,
                LeftJoin(
                    BugTag,
                    BugTag.bug == Bug.id and
                    # We want at most one tag per bug. Select the
                    # tag that comes first in alphabetic order.
                    BugTag.id == SQL("""
                        SELECT id FROM BugTag AS bt
                        WHERE bt.bug=bug.id ORDER BY bt.name LIMIT 1
                        """))),
            ]
        ),
    "specification": (
        Specification.name,
        [
            (Bug, Join(Bug, BugTask.bug == Bug.id)),
            (Specification,
                LeftJoin(
                    Specification,
                    # We want at most one specification per bug.
                    # Select the specification that comes first
                    # in alphabetic order.
                    Specification.id == SQL("""
                        SELECT Specification.id
                        FROM SpecificationBug
                        JOIN Specification
                            ON SpecificationBug.specification=
                                Specification.id
                        WHERE SpecificationBug.bug=Bug.id
                        ORDER BY Specification.name
                        LIMIT 1
                        """))),
            ]
        ),
    }


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


def search_bugs(resultrow, prejoins, pre_iter_hook, params, *args):
    """Return a Storm result set for the given search parameters.

    :param resultrow: The type of data returned by the query.
    :param prejoins: A sequence of Storm SQL row instances which are
        pre-joined.
    :param pre_iter_hook: An optional pre-iteration hook used for eager
        loading bug targets for list views.
    :param params: A BugTaskSearchParams instance.
    :param args: optional additional BugTaskSearchParams instances,
    """
    orig_store = store = IStore(BugTask)
    [query, clauseTables, bugtask_decorator, join_tables,
    has_duplicate_results, with_clause] = _build_query(params)
    if with_clause:
        store = store.with_(with_clause)
    orderby_expression, orderby_joins = _process_order_by(params)
    decorators = [bugtask_decorator]

    if len(args) == 0:
        if has_duplicate_results:
            origin = _build_origin(join_tables, [], clauseTables)
            outer_origin = _build_origin(
                    orderby_joins, prejoins, [])
            subquery = Select(BugTask.id, where=SQL(query), tables=origin)
            result = store.using(*outer_origin).find(
                resultrow, In(BugTask.id, subquery))
        else:
            origin = _build_origin(
                join_tables + orderby_joins, prejoins, clauseTables)
            result = store.using(*origin).find(resultrow, query)
    else:
        inner_resultrow = (BugTask,)
        origin = _build_origin(join_tables, [], clauseTables)
        resultset = store.using(*origin).find(inner_resultrow, query)

        for arg in args:
            [query, clauseTables, decorator, join_tables,
                has_duplicate_results, with_clause] = _build_query(arg)
            origin = _build_origin(join_tables, [], clauseTables)
            localstore = store
            if with_clause:
                localstore = orig_store.with_(with_clause)
            next_result = localstore.using(*origin).find(
                inner_resultrow, query)
            resultset = resultset.union(next_result)
            # NB: assumes the decorators are all compatible.
            # This may need revisiting if e.g. searches on behalf of different
            # users are combined.
            decorators.append(decorator)

        origin = _build_origin(
            orderby_joins, prejoins, [],
            start_with=Alias(resultset._get_select(), "BugTask"))
        result = store.using(*origin).find(resultrow)

    def prejoin_decorator(row):
        bugtask = row[0]
        for decorator in decorators:
            bugtask = decorator(bugtask)
        return bugtask

    def simple_decorator(bugtask):
        for decorator in decorators:
            bugtask = decorator(bugtask)
        return bugtask

    if prejoins:
        decorator = prejoin_decorator
    else:
        decorator = simple_decorator

    result.order_by(orderby_expression)
    return DecoratedResultSet(result, result_decorator=decorator,
        pre_iter_hook=pre_iter_hook)


def _build_origin(join_tables, prejoin_tables, clauseTables,
                start_with=BugTask):
    """Build the parameter list for Store.using().

    :param join_tables: A sequence of tables that should be joined
        as returned by _build_query(). Each element has the form
        (table, join), where table is the table to join and join
        is a Storm Join or LeftJoin instance.
    :param prejoin_tables: A sequence of tables that should additionally
        be joined. Each element has the form (table, join),
        where table is the table to join and join is a Storm Join
        or LeftJoin instance.
    :param clauseTables: A sequence of tables that should appear in
        the FROM clause of a query. The join condition is defined in
        the WHERE clause.

    Tables may appear simultaneously in join_tables, prejoin_tables
    and in clauseTables. This method ensures that each table
    appears exactly once in the returned sequence.
    """
    origin = [start_with]
    already_joined = set(origin)
    for table, join in join_tables:
        if table is None or table not in already_joined:
            origin.append(join)
            if table is not None:
                already_joined.add(table)
    for table, join in prejoin_tables:
        if table not in already_joined:
            origin.append(join)
            already_joined.add(table)
    for table in clauseTables:
        if table not in already_joined:
            origin.append(table)
    return origin


def _build_query(params):
    """Build and return an SQL query with the given parameters.

    Also return the clauseTables and orderBy for the generated query.

    :return: A query, the tables to query, ordering expression and a
        decorator to call on each returned row.
    """
    params = _require_params(params)
    from lp.bugs.model.bug import (
        Bug,
        BugAffectsPerson,
        )
    extra_clauses = ['Bug.id = BugTask.bug']
    clauseTables = [BugTask, Bug]
    join_tables = []
    decorators = []
    has_duplicate_results = False
    with_clauses = []

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
    # lp.services.database.sqlbase?
    for arg_name, arg_value in standard_args.items():
        if arg_value is None:
            continue
        where_cond = search_value_to_where_condition(arg_value)
        if where_cond is not None:
            extra_clauses.append("BugTask.%s %s" % (arg_name, where_cond))

    if params.status is not None:
        extra_clauses.append(_build_status_clause(params.status))

    if params.exclude_conjoined_tasks:
        # XXX: frankban 2012-01-05 bug=912370: excluding conjoined
        # bugtasks is not currently supported for milestone tags.
        if params.milestone_tag:
            raise NotImplementedError(
                'Excluding conjoined tasks is not currently supported '
                'for milestone tags')
        if not params.milestone:
            raise ValueError(
                "BugTaskSearchParam.exclude_conjoined cannot be True if "
                "BugTaskSearchParam.milestone is not set")

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

        if params.exclude_conjoined_tasks:
            tables, clauses = _build_exclude_conjoined_clause(
                params.milestone)
            join_tables += tables
            extra_clauses += clauses

    if params.milestone_tag:
        where_cond = """
            IN (SELECT Milestone.id
                FROM Milestone, Product, MilestoneTag
                WHERE Milestone.product = Product.id
                    AND Product.project = %s
                    AND MilestoneTag.milestone = Milestone.id
                    AND MilestoneTag.tag IN %s
                GROUP BY Milestone.id
                HAVING COUNT(Milestone.id) = %s)
        """ % sqlvalues(params.milestone_tag.target,
                        params.milestone_tag.tags,
                        len(params.milestone_tag.tags))
        extra_clauses.append("BugTask.milestone %s" % where_cond)

        # XXX: frankban 2012-01-05 bug=912370: excluding conjoined
        # bugtasks is not currently supported for milestone tags.
        # if params.exclude_conjoined_tasks:
        #     tables, clauses = _build_exclude_conjoined_clause(
        #         params.milestone_tag)
        #     join_tables += tables
        #     extra_clauses += clauses

    if params.project:
        # Prevent circular import problems.
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
        extra_clauses.append(_build_search_text_clause(params))

    if params.fast_searchtext:
        extra_clauses.append(_build_fast_search_text_clause(params))

    if params.subscriber is not None:
        clauseTables.append(BugSubscription)
        extra_clauses.append("""Bug.id = BugSubscription.bug AND
                BugSubscription.person = %(personid)s""" %
                sqlvalues(personid=params.subscriber.id))

    if params.structural_subscriber is not None:
        # See bug 787294 for the story that led to the query elements
        # below.  Please change with care.
        with_clauses.append(
            '''ss as (SELECT * from StructuralSubscription
            WHERE StructuralSubscription.subscriber = %s)'''
            % sqlvalues(params.structural_subscriber))
        # Prevent circular import problems.
        from lp.registry.model.product import Product
        join_tables.append(
            (Product, LeftJoin(Product, And(
                            BugTask.productID == Product.id,
                            Product.active))))
        join_tables.append(
            (None,
                LeftJoin(
                SQL('ss ss1'),
                BugTask.product == SQL('ss1.product'))))
        join_tables.append(
            (None,
                LeftJoin(
                SQL('ss ss2'),
                BugTask.productseries == SQL('ss2.productseries'))))
        join_tables.append(
            (None,
                LeftJoin(
                SQL('ss ss3'),
                Product.project == SQL('ss3.project'))))
        join_tables.append(
            (None,
                LeftJoin(
                SQL('ss ss4'),
                And(BugTask.distribution == SQL('ss4.distribution'),
                    Or(BugTask.sourcepackagename ==
                        SQL('ss4.sourcepackagename'),
                        SQL('ss4.sourcepackagename IS NULL'))))))
        if params.distroseries is not None:
            parent_distro_id = params.distroseries.distributionID
        else:
            parent_distro_id = 0
        join_tables.append(
            (None,
                LeftJoin(
                SQL('ss ss5'),
                Or(BugTask.distroseries == SQL('ss5.distroseries'),
                    # There is a mismatch between BugTask and
                    # StructuralSubscription. SS does not support
                    # distroseries. This clause works because other
                    # joins ensure the match bugtask is the right
                    # series.
                    And(parent_distro_id == SQL('ss5.distribution'),
                        BugTask.sourcepackagename == SQL(
                            'ss5.sourcepackagename'))))))
        join_tables.append(
            (None,
                LeftJoin(
                SQL('ss ss6'),
                BugTask.milestone == SQL('ss6.milestone'))))
        extra_clauses.append(
            "NULL_COUNT("
            "ARRAY[ss1.id, ss2.id, ss3.id, ss4.id, ss5.id, ss6.id]"
            ") < 6")
        has_duplicate_results = True

    # Remove bugtasks from deactivated products, if necessary.
    # We don't have to do this if
    # 1) We're searching on bugtasks for a specific product
    # 2) We're searching on bugtasks for a specific productseries
    # 3) We're searching on bugtasks for a distribution
    # 4) We're searching for bugtasks for a distroseries
    # because in those instances we don't have arbitrary products which
    # may be deactivated showing up in our search.
    if (params.product is None and
        params.distribution is None and
        params.productseries is None and
        params.distroseries is None):
        # Prevent circular import problems.
        from lp.registry.model.product import Product
        extra_clauses.append(
            "(Bugtask.product IS NULL OR Product.active = TRUE)")
        join_tables.append(
            (Product, LeftJoin(Product, And(
                            BugTask.productID == Product.id,
                            Product.active))))

    if params.component:
        distroseries = None
        if params.distribution:
            distroseries = params.distribution.currentseries
        elif params.distroseries:
            distroseries = params.distroseries
        if distroseries is None:
            raise ValueError(
                "Search by component requires a context with a "
                "distribution or distroseries.")

        if zope_isinstance(params.component, any):
            component_ids = sqlvalues(*params.component.query_values)
        else:
            component_ids = sqlvalues(params.component)

        distro_archive_ids = [
            archive.id
            for archive in distroseries.distribution.all_distro_archives]
        with_clauses.append("""spns as (
            SELECT spr.sourcepackagename
            FROM SourcePackagePublishingHistory
            JOIN SourcePackageRelease AS spr ON spr.id =
                SourcePackagePublishingHistory.sourcepackagerelease AND
            SourcePackagePublishingHistory.distroseries = %s AND
            SourcePackagePublishingHistory.archive IN %s AND
            SourcePackagePublishingHistory.component IN %s AND
            SourcePackagePublishingHistory.status = %s
            )""" % sqlvalues(distroseries,
                            distro_archive_ids,
                            component_ids,
                            PackagePublishingStatus.PUBLISHED))
        extra_clauses.append(
            """BugTask.sourcepackagename in (
                select sourcepackagename from spns)""")

    upstream_clause = _build_upstream_clause(params)
    if upstream_clause:
        extra_clauses.append(upstream_clause)

    if params.tag:
        tag_clause = _build_tag_search_clause(params.tag)
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
        bug_supervisor_clause = """(
            BugTask.product IN (
                SELECT id FROM Product
                WHERE Product.bug_supervisor = %(bug_supervisor)s)
            OR
            ((BugTask.distribution, Bugtask.sourcepackagename) IN
                (SELECT distribution,  sourcepackagename FROM
                    StructuralSubscription
                    WHERE subscriber = %(bug_supervisor)s))
            OR
            BugTask.distribution IN (
                SELECT id from Distribution WHERE
                Distribution.bug_supervisor = %(bug_supervisor)s)
            )""" % sqlvalues(bug_supervisor=params.bug_supervisor)
        extra_clauses.append(bug_supervisor_clause)

    if params.bug_reporter:
        bug_reporter_clause = (
            "BugTask.bug = Bug.id AND Bug.owner = %s" % sqlvalues(
                params.bug_reporter))
        extra_clauses.append(bug_reporter_clause)

    if params.bug_commenter:
        bug_commenter_clause = """
        Bug.id IN (SELECT DISTINCT bug FROM Bugmessage WHERE
        BugMessage.index > 0 AND BugMessage.owner = %(bug_commenter)s)
        """ % sqlvalues(bug_commenter=params.bug_commenter)
        extra_clauses.append(bug_commenter_clause)

    if params.affects_me:
        params.affected_user = params.user
    if params.affected_user:
        join_tables.append(
            (BugAffectsPerson, Join(
                BugAffectsPerson, And(
                    BugTask.bugID == BugAffectsPerson.bugID,
                    BugAffectsPerson.affected,
                    BugAffectsPerson.person == params.affected_user))))

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

    clause, decorator = _get_bug_privacy_filter_with_decorator(params.user)
    if clause:
        extra_clauses.append(clause)
        decorators.append(decorator)

    hw_clause = _build_hardware_related_clause(params)
    if hw_clause is not None:
        extra_clauses.append(hw_clause)

    if zope_isinstance(params.linked_branches, BaseItem):
        if params.linked_branches == BugBranchSearch.BUGS_WITH_BRANCHES:
            extra_clauses.append(
                """EXISTS (
                    SELECT id FROM BugBranch WHERE BugBranch.bug=Bug.id)
                """)
        elif (params.linked_branches ==
                BugBranchSearch.BUGS_WITHOUT_BRANCHES):
            extra_clauses.append(
                """NOT EXISTS (
                    SELECT id FROM BugBranch WHERE BugBranch.bug=Bug.id)
                """)
    elif zope_isinstance(params.linked_branches, (any, all, int)):
        # A specific search term has been supplied.
        extra_clauses.append(
            """EXISTS (
                SELECT TRUE FROM BugBranch WHERE BugBranch.bug=Bug.id AND
                BugBranch.branch %s)
            """ % search_value_to_where_condition(params.linked_branches))

    linked_blueprints_clause = _build_blueprint_related_clause(params)
    if linked_blueprints_clause is not None:
        extra_clauses.append(linked_blueprints_clause)

    if params.modified_since:
        extra_clauses.append(
            "Bug.date_last_updated > %s" % (
                sqlvalues(params.modified_since,)))

    if params.created_since:
        extra_clauses.append(
            "BugTask.datecreated > %s" % (
                sqlvalues(params.created_since,)))

    query = " AND ".join(extra_clauses)

    if not decorators:
        decorator = lambda x: x
    else:

        def decorator(obj):
            for decor in decorators:
                obj = decor(obj)
            return obj
    if with_clauses:
        with_clause = SQL(', '.join(with_clauses))
    else:
        with_clause = None
    return (
        query, clauseTables, decorator, join_tables,
        has_duplicate_results, with_clause)


def _process_order_by(params):
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
    # decide whether we need to add the BugTask.bug or BugTask.id
    # columns to make the sort consistent over runs -- which is good
    # for the user and essential for the test suite.
    unambiguous_cols = set([
        Bug.date_last_updated,
        Bug.datecreated,
        Bug.id,
        BugTask.bugID,
        BugTask.date_assigned,
        BugTask.datecreated,
        BugTask.id,
        ])
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
    extra_joins = []
    ambiguous = True
    # Sorting by milestone only is a very "coarse" sort order.
    # If no additional sort order is specified, add the bug task
    # importance as a secondary sort order.
    if len(orderby) == 1:
        if orderby[0] == 'milestone_name':
            # We want the most important bugtasks first; these have
            # larger integer values.
            orderby.append('-importance')
        elif orderby[0] == '-milestone_name':
            orderby.append('importance')
        else:
            # Other sort orders don't need tweaking.
            pass

    for orderby_col in orderby:
        if isinstance(orderby_col, SQLConstant):
            orderby_arg.append(orderby_col)
            continue
        if orderby_col.startswith("-"):
            col, sort_joins = orderby_expression[orderby_col[1:]]
            extra_joins.extend(sort_joins)
            order_clause = Desc(col)
        else:
            col, sort_joins = orderby_expression[orderby_col]
            extra_joins.extend(sort_joins)
            order_clause = col
        if col in unambiguous_cols:
            ambiguous = False
        orderby_arg.append(order_clause)

    if ambiguous:
        if in_unique_context:
            orderby_arg.append(BugTask.bugID)
        else:
            orderby_arg.append(BugTask.id)

    return tuple(orderby_arg), extra_joins


def _require_params(params):
    assert zope_isinstance(params, BugTaskSearchParams)
    if not isinstance(params, BugTaskSearchParams):
        # Browser code let this get wrapped, unwrap it here as its just a
        # dumb data store that has no security implications.
        params = removeSecurityProxy(params)
    return params


def _build_search_text_clause(params):
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
            ]

    comment_clause = """BugTask.id IN (
        SELECT BugTask.id
        FROM BugTask, BugMessage,Message, MessageChunk
        WHERE BugMessage.bug = BugTask.bug
            AND BugMessage.message = Message.id
            AND Message.id = MessageChunk.message
            AND MessageChunk.fti @@ ftq(%s))""" % searchtext_quoted
    text_search_clauses = [
        "Bug.fti @@ ftq(%s)" % searchtext_quoted,
        ]
    no_targetnamesearch = bool(features.getFeatureFlag(
        'malone.disable_targetnamesearch'))
    if not no_targetnamesearch:
        text_search_clauses.append(
            "BugTask.targetnamecache ILIKE '%%' || %s || '%%'" % (
            searchtext_like_quoted))
    # Due to performance problems, whether to search in comments is
    # controlled by a config option.
    if config.malone.search_comments:
        text_search_clauses.append(comment_clause)
    return "(%s)" % " OR ".join(text_search_clauses)


def _build_fast_search_text_clause(params):
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


def _build_status_clause(status):
    """Return the SQL query fragment for search by status.

    Called from `_build_query` or recursively."""
    if zope_isinstance(status, any):
        values = list(status.query_values)
        # Since INCOMPLETE isn't stored as a single value we need to
        # expand it before generating the SQL.
        if BugTaskStatus.INCOMPLETE in values:
            values.remove(BugTaskStatus.INCOMPLETE)
            values.extend(DB_INCOMPLETE_BUGTASK_STATUSES)
        return '(BugTask.status {0})'.format(
            search_value_to_where_condition(any(*values)))
    elif zope_isinstance(status, not_equals):
        return '(NOT {0})'.format(_build_status_clause(status.value))
    elif zope_isinstance(status, BaseItem):
        # INCOMPLETE is not stored in the DB, instead one of
        # DB_INCOMPLETE_BUGTASK_STATUSES is stored, so any request to
        # search for INCOMPLETE should instead search for those values.
        if status == BugTaskStatus.INCOMPLETE:
            return '(BugTask.status {0})'.format(
                search_value_to_where_condition(
                    any(*DB_INCOMPLETE_BUGTASK_STATUSES)))
        else:
            return '(BugTask.status = %s)' % sqlvalues(status)
    else:
        raise ValueError('Unrecognized status value: %r' % (status,))


def _build_exclude_conjoined_clause(milestone):
    """Exclude bugtasks with a conjoined master.

    This search option only makes sense when searching for bugtasks
    for a milestone.  Only bugtasks for a project or a distribution
    can have a conjoined master bugtask, which is a bugtask on the
    project's development focus series or the distribution's
    currentseries. The project bugtask or the distribution bugtask
    will always have the same milestone set as its conjoined master
    bugtask, if it exists on the bug. Therefore, this prevents a lot
    of bugs having two bugtasks listed in the results. However, it
    is ok if a bug has multiple bugtasks in the results as long as
    those other bugtasks are on other series.
    """
    # XXX: EdwinGrubbs 2010-12-15 bug=682989
    # (ConjoinedMaster.bug == X) produces the wrong sql, but
    # (ConjoinedMaster.bugID == X) works right. This bug applies to
    # all foreign keys on the ClassAlias.

    # Perform a LEFT JOIN to the conjoined master bugtask.  If the
    # conjoined master is not null, it gets filtered out.
    ConjoinedMaster = ClassAlias(BugTask, 'ConjoinedMaster')
    extra_clauses = ["ConjoinedMaster.id IS NULL"]
    if milestone.distribution is not None:
        current_series = milestone.distribution.currentseries
        join = LeftJoin(
            ConjoinedMaster,
            And(ConjoinedMaster.bugID == BugTask.bugID,
                BugTask.distributionID == milestone.distribution.id,
                ConjoinedMaster.distroseriesID == current_series.id,
                Not(ConjoinedMaster._status.is_in(
                        BugTask._NON_CONJOINED_STATUSES))))
        join_tables = [(ConjoinedMaster, join)]
    else:
        # Prevent import loop.
        from lp.registry.model.milestone import Milestone
        from lp.registry.model.product import Product
        if IProjectGroupMilestone.providedBy(milestone):
            # Since an IProjectGroupMilestone could have bugs with
            # bugtasks on two different projects, the project
            # bugtask is only excluded by a development focus series
            # bugtask on the same project.
            joins = [
                Join(Milestone, BugTask.milestone == Milestone.id),
                LeftJoin(Product, BugTask.product == Product.id),
                LeftJoin(
                    ConjoinedMaster,
                    And(ConjoinedMaster.bugID == BugTask.bugID,
                        ConjoinedMaster.productseriesID
                            == Product.development_focusID,
                        Not(ConjoinedMaster._status.is_in(
                                BugTask._NON_CONJOINED_STATUSES)))),
                ]
            # join.right is the table name.
            join_tables = [(join.right, join) for join in joins]
        elif milestone.product is not None:
            dev_focus_id = (
                milestone.product.development_focusID)
            join = LeftJoin(
                ConjoinedMaster,
                And(ConjoinedMaster.bugID == BugTask.bugID,
                    BugTask.productID == milestone.product.id,
                    ConjoinedMaster.productseriesID == dev_focus_id,
                    Not(ConjoinedMaster._status.is_in(
                            BugTask._NON_CONJOINED_STATUSES))))
            join_tables = [(ConjoinedMaster, join)]
        else:
            raise AssertionError(
                "A milestone must always have either a project, "
                "project group, or distribution")
    return (join_tables, extra_clauses)


def _build_hardware_related_clause(params):
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


def _build_blueprint_related_clause(params):
    """Find bugs related to Blueprints, or not."""
    linked_blueprints = params.linked_blueprints
    if linked_blueprints is None:
        return None
    elif zope_isinstance(linked_blueprints, BaseItem):
        if linked_blueprints == BugBlueprintSearch.BUGS_WITH_BLUEPRINTS:
            return "EXISTS (%s)" % (
                "SELECT 1 FROM SpecificationBug"
                " WHERE SpecificationBug.bug = Bug.id")
        elif (linked_blueprints ==
                BugBlueprintSearch.BUGS_WITHOUT_BLUEPRINTS):
            return "NOT EXISTS (%s)" % (
                "SELECT 1 FROM SpecificationBug"
                " WHERE SpecificationBug.bug = Bug.id")
    else:
        # A specific search term has been supplied.
        return """EXISTS (
                SELECT TRUE FROM SpecificationBug
                WHERE SpecificationBug.bug=Bug.id AND
                SpecificationBug.specification %s)
            """ % search_value_to_where_condition(linked_blueprints)


# Upstream task restrictions

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

_open_resolved_upstream_with_target = """
    EXISTS (
        SELECT TRUE FROM BugTask AS RelatedBugTask
        WHERE RelatedBugTask.bug = BugTask.bug
            AND RelatedBugTask.id != BugTask.id
            AND ((
                RelatedBugTask.%(target_column)s = %(target_id)s AND
                RelatedBugTask.bugwatch IS NOT NULL AND
                RelatedBugTask.status %(status_with_watch)s)
                OR (
                RelatedBugTask.%(target_column)s = %(target_id)s AND
                RelatedBugTask.bugwatch IS NULL AND
                RelatedBugTask.status %(status_without_watch)s))
        )
    """


def _build_pending_bugwatch_elsewhere_clause(params):
    """Return a clause for BugTaskSearchParams.pending_bugwatch_elsewhere
    """
    if params.product:
        # Include only bugtasks that do no have bug watches that
        # belong to a product that does not use Malone.
        return """
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
    elif params.upstream_target is None:
        # Include only bugtasks that have other bugtasks on targets
        # not using Malone, which are not Invalid, and have no bug
        # watch.
        return """
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
    else:
        # Include only bugtasks that have other bugtasks on
        # params.upstream_target, but only if this this product
        # does not use Malone and if the bugtasks are not Invalid,
        # and have no bug watch.
        if IProduct.providedBy(params.upstream_target):
            target_clause = 'RelatedBugTask.product = %s'
        elif IDistribution.providedBy(params.upstream_target):
            target_clause = 'RelatedBugTask.distribution = %s'
        else:
            raise AssertionError(
                'params.upstream_target must be a Distribution or '
                'a Product')
        # There is no point to construct a real sub-select if we
        # already know that the result will be empty.
        if params.upstream_target.official_malone:
            return 'false'
        target_clause = target_clause % sqlvalues(
            params.upstream_target.id)
        return """
            EXISTS (
                SELECT TRUE
                FROM BugTask AS RelatedBugTask
                WHERE RelatedBugTask.bug = BugTask.bug
                    AND RelatedBugTask.id != BugTask.id
                    AND RelatedBugTask.bugwatch IS NULL
                    AND %s
                    AND RelatedBugTask.status != %s)
            """ % (target_clause, sqlvalues(BugTaskStatus.INVALID)[0])


def _build_no_upstream_bugtask_clause(params):
    """Return a clause for BugTaskSearchParams.has_no_upstream_bugtask."""
    if params.upstream_target is None:
        # Find all bugs that has no product bugtask. We limit the
        # SELECT by matching against BugTask.bug to make the query
        # faster.
        return """
            NOT EXISTS (SELECT TRUE
                        FROM BugTask AS OtherBugTask
                        WHERE OtherBugTask.bug = BugTask.bug
                            AND OtherBugTask.product IS NOT NULL)
        """
    elif IProduct.providedBy(params.upstream_target):
        return """
            NOT EXISTS (SELECT TRUE
                        FROM BugTask AS OtherBugTask
                        WHERE OtherBugTask.bug = BugTask.bug
                            AND OtherBugTask.product=%s)
        """ % sqlvalues(params.upstream_target.id)
    elif IDistribution.providedBy(params.upstream_target):
        return """
            NOT EXISTS (SELECT TRUE
                        FROM BugTask AS OtherBugTask
                        WHERE OtherBugTask.bug = BugTask.bug
                            AND OtherBugTask.distribution=%s)
        """ % sqlvalues(params.upstream_target.id)
    else:
        raise AssertionError(
            'params.upstream_target must be a Distribution or '
            'a Product')


def _build_open_or_resolved_upstream_clause(params,
                                      statuses_for_watch_tasks,
                                      statuses_for_upstream_tasks):
    """Return a clause for BugTaskSearchParams.open_upstream or
    BugTaskSearchParams.resolved_upstream."""
    if params.upstream_target is None:
        return _open_resolved_upstream % (
                search_value_to_where_condition(
                    any(*statuses_for_watch_tasks)),
                search_value_to_where_condition(
                    any(*statuses_for_upstream_tasks)))
    elif IProduct.providedBy(params.upstream_target):
        query_values = {'target_column': 'product'}
    elif IDistribution.providedBy(params.upstream_target):
        query_values = {'target_column': 'distribution'}
    else:
        raise AssertionError(
            'params.upstream_target must be a Distribution or '
            'a Product')
    query_values['target_id'] = sqlvalues(params.upstream_target.id)[0]
    query_values['status_with_watch'] = search_value_to_where_condition(
        any(*statuses_for_watch_tasks))
    query_values['status_without_watch'] = search_value_to_where_condition(
        any(*statuses_for_upstream_tasks))
    return _open_resolved_upstream_with_target % query_values


def _build_open_upstream_clause(params):
    """Return a clause for BugTaskSearchParams.open_upstream."""
    statuses_for_open_tasks = [
        BugTaskStatus.NEW,
        BugTaskStatus.INCOMPLETE,
        BugTaskStatusSearch.INCOMPLETE_WITHOUT_RESPONSE,
        BugTaskStatusSearch.INCOMPLETE_WITH_RESPONSE,
        BugTaskStatus.CONFIRMED,
        BugTaskStatus.INPROGRESS,
        BugTaskStatus.UNKNOWN]
    return _build_open_or_resolved_upstream_clause(
        params, statuses_for_open_tasks, statuses_for_open_tasks)


def _build_resolved_upstream_clause(params):
    """Return a clause for BugTaskSearchParams.open_upstream."""
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
    statuses_for_watch_tasks = [
        BugTaskStatus.INVALID,
        BugTaskStatus.FIXCOMMITTED,
        BugTaskStatus.FIXRELEASED]
    statuses_for_upstream_tasks = [
        BugTaskStatus.FIXCOMMITTED,
        BugTaskStatus.FIXRELEASED]
    return _build_open_or_resolved_upstream_clause(
        params, statuses_for_watch_tasks, statuses_for_upstream_tasks)


def _build_upstream_clause(params):
    """Return an clause for returning upstream data if the data exists.

    This method will handles BugTasks that do not have upstream BugTasks
    as well as thoses that do.
    """
    params = _require_params(params)
    upstream_clauses = []
    if params.pending_bugwatch_elsewhere:
        upstream_clauses.append(
            _build_pending_bugwatch_elsewhere_clause(params))
    if params.has_no_upstream_bugtask:
        upstream_clauses.append(
            _build_no_upstream_bugtask_clause(params))
    if params.resolved_upstream:
        upstream_clauses.append(_build_resolved_upstream_clause(params))
    if params.open_upstream:
        upstream_clauses.append(_build_open_upstream_clause(params))

    if upstream_clauses:
        upstream_clause = " OR ".join(upstream_clauses)
        return '(%s)' % upstream_clause
    return None


# Tag restrictions

def _build_tag_set_query(joiner, tags):
    """Return an SQL snippet to find whether a bug matches the given tags.

    The tags are sorted so that testing the generated queries is
    easier and more reliable.

    This SQL is designed to be a sub-query where the parent SQL defines
    Bug.id. It evaluates to TRUE or FALSE, indicating whether the bug
    with Bug.id matches against the tags passed.

    Returns None if no tags are passed.

    :param joiner: The SQL set term used to join the individual tag
        clauses, typically "INTERSECT" or "UNION".
    :param tags: An iterable of valid tag names (not prefixed minus
        signs, not wildcards).
    """
    tags = list(tags)
    if tags == []:
        return None

    joiner = " %s " % joiner
    return "EXISTS (%s)" % joiner.join(
        "SELECT TRUE FROM BugTag WHERE " +
            "BugTag.bug = Bug.id AND BugTag.tag = %s" % quote(tag)
        for tag in sorted(tags))


def _build_tag_set_query_any(tags):
    """Return a query fragment for bugs matching any tag.

    :param tags: An iterable of valid tags without - or + and not wildcards.
    :return: A string SQL query fragment or None if no tags were provided.
    """
    tags = sorted(tags)
    if tags == []:
        return None
    return "EXISTS (%s)" % (
        "SELECT TRUE FROM BugTag"
        " WHERE BugTag.bug = Bug.id"
        " AND BugTag.tag IN %s") % sqlvalues(tags)


def _build_tag_search_clause(tags_spec):
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
        include_clause = _build_tag_set_query("INTERSECT", include)
        # The set of bugs that have *any* of the tags requested for
        # *exclusion*.
        exclude_clause = _build_tag_set_query_any(exclude)
    else:
        # How to combine an include clause and an exclude clause when
        # both are generated.
        combine_with = 'OR'
        # The set of bugs that have *any* of the tags requested for
        # inclusion.
        include_clause = _build_tag_set_query_any(include)
        # The set of bugs that have *all* of the tags requested for
        # exclusion.
        exclude_clause = _build_tag_set_query("INTERSECT", exclude)

    # Search for the *presence* of any tag.
    if '*' in wildcards:
        # Only clobber the clause if not searching for all tags.
        if include_clause == None or not find_all:
            include_clause = (
                "EXISTS (SELECT TRUE FROM BugTag WHERE BugTag.bug = Bug.id)")

    # Search for the *absence* of any tag.
    if '-*' in wildcards:
        # Only clobber the clause if searching for all tags.
        if exclude_clause == None or find_all:
            exclude_clause = (
                "EXISTS (SELECT TRUE FROM BugTag WHERE BugTag.bug = Bug.id)")

    # Combine the include and exclude sets.
    if include_clause != None and exclude_clause != None:
        return "(%s %s NOT %s)" % (
            include_clause, combine_with, exclude_clause)
    elif include_clause != None:
        return "%s" % include_clause
    elif exclude_clause != None:
        return "NOT %s" % exclude_clause
    else:
        # This means that there were no tags (wildcard or specific) to
        # search for (which is allowed, even if it's a bit weird).
        return None


# Privacy restrictions

def get_bug_privacy_filter(user, private_only=False):
    """An SQL filter for search results that adds privacy-awareness."""
    return _get_bug_privacy_filter_with_decorator(user, private_only)[0]


def _nocache_bug_decorator(obj):
    """A pass through decorator for consistency.

    :seealso: _get_bug_privacy_filter_with_decorator
    """
    return obj


def _make_cache_user_can_view_bug(user):
    """Curry a decorator for bugtask queries to cache permissions.

    :seealso: _get_bug_privacy_filter_with_decorator
    """
    userid = user.id

    def cache_user_can_view_bug(bugtask):
        get_property_cache(bugtask.bug)._known_viewers = set([userid])
        return bugtask
    return cache_user_can_view_bug


def _get_bug_privacy_filter_with_decorator(user, private_only=False):
    """Return a SQL filter to limit returned bug tasks.

    :param user: The user whose visible bugs will be filtered.
    :param private_only: If a user is specified, this parameter determines
        whether only private bugs will be filtered. If True, the returned
        filter omits the "Bug.private IS FALSE" clause.
    :return: A SQL filter, a decorator to cache visibility in a resultset that
        returns BugTask objects.
    """
    if user is None:
        return "Bug.private IS FALSE", _nocache_bug_decorator
    admin_team = getUtility(ILaunchpadCelebrities).admin
    if user.inTeam(admin_team):
        return "", _nocache_bug_decorator

    public_bug_filter = ''
    if not private_only:
        public_bug_filter = 'Bug.private IS FALSE OR'

    # A subselect is used here because joining through
    # TeamParticipation is only relevant to the "user-aware"
    # part of the WHERE condition (i.e. the bit below.) The
    # other half of this condition (see code above) does not
    # use TeamParticipation at all.
    pillar_privacy_filters = ''
    if features.getFeatureFlag(
        'disclosure.private_bug_visibility_cte.enabled'):
        if features.getFeatureFlag(
            'disclosure.private_bug_visibility_rules.enabled'):
            pillar_privacy_filters = """
                UNION ALL
                SELECT BugTask.bug
                FROM BugTask, Product
                WHERE Product.owner IN (SELECT team FROM teams) AND
                    BugTask.product = Product.id AND
                    BugTask.bug = Bug.id AND
                    Bug.security_related IS False
                UNION ALL
                SELECT BugTask.bug
                FROM BugTask, ProductSeries
                WHERE ProductSeries.owner IN (SELECT team FROM teams) AND
                    BugTask.productseries = ProductSeries.id AND
                    BugTask.bug = Bug.id AND
                    Bug.security_related IS False
                UNION ALL
                SELECT BugTask.bug
                FROM BugTask, Distribution
                WHERE Distribution.owner IN (SELECT team FROM teams) AND
                    BugTask.distribution = Distribution.id AND
                    BugTask.bug = Bug.id AND
                    Bug.security_related IS False
                UNION ALL
                SELECT BugTask.bug
                FROM BugTask, DistroSeries, Distribution
                WHERE Distribution.owner IN (SELECT team FROM teams) AND
                    DistroSeries.distribution = Distribution.id AND
                    BugTask.distroseries = DistroSeries.id AND
                    BugTask.bug = Bug.id AND
                    Bug.security_related IS False
            """
        query = """
            (%(public_bug_filter)s EXISTS (
                WITH teams AS (
                    SELECT team from TeamParticipation
                    WHERE person = %(personid)s
                )
                SELECT BugSubscription.bug
                FROM BugSubscription
                WHERE BugSubscription.person IN (SELECT team FROM teams) AND
                    BugSubscription.bug = Bug.id
                UNION ALL
                SELECT BugTask.bug
                FROM BugTask
                WHERE BugTask.assignee IN (SELECT team FROM teams) AND
                    BugTask.bug = Bug.id
                %(extra_filters)s
                    ))
            """ % dict(
                    personid=quote(user.id),
                    public_bug_filter=public_bug_filter,
                    extra_filters=pillar_privacy_filters)
    else:
        if features.getFeatureFlag(
            'disclosure.private_bug_visibility_rules.enabled'):
            pillar_privacy_filters = """
                UNION ALL
                SELECT BugTask.bug
                FROM BugTask, TeamParticipation, Product
                WHERE TeamParticipation.person = %(personid)s AND
                    TeamParticipation.team = Product.owner AND
                    BugTask.product = Product.id AND
                    BugTask.bug = Bug.id AND
                    Bug.security_related IS False
                UNION ALL
                SELECT BugTask.bug
                FROM BugTask, TeamParticipation, ProductSeries
                WHERE TeamParticipation.person = %(personid)s AND
                    TeamParticipation.team = ProductSeries.owner AND
                    BugTask.productseries = ProductSeries.id AND
                    BugTask.bug = Bug.id AND
                    Bug.security_related IS False
                UNION ALL
                SELECT BugTask.bug
                FROM BugTask, TeamParticipation, Distribution
                WHERE TeamParticipation.person = %(personid)s AND
                    TeamParticipation.team = Distribution.owner AND
                    BugTask.distribution = Distribution.id AND
                    BugTask.bug = Bug.id AND
                    Bug.security_related IS False
                UNION ALL
                SELECT BugTask.bug
                FROM BugTask, TeamParticipation, DistroSeries, Distribution
                WHERE TeamParticipation.person = %(personid)s AND
                    TeamParticipation.team = Distribution.owner AND
                    DistroSeries.distribution = Distribution.id AND
                    BugTask.distroseries = DistroSeries.id AND
                    BugTask.bug = Bug.id AND
                    Bug.security_related IS False
            """ % sqlvalues(personid=user.id)
        query = """
            (%(public_bug_filter)s EXISTS (
                SELECT BugSubscription.bug
                FROM BugSubscription, TeamParticipation
                WHERE TeamParticipation.person = %(personid)s AND
                    TeamParticipation.team = BugSubscription.person AND
                    BugSubscription.bug = Bug.id
                UNION ALL
                SELECT BugTask.bug
                FROM BugTask, TeamParticipation
                WHERE TeamParticipation.person = %(personid)s AND
                    TeamParticipation.team = BugTask.assignee AND
                    BugTask.bug = Bug.id
                %(extra_filters)s
                    ))
            """ % dict(
                    personid=quote(user.id),
                    public_bug_filter=public_bug_filter,
                    extra_filters=pillar_privacy_filters)
    return query, _make_cache_user_can_view_bug(user)
