# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

"""Interfaces related to bugs."""

__metaclass__ = type


__all__ = [
    'BugDistroSeriesTargetDetails',
    'IBugTarget',
    'IHasBugs',
    'IHasBugHeat',
    'IHasOfficialBugTags',
    'IOfficialBugTag',
    'IOfficialBugTagTarget',
    'IOfficialBugTagTargetPublic',
    'IOfficialBugTagTargetRestricted',
    ]

from zope.interface import Interface, Attribute
from zope.schema import Bool, Choice, Datetime, List, Object, Text, TextLine

from canonical.launchpad import _
from canonical.launchpad.fields import Tag
from lp.bugs.interfaces.bugtask import (
    BugBranchSearch, BugTagsSearchCombinator, IBugTask, IBugTaskSearch)
from lazr.enum import DBEnumeratedType
from lazr.restful.fields import Reference
from lazr.restful.interface import copy_field
from lazr.restful.declarations import (
    LAZR_WEBSERVICE_EXPORTED, REQUEST_USER, call_with,
    export_as_webservice_entry, export_read_operation, export_write_operation,
    exported, operation_parameters, operation_returns_collection_of)


class IHasBugs(Interface):
    """An entity which has a collection of bug tasks."""

    export_as_webservice_entry()

    # XXX Tom Berger 2008-09-26, Bug #274735
    # The following are attributes, rather than fields, and must remain
    # so, to make sure that they are not being copied into snapshots.
    # Eventually, we'd like to remove these attributes from the content
    # class altogether.
    open_bugtasks = Attribute("A list of open bugTasks for this target.")
    closed_bugtasks = Attribute("A list of closed bugTasks for this target.")
    inprogress_bugtasks = Attribute(
        "A list of in-progress bugTasks for this target.")
    high_bugtasks = Attribute(
        "A list of high importance BugTasks for this target.")
    critical_bugtasks = Attribute(
        "A list of critical BugTasks for this target.")
    new_bugtasks = Attribute("A list of New BugTasks for this target.")
    unassigned_bugtasks = Attribute(
        "A list of unassigned BugTasks for this target.")
    all_bugtasks = Attribute(
        "A list of all BugTasks ever reported for this target.")
    has_bugtasks = Attribute(
        "True if a BugTask has ever been reported for this target.")

    @call_with(search_params=None, user=REQUEST_USER)
    @operation_parameters(
        order_by=List(
            title=_('List of fields by which the results are ordered.'),
            value_type=Text(),
            required=False),
        search_text=copy_field(IBugTaskSearch['searchtext']),
        status=copy_field(IBugTaskSearch['status']),
        importance=copy_field(IBugTaskSearch['importance']),
        assignee=Reference(schema=Interface),
        bug_reporter=Reference(schema=Interface),
        bug_supervisor=Reference(schema=Interface),
        bug_commenter=Reference(schema=Interface),
        bug_subscriber=Reference(schema=Interface),
        structural_subscriber=Reference(schema=Interface),
        owner=Reference(schema=Interface),
        affected_user=Reference(schema=Interface),
        has_patch=copy_field(IBugTaskSearch['has_patch']),
        has_cve=copy_field(IBugTaskSearch['has_cve']),
        tags=copy_field(IBugTaskSearch['tag']),
        tags_combinator=copy_field(IBugTaskSearch['tags_combinator']),
        omit_duplicates=copy_field(IBugTaskSearch['omit_dupes']),
        omit_targeted=copy_field(IBugTaskSearch['omit_targeted']),
        status_upstream=copy_field(IBugTaskSearch['status_upstream']),
        milestone_assignment=copy_field(
            IBugTaskSearch['milestone_assignment']),
        milestone=copy_field(IBugTaskSearch['milestone']),
        component=copy_field(IBugTaskSearch['component']),
        nominated_for=Reference(schema=Interface),
        has_no_package=copy_field(IBugTaskSearch['has_no_package']),
        hardware_bus=Choice(
            title=u'The bus of a hardware device related to a bug',
            # The vocabulary should be HWBus; this is fixed in
            # _schema_circular_imports to avoid circular imports.
            vocabulary=DBEnumeratedType, required=False),
        hardware_vendor_id=TextLine(
            title=(
                u"The vendor ID of a hardware device related to a bug."),
            description=(
                u"Allowed values of the vendor ID depend on the bus of the "
                "device.\n\n"
                "Vendor IDs of PCI, PCCard and USB devices are hexadecimal "
                "string representations of 16 bit integers in the format "
                "'0x01ab': The prefix '0x', followed by exactly 4 digits; "
                "where a digit is one of the characters 0..9, a..f. The "
                "characters A..F are not allowed.\n\n"
                "SCSI vendor IDs are strings with exactly 8 characters. "
                "Shorter names are right-padded with space (0x20) characters."
                "\n\n"
                "IDs for other buses may be arbitrary strings."),
            required=False),
        hardware_product_id=TextLine(
            title=(
                u"The product ID of a hardware device related to a bug."),
            description=(
                u"Allowed values of the product ID depend on the bus of the "
                "device.\n\n"
                "Product IDs of PCI, PCCard and USB devices are hexadecimal "
                "string representations of 16 bit integers in the format "
                "'0x01ab': The prefix '0x', followed by exactly 4 digits; "
                "where a digit is one of the characters 0..9, a..f. The "
                "characters A..F are not allowed.\n\n"
                "SCSI product IDs are strings with exactly 16 characters. "
                "Shorter names are right-padded with space (0x20) characters."
                "\n\n"
                "IDs for other buses may be arbitrary strings."),
            required=False),
        hardware_driver_name=TextLine(
            title=(
                u"The driver controlling a hardware device related to a "
                "bug."),
            required=False),
        hardware_driver_package_name=TextLine(
            title=(
                u"The package of the driver which controls a hardware "
                "device related to a bug."),
            required=False),
        hardware_owner_is_bug_reporter=Bool(
            title=(
                u"Search for bugs reported by people who own the given "
                "device or who use the given hardware driver."),
            required=False),
        hardware_owner_is_affected_by_bug=Bool(
            title=(
                u"Search for bugs where people affected by a bug own the "
                "given device or use the given hardware driver."),
            required=False),
        hardware_owner_is_subscribed_to_bug=Bool(
            title=(
                u"Search for bugs where a bug subscriber owns the "
                "given device or uses the given hardware driver."),
            required=False),
        hardware_is_linked_to_bug=Bool(
            title=(
                u"Search for bugs which are linked to hardware reports "
                "which contain the given device or whcih contain a device"
                "controlled by the given driver."),
            required=False),
        linked_branches=Choice(
            title=(
                u"Search for bugs that are linked to branches or for bugs "
                "that are not linked to branches."),
            vocabulary=BugBranchSearch, required=False),
        modified_since=Datetime(
            title=(
                u"Search for bugs that have been modified since the given "
                "date."),
            required=False),
        )
    @operation_returns_collection_of(IBugTask)
    @export_read_operation()
    def searchTasks(search_params, user=None,
                    order_by=None, search_text=None,
                    status=None, importance=None,
                    assignee=None, bug_reporter=None, bug_supervisor=None,
                    bug_commenter=None, bug_subscriber=None, owner=None,
                    affected_user=None, has_patch=None, has_cve=None,
                    distribution=None, tags=None,
                    tags_combinator=BugTagsSearchCombinator.ALL,
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
                    hardware_is_linked_to_bug=False, linked_branches=None,
                    structural_subscriber=None, modified_since=None):
        """Search the IBugTasks reported on this entity.

        :search_params: a BugTaskSearchParams object

        Return an iterable of matching results.

        Note: milestone is currently ignored for all IBugTargets
        except IProduct.

        In order to search bugs that are related to a given hardware
        device, you must specify the bus, the vendor ID, the product
        ID of the device and set at least one of
        hardware_owner_is_bug_reporter,
        hardware_owner_is_affected_by_bug,
        hardware_owner_is_subscribed_to_bug,
        hardware_is_linked_to_bug to True.
        """

    def getBugCounts(user, statuses=None):
        """Return a dict with the number of bugs in each possible status.

            :user: Only bugs the user has permission to view will be
                   counted.
            :statuses: Only bugs with these statuses will be counted. If
                       None, all statuses will be included.
        """


class IBugTarget(IHasBugs):
    """An entity on which a bug can be reported.

    Examples include an IDistribution, an IDistroSeries and an
    IProduct.
    """

    export_as_webservice_entry()

    # XXX Brad Bollenbach 2006-08-02 bug=54974: This attribute name smells.
    bugtargetdisplayname = Attribute("A display name for this bug target")
    bugtargetname = Attribute("The target as shown in mail notifications.")

    bug_reporting_guidelines = exported(
        Text(
            title=(
                u"Helpful guidelines for reporting a bug"),
            description=(
                u"These guidelines will be shown to "
                "everyone reporting a bug and should be "
                "text or a bulleted list with your particular "
                "requirements, if any."),
            required=False,
            max_length=50000))

    bug_reported_acknowledgement = exported(
        Text(
            title=(
                u"After reporting a bug, I can expect the following."),
            description=(
                u"This message of acknowledgement will be displayed "
                "to anyone after reporting a bug."),
            required=False,
            max_length=50000))

    def createBug(bug_params):
        """Create a new bug on this target.

        bug_params is an instance of
        canonical.launchpad.interfaces.CreateBugParams.
        """

# We assign the schema for an `IBugTask` attribute here
# in order to avoid circular dependencies.
IBugTask['target'].schema = IBugTarget
IBugTask['transitionToTarget'].getTaggedValue(
    LAZR_WEBSERVICE_EXPORTED)['params']['target'].schema = IBugTarget


class IHasBugHeat(Interface):
    """An entity which has bug heat."""

    max_bug_heat = Attribute(
        "The current highest bug heat value for this entity.")

    def setMaxBugHeat(heat):
        """Set the max_bug_heat for this context."""

    def recalculateBugHeatCache():
        """Recalculate and set the various bug heat values for this context.

        Several different objects cache max_bug_heat.
        When DistributionSourcePackage is the target, the total_bug_heat
        and bug_count are also cached.
        """


class BugDistroSeriesTargetDetails:
    """The details of a bug targeted to a specific IDistroSeries.

    The following attributes are provided:

    :series: The IDistroSeries.
    :istargeted: Is there a fix targeted to this series?
    :sourcepackage: The sourcepackage to which the fix would be targeted.
    :assignee: An IPerson, or None if no assignee.
    :status: A BugTaskStatus dbschema item, or None, if series is not targeted.
    """
    def __init__(self, series, istargeted=False, sourcepackage=None,
                 assignee=None, status=None):
        self.series = series
        self.istargeted = istargeted
        self.sourcepackage = sourcepackage
        self.assignee = assignee
        self.status = status


class IHasOfficialBugTags(Interface):
    """An entity that exposes a set of official bug tags."""

    official_bug_tags = exported(List(
        title=_("Official Bug Tags"),
        description=_("The list of bug tags defined as official."),
        value_type=Tag(),
        readonly=True))

    def getUsedBugTags():
        """Return the tags used by the context as a sorted list of strings."""

    def getUsedBugTagsWithOpenCounts(user):
        """Return name and bug count of tags having open bugs.

        It returns a list of tuples contining the tag name, and the
        number of open bugs having that tag. Only the bugs that the user
        has permission to see are counted, and only tags having open
        bugs will be returned.
        """


class IOfficialBugTagTargetPublic(IHasOfficialBugTags):
    """Public attributes for `IOfficialBugTagTarget`."""

    official_bug_tags = copy_field(
        IHasOfficialBugTags['official_bug_tags'], readonly=False)


class IOfficialBugTagTargetRestricted(Interface):
    """Restricted methods for `IOfficialBugTagTarget`."""

    @operation_parameters(
        tag=Tag(title=u'The official bug tag', required=True))
    @export_write_operation()
    def addOfficialBugTag(tag):
        """Add tag to the official bug tags of this target."""

    @operation_parameters(
        tag=Tag(title=u'The official bug tag', required=True))
    @export_write_operation()
    def removeOfficialBugTag(tag):
        """Remove tag from the official bug tags of this target."""


class IOfficialBugTagTarget(IOfficialBugTagTargetPublic,
                            IOfficialBugTagTargetRestricted):
    """An entity for which official bug tags can be defined."""
    # XXX intellectronica 2009-03-16 bug=342413
    # We can start using straight inheritance once it becomes possible
    # to export objects implementing multiple interfaces in the
    # webservice API.


class IOfficialBugTag(Interface):
    """Official bug tags for a product, a project or a distribution."""
    tag = Tag(
        title=u'The official bug tag', required=True)

    target = Object(
        title=u'The target of this bug tag.',
        schema=IOfficialBugTagTarget,
        description=
            u'The distribution or product having this official bug tag.')
