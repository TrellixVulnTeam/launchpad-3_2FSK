# Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""IBugTask-related browser views."""

__metaclass__ = type

__all__ = [
    'BugListingBatchNavigator',
    'BugListingPortletInfoView',
    'BugListingPortletStatsView',
    'BugNominationsView',
    'BugsBugTaskSearchListingView',
    'bugtarget_renderer',
    'BugTargetTraversalMixin',
    'BugTargetView',
    'bugtask_heat_html',
    'BugTaskBreadcrumb',
    'BugTaskContextMenu',
    'BugTaskCreateQuestionView',
    'BugTaskEditView',
    'BugTaskExpirableListingView',
    'BugTaskListingItem',
    'BugTaskListingView',
    'BugTaskNavigation',
    'BugTaskPortletView',
    'BugTaskPrivacyAdapter',
    'BugTaskRemoveQuestionView',
    'BugTasksAndNominationsView',
    'BugTaskSearchListingView',
    'BugTaskSetNavigation',
    'BugTaskStatusView',
    'BugTaskTableRowView',
    'BugTaskTextView',
    'BugTaskView',
    'calculate_heat_display',
    'get_buglisting_search_filter_url',
    'get_comments_for_bugtask',
    'get_sortorder_from_request',
    'get_visible_comments',
    'NominationsReviewTableBatchNavigatorView',
    'TextualBugTaskSearchListingView',
    ]

import cgi
from collections import defaultdict
from datetime import (
    datetime,
    timedelta,
    )
from itertools import groupby
from math import (
    floor,
    log,
    )
from operator import attrgetter
import re
import transaction
import urllib

from lazr.delegates import delegates
from lazr.enum import (
    EnumeratedType,
    Item,
    )
from lazr.lifecycle.event import ObjectModifiedEvent
from lazr.lifecycle.snapshot import Snapshot
from lazr.restful.interface import copy_field
from lazr.restful.interfaces import (
    IFieldHTMLRenderer,
    IJSONRequestCache,
    IReference,
    IWebServiceClientRequest,
    )
from lazr.uri import URI
from pytz import utc
from simplejson import dumps
from z3c.ptcompat import ViewPageTemplateFile
from zope import (
    component,
    formlib,
    )
from zope.app.form import CustomWidgetFactory
from zope.app.form.browser.itemswidgets import RadioWidget
from zope.app.form.interfaces import (
    IDisplayWidget,
    IInputWidget,
    InputErrors,
    WidgetsError,
    )
from zope.app.form.utility import (
    setUpWidget,
    setUpWidgets,
    )
from zope.component import (
    ComponentLookupError,
    getAdapter,
    getMultiAdapter,
    getUtility,
    queryMultiAdapter,
    )
from zope.event import notify
from zope.interface import (
    implementer,
    implements,
    Interface,
    providedBy,
    )
from zope.schema import Choice
from zope.schema.interfaces import (
    IContextSourceBinder,
    IList,
    )
from zope.schema.vocabulary import (
    getVocabularyRegistry,
    SimpleVocabulary,
    )
from zope.security.interfaces import Unauthorized
from zope.security.proxy import (
    isinstance as zope_isinstance,
    removeSecurityProxy,
    )
from zope.traversing.interfaces import IPathAdapter

from canonical.config import config
from canonical.launchpad import (
    _,
    helpers,
    )
from canonical.launchpad.browser.feeds import (
    BugTargetLatestBugsFeedLink,
    FeedsMixin,
    )
from canonical.launchpad.interfaces.launchpad import IHasExternalBugTracker
from canonical.launchpad.mailnotification import get_unified_diff
from canonical.launchpad.searchbuilder import (
    all,
    any,
    NULL,
    )
from canonical.launchpad.webapp import (
    canonical_url,
    enabled_with_permission,
    GetitemNavigation,
    LaunchpadView,
    Link,
    Navigation,
    NavigationMenu,
    redirection,
    stepthrough,
    )
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.batching import TableBatchNavigator
from canonical.launchpad.webapp.breadcrumb import Breadcrumb
from canonical.launchpad.webapp.interfaces import ILaunchBag
from canonical.launchpad.webapp.menu import structured
from canonical.lazr.interfaces import IObjectPrivacy
from canonical.lazr.utils import smartquote
from lp.answers.interfaces.questiontarget import IQuestionTarget
from lp.app.browser.launchpadform import (
    action,
    custom_widget,
    LaunchpadEditFormView,
    LaunchpadFormView,
    )
from lp.app.browser.lazrjs import (
    TextAreaEditorWidget,
    TextLineEditorWidget,
    vocabulary_to_choice_edit_items,
    )
from lp.app.browser.stringformatter import FormattersAPI
from lp.app.browser.tales import (
    ObjectImageDisplayAPI,
    PersonFormatterAPI,
    )
from lp.app.enums import ServiceUsage
from lp.app.errors import (
    NotFoundError,
    UnexpectedFormData,
    )
from lp.app.interfaces.launchpad import (
    ILaunchpadCelebrities,
    IServiceUsage,
    )
from lp.app.validators import LaunchpadValidationError
from lp.app.widgets.itemswidgets import LabeledMultiCheckBoxWidget
from lp.app.widgets.launchpadtarget import LaunchpadTargetWidget
from lp.app.widgets.project import ProjectScopeWidget
from lp.bugs.browser.bug import (
    BugContextMenu,
    BugTextView,
    BugViewMixin,
    )
from lp.bugs.browser.bugcomment import (
    build_comments_from_chunks,
    group_comments_with_activity,
    )
from lp.bugs.browser.structuralsubscription import (
    expose_structural_subscription_data_to_js,
    )
from lp.bugs.browser.widgets.bug import BugTagsWidget
from lp.bugs.browser.widgets.bugtask import (
    AssigneeDisplayWidget,
    BugTaskAssigneeWidget,
    BugTaskBugWatchWidget,
    BugTaskSourcePackageNameWidget,
    DBItemDisplayWidget,
    NewLineToSpacesWidget,
    NominationReviewActionWidget,
    )
from lp.bugs.interfaces.bug import (
    IBug,
    IBugSet,
    )
from lp.bugs.interfaces.bugactivity import IBugActivity
from lp.bugs.interfaces.bugattachment import (
    BugAttachmentType,
    IBugAttachmentSet,
    )
from lp.bugs.interfaces.bugnomination import (
    BugNominationStatus,
    IBugNominationSet,
    )
from lp.bugs.interfaces.bugtarget import ISeriesBugTarget
from lp.bugs.interfaces.bugtask import (
    BugBlueprintSearch,
    BugBranchSearch,
    BugTagsSearchCombinator,
    BugTaskImportance,
    BugTaskSearchParams,
    BugTaskStatus,
    BugTaskStatusSearchDisplay,
    DEFAULT_SEARCH_BUGTASK_STATUSES_FOR_DISPLAY,
    IBugTask,
    IBugTaskSearch,
    IBugTaskSet,
    ICreateQuestionFromBugTaskForm,
    IFrontPageBugTaskSearch,
    IllegalTarget,
    INominationsReviewTableBatchNavigator,
    IPersonBugTaskSearch,
    IRemoveQuestionFromBugTaskForm,
    IUpstreamProductBugTaskSearch,
    UNRESOLVED_BUGTASK_STATUSES,
    UserCannotEditBugTaskStatus,
    )
from lp.bugs.interfaces.bugtracker import BugTrackerType
from lp.bugs.interfaces.bugwatch import BugWatchActivityStatus
from lp.bugs.interfaces.cve import ICveSet
from lp.bugs.interfaces.malone import IMaloneApplication
from lp.bugs.model.bugtask import validate_target
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
from lp.registry.interfaces.person import (
    IPerson,
    IPersonSet,
    )
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.projectgroup import IProjectGroup
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.registry.model.personroles import PersonRoles
from lp.registry.vocabularies import MilestoneVocabulary
from lp.services.fields import PersonChoice
from lp.services.propertycache import cachedproperty


DISPLAY_BUG_STATUS_FOR_PATCHES = {
    BugTaskStatus.NEW: True,
    BugTaskStatus.INCOMPLETE: True,
    BugTaskStatus.INVALID: False,
    BugTaskStatus.WONTFIX: False,
    BugTaskStatus.CONFIRMED: True,
    BugTaskStatus.TRIAGED: True,
    BugTaskStatus.INPROGRESS: True,
    BugTaskStatus.FIXCOMMITTED: True,
    BugTaskStatus.FIXRELEASED: False,
    BugTaskStatus.UNKNOWN: False,
    BugTaskStatus.EXPIRED: False,
    }


@component.adapter(IBugTask, IReference, IWebServiceClientRequest)
@implementer(IFieldHTMLRenderer)
def bugtarget_renderer(context, field, request):
    """Render a bugtarget as a link."""

    def render(value):
        html = """<span>
          <a href="%(href)s" class="%(class)s">%(displayname)s</a>
        </span>""" % {
            'href': canonical_url(context.target),
            'class': ObjectImageDisplayAPI(context.target).sprite_css(),
            'displayname': cgi.escape(context.bugtargetdisplayname)}
        return html
    return render


def unique_title(title):
    """Canonicalise a message title to help identify messages with new
    information in their titles.
    """
    if title is None:
        return None
    title = title.lower()
    if title.startswith('re:'):
        title = title[3:]
    return title.strip()


def get_comments_for_bugtask(bugtask, truncate=False, for_display=False,
    slice_info=None, show_spam_controls=False):
    """Return BugComments related to a bugtask.

    This code builds a sorted list of BugComments in one shot,
    requiring only two database queries. It removes the titles
    for those comments which do not have a "new" subject line

    :param for_display: If true, the zeroth comment is given an empty body so
        that it will be filtered by get_visible_comments.
    :param slice_info: If not None, defines a list of slices of the comments
        to retrieve.
    """
    comments = build_comments_from_chunks(bugtask, truncate=truncate,
        slice_info=slice_info, show_spam_controls=show_spam_controls)
    # TODO: further fat can be shaved off here by limiting the attachments we
    # query to those that slice_info would include.
    for attachment in bugtask.bug.attachments_unpopulated:
        message_id = attachment.message.id
        # All attachments are related to a message, so we can be
        # sure that the BugComment is already created.
        if message_id not in comments:
            # We are not showing this message.
            break
        if attachment.type == BugAttachmentType.PATCH:
            comments[message_id].patches.append(attachment)
        else:
            comments[message_id].bugattachments.append(attachment)
    comments = sorted(comments.values(), key=attrgetter("index"))
    current_title = bugtask.bug.title
    for comment in comments:
        if not ((unique_title(comment.title) == \
                 unique_title(current_title)) or \
                (unique_title(comment.title) == \
                 unique_title(bugtask.bug.title))):
            # this comment has a new title, so make that the rolling focus
            current_title = comment.title
            comment.display_title = True
    if for_display and comments and comments[0].index == 0:
        # We show the text of the first comment as the bug description,
        # or via the special link "View original description", but we want
        # to display attachments filed together with the bug in the
        # comment list.
        comments[0].text_for_display = ''
    return comments


def get_visible_comments(comments, user=None):
    """Return comments, filtering out empty or duplicated ones."""
    visible_comments = []
    previous_comment = None
    for comment in comments:
        # Omit comments that are identical to their previous
        # comment, which were probably produced by
        # double-submissions or user errors, and which don't add
        # anything useful to the bug itself.
        # Also omit comments with no body text or attachments to display.
        if (comment.isEmpty() or
            previous_comment and
            previous_comment.isIdenticalTo(comment)):
            continue

        visible_comments.append(comment)
        previous_comment = comment

    # These two lines are here to fill the ValidPersonOrTeamCache cache,
    # so that checking owner.is_valid_person, when rendering the link,
    # won't issue a DB query. Note that this should be obsolete now with
    # getMessagesForView improvements.
    commenters = set(comment.owner for comment in visible_comments)
    getUtility(IPersonSet).getValidPersons(commenters)

    # If a user is supplied, we can also strip out comments that the user
    # cannot see, because they have been marked invisible.
    strip_invisible = True
    if user is not None:
        role = PersonRoles(user)
        strip_invisible = not (role.in_admin or role.in_registry_experts)
    if strip_invisible:
        visible_comments = [c for c in visible_comments if c.visible]

    return visible_comments


def get_sortorder_from_request(request):
    """Get the sortorder from the request.

    >>> from canonical.launchpad.webapp.servers import LaunchpadTestRequest
    >>> get_sortorder_from_request(LaunchpadTestRequest(form={}))
    ['-importance']
    >>> get_sortorder_from_request(
    ...     LaunchpadTestRequest(form={'orderby': '-status'}))
    ['-status']
    >>> get_sortorder_from_request(LaunchpadTestRequest(
    ...     form={'orderby': 'status,-severity,importance'}))
    ['status', 'importance']
    >>> get_sortorder_from_request(
    ...     LaunchpadTestRequest(form={'orderby': 'priority,-severity'}))
    ['-importance']
    """
    order_by_string = request.get("orderby", '')
    if order_by_string:
        if not zope_isinstance(order_by_string, list):
            order_by = order_by_string.split(',')
        else:
            order_by = order_by_string
    else:
        order_by = []
    # Remove old order_by values that people might have in bookmarks.
    for old_order_by_column in ['priority', 'severity']:
        if old_order_by_column in order_by:
            order_by.remove(old_order_by_column)
        if '-' + old_order_by_column in order_by:
            order_by.remove('-' + old_order_by_column)
    if order_by:
        return order_by
    else:
        # No sort ordering specified, so use a reasonable default.
        return ["-importance"]


def get_default_search_params(user):
    """Return a BugTaskSearchParams instance with default values.

    By default, a search includes any bug that is unresolved and not a
    duplicate of another bug.

    If this search will be used to display a list of bugs to the user
    it may be a good idea to set the orderby attribute using
    get_sortorder_from_request():

      params = get_default_search_params(user)
      params.orderby = get_sortorder_from_request(request)

    """
    return BugTaskSearchParams(
        user=user, status=any(*UNRESOLVED_BUGTASK_STATUSES), omit_dupes=True)


OLD_BUGTASK_STATUS_MAP = {
    'Unconfirmed': 'New',
    'Needs Info': 'Incomplete',
    'Rejected': 'Invalid',
    }


def rewrite_old_bugtask_status_query_string(query_string):
    """Return a query string with old status names replaced with new.

    If an old status string has been used in the query, construct a
    corrected query string for the search, else return the original
    query string.
    """
    query_elements = cgi.parse_qsl(
        query_string, keep_blank_values=True, strict_parsing=False)
    query_elements_mapped = []

    for name, value in query_elements:
        if name == 'field.status:list':
            value = OLD_BUGTASK_STATUS_MAP.get(value, value)
        query_elements_mapped.append((name, value))

    if query_elements == query_elements_mapped:
        return query_string
    else:
        return urllib.urlencode(query_elements_mapped, doseq=True)


def target_has_expirable_bugs_listing(target):
    """Return True or False if the target has the expirable-bugs listing.

    The target must be a Distribution, DistroSeries, Product, or
    ProductSeries, and the pillar must have enabled bug expiration.
    """
    if IDistribution.providedBy(target) or IProduct.providedBy(target):
        return target.enable_bug_expiration
    elif IProductSeries.providedBy(target):
        return target.product.enable_bug_expiration
    elif IDistroSeries.providedBy(target):
        return target.distribution.enable_bug_expiration
    else:
        # This context is not a supported bugtarget.
        return False


class BugTargetTraversalMixin:
    """Mix-in in class that provides .../+bug/NNN traversal."""

    redirection('+bug', '+bugs')

    @stepthrough('+bug')
    def traverse_bug(self, name):
        """Traverses +bug portions of URLs"""
        return self._get_task_for_context(name)

    def _get_task_for_context(self, name):
        """Return the IBugTask for this name in this context.

        If the bug has been reported, but not in this specific context, a
        redirect to the default context will be returned.

        Returns None if no bug with the given name is found, or the
        bug is not accessible to the current user.
        """
        context = self.context

        # Raises NotFoundError if no bug is found
        bug = getUtility(IBugSet).getByNameOrID(name)

        # Get out now if the user cannot view the bug. Continuing may
        # reveal information about its context
        if not check_permission('launchpad.View', bug):
            return None

        # Loop through this bug's tasks to try and find the appropriate task
        # for this context. We always want to return a task, whether or not
        # the user has the permission to see it so that, for example, an
        # anonymous user is presented with a login screen at the correct URL,
        # rather than making it look as though this task was "not found",
        # because it was filtered out by privacy-aware code.
        for bugtask in bug.bugtasks:
            if bugtask.target == context:
                # Security proxy this object on the way out.
                return getUtility(IBugTaskSet).get(bugtask.id)

        # If we've come this far, there's no task for the requested
        # context. Redirect to one that exists.
        return self.redirectSubTree(canonical_url(bug.default_bugtask))


class BugTaskNavigation(Navigation):
    """Navigation for the `IBugTask`."""
    usedfor = IBugTask

    @stepthrough('attachments')
    def traverse_attachments(self, name):
        """traverse to an attachment by id."""
        if name.isdigit():
            attachment = getUtility(IBugAttachmentSet)[name]
            if attachment is not None and attachment.bug == self.context.bug:
                return self.redirectSubTree(
                    canonical_url(attachment), status=301)

    @stepthrough('+attachment')
    def traverse_attachment(self, name):
        """traverse to an attachment by id."""
        if name.isdigit():
            attachment = getUtility(IBugAttachmentSet)[name]
            if attachment is not None and attachment.bug == self.context.bug:
                return attachment

    @stepthrough('comments')
    def traverse_comments(self, name):
        """Traverse to a comment by id."""
        if not name.isdigit():
            return None
        index = int(name)
        comments = get_comments_for_bugtask(self.context)
        # I couldn't find a way of using index to restrict the queries
        # in get_comments_for_bugtask in a way that wasn't horrible, and
        # it wouldn't really save us a lot in terms of database time, so
        # I have chosed to use this simple solution for now.
        #   -- kiko, 2006-07-11
        try:
            comment = comments[index]
            if (comment.visible
                or check_permission('launchpad.Admin', self.context)):
                return comment
            else:
                return None
        except IndexError:
            return None

    @stepthrough('nominations')
    def traverse_nominations(self, nomination_id):
        """Traverse to a nomination by id."""
        if not nomination_id.isdigit():
            return None
        return getUtility(IBugNominationSet).get(nomination_id)

    redirection('references', '..')


class BugTaskSetNavigation(GetitemNavigation):
    """Navigation for the `IbugTaskSet`."""
    usedfor = IBugTaskSet


class BugTaskContextMenu(BugContextMenu):
    """Context menu of actions that can be performed upon an `IBugTask`."""
    usedfor = IBugTask


class BugTaskTextView(LaunchpadView):
    """View for a simple text page displaying information about a bug task."""

    def render(self):
        """Return a text representation of the parent bug."""
        view = BugTextView(self.context.bug, self.request)
        view.initialize()
        return view.render()


class BugTaskView(LaunchpadView, BugViewMixin, FeedsMixin):
    """View class for presenting information about an `IBugTask`."""

    override_title_breadcrumbs = True

    def __init__(self, context, request):
        LaunchpadView.__init__(self, context, request)

        self.notices = []

        # Make sure we always have the current bugtask.
        if not IBugTask.providedBy(context):
            self.context = getUtility(ILaunchBag).bugtask
        else:
            self.context = context
        list(getUtility(IPersonSet).getPrecachedPersonsFromIDs(
            [self.context.bug.ownerID], need_validity=True))

    @property
    def page_title(self):
        heading = 'Bug #%s in %s' % (
            self.context.bug.id, self.context.bugtargetdisplayname)
        title = FormattersAPI(self.context.bug.title).obfuscate_email()
        return smartquote('%s: "%s"') % (heading, title)

    @property
    def next_url(self):
        """Provided so returning to the page they came from works."""
        referer = self.request.getHeader('referer')

        # XXX bdmurray 2010-09-30 bug=98437: work around zope's test
        # browser setting referer to localhost.
        if referer and referer != 'localhost':
            next_url = referer
        else:
            next_url = canonical_url(self.context)
        return next_url

    @property
    def cancel_url(self):
        """Provided so returning to the page they came from works."""
        referer = self.request.getHeader('referer')

        # XXX bdmurray 2010-09-30 bug=98437: work around zope's test
        # browser setting referer to localhost.
        if referer and referer != 'localhost':
            cancel_url = referer
        else:
            cancel_url = canonical_url(self.context)
        return cancel_url

    def initialize(self):
        """Set up the needed widgets."""
        bug = self.context.bug
        IJSONRequestCache(self.request).objects['bug'] = bug

        # See render() for how this flag is used.
        self._redirecting_to_bug_list = False

        self.bug_title_edit_widget = TextLineEditorWidget(
            bug, IBug['title'], "Edit this summary", 'h1',
            edit_url=canonical_url(self.context, view_name='+edit'))

        # XXX 2010-10-05 gmb bug=655597:
        # This line of code keeps the view's query count down,
        # possibly using witchcraft. It should be rewritten to be
        # useful or removed in favour of making other queries more
        # efficient. The witchcraft is because the subscribers are accessed
        # in the initial page load, so the data is actually used.
        if self.user is not None:
            list(bug.getSubscribersForPerson(self.user))

    def userIsSubscribed(self):
        """Is the user subscribed to this bug?"""
        return (
            self.context.bug.isSubscribed(self.user) or
            self.context.bug.isSubscribedToDupes(self.user))

    def render(self):
        """Render the bug list if the user has permission to see the bug."""
        # Prevent normal rendering when redirecting to the bug list
        # after unsubscribing from a private bug, because rendering the
        # bug page would raise Unauthorized errors!
        if self._redirecting_to_bug_list:
            return u''
        else:
            return LaunchpadView.render(self)

    def _nominateBug(self, series):
        """Nominate the bug for the series and redirect to the bug page."""
        self.context.bug.addNomination(self.user, series)
        self.request.response.addInfoNotification(
            'This bug has been nominated to be fixed in %s.' %
                series.bugtargetdisplayname)
        self.request.response.redirect(canonical_url(self.context))

    @cachedproperty
    def comments(self):
        """Return the bugtask's comments."""
        show_spam_controls = check_permission(
            'launchpad.Admin', self.context.bug)
        return get_comments_for_bugtask(self.context, truncate=True,
            for_display=True, show_spam_controls=show_spam_controls)

    @cachedproperty
    def interesting_activity(self):
        """A sequence of interesting bug activity."""
        bug_change_re = (
            'affects|description|security vulnerability|'
            'summary|tags|visibility')
        bugtask_change_re = (
            '[a-z0-9][a-z0-9\+\.\-]+( \([A-Za-z0-9\s]+\))?: '
            '(assignee|importance|milestone|status)')
        interesting_match = re.compile(
            "^(%s|%s)$" % (bug_change_re, bugtask_change_re)).match
        return tuple(
            BugActivityItem(activity)
            for activity in self.context.bug.activity
            if interesting_match(activity.whatchanged) is not None)

    @cachedproperty
    def activity_and_comments(self):
        """Build list of comments interleaved with activities

        When activities occur on the same day a comment was posted,
        encapsulate them with that comment.  For the remainder, group
        then as if owned by the person who posted the first action
        that day.

        If the number of comments exceeds the configured maximum limit, the
        list will be truncated to just the first and last sets of comments.

        The division between the most recent and oldest is marked by an entry
        in the list with the key 'num_hidden' defined.
        """
        # Ensure truncation results in < max_length comments as expected
        assert(config.malone.comments_list_truncate_oldest_to
               + config.malone.comments_list_truncate_newest_to
               < config.malone.comments_list_max_length)

        if not self.visible_comments_truncated_for_display:
            comments = self.comments
        else:
            # the comment function takes 0-offset counts where comment 0 is
            # the initial description, so we need to add one to the limits
            # to adjust.
            oldest_count = 1 + self.visible_initial_comments
            new_count = 1 + self.total_comments - self.visible_recent_comments
            show_spam_controls = check_permission(
                'launchpad.Admin', self.context.bug)
            comments = get_comments_for_bugtask(
                self.context, truncate=True, for_display=True,
                slice_info=[
                    slice(None, oldest_count), slice(new_count, None)],
                show_spam_controls=show_spam_controls)

        visible_comments = get_visible_comments(
            comments, user=self.user)

        event_groups = group_comments_with_activity(
            comments=visible_comments,
            activities=self.interesting_activity)

        def group_activities_by_target(activities):
            activities = sorted(
                activities, key=attrgetter(
                    "datechanged", "target", "attribute"))
            return [
                {"target": target, "activity": list(activity)}
                for target, activity in groupby(
                    activities, attrgetter("target"))]

        def comment_event_dict(comment):
            actors = set(activity.person for activity in comment.activity)
            actors.add(comment.owner)
            assert len(actors) == 1, actors
            dates = set(activity.datechanged for activity in comment.activity)
            dates.add(comment.datecreated)
            comment.activity = group_activities_by_target(comment.activity)
            return {
                "comment": comment,
                "date": min(dates),
                "person": actors.pop(),
                }

        def activity_event_dict(activities):
            actors = set(activity.person for activity in activities)
            assert len(actors) == 1, actors
            dates = set(activity.datechanged for activity in activities)
            return {
                "activity": group_activities_by_target(activities),
                "date": min(dates),
                "person": actors.pop(),
                }

        def event_dict(event_group):
            if isinstance(event_group, list):
                return activity_event_dict(event_group)
            else:
                return comment_event_dict(event_group)

        events = map(event_dict, event_groups)

        # Insert blanks if we're showing only a subset of the comment list.
        if self.visible_comments_truncated_for_display:
            # Find the oldest recent comment in the event list.
            index = 0
            prev_comment = None
            while index < len(events):
                event = events[index]
                comment = event.get("comment")
                if prev_comment is None:
                    prev_comment = comment
                    index += 1
                    continue
                if comment is None:
                    index += 1
                    continue
                if prev_comment.index + 1 != comment.index:
                    # There is a gap here, record it.
                    separator = {
                        'date': prev_comment.datecreated,
                        'num_hidden': comment.index - prev_comment.index,
                        }
                    events.insert(index, separator)
                    index += 1
                prev_comment = comment
                index += 1
        return events

    @property
    def visible_initial_comments(self):
        """How many initial comments are being shown."""
        return config.malone.comments_list_truncate_oldest_to

    @property
    def visible_recent_comments(self):
        """How many recent comments are being shown."""
        return config.malone.comments_list_truncate_newest_to

    @cachedproperty
    def visible_comments_truncated_for_display(self):
        """Whether the visible comment list is truncated for display."""
        show_all = (self.request.form_ng.getOne('comments') == 'all')
        if show_all:
            return False
        max_comments = config.malone.comments_list_max_length
        return self.total_comments > max_comments

    @cachedproperty
    def total_comments(self):
        """We count all comments because the db cannot do visibility yet."""
        return self.context.bug.bug_messages.count() - 1

    def wasDescriptionModified(self):
        """Return a boolean indicating whether the description was modified"""
        return (self.context.bug._indexed_messages(
            include_content=True, include_parents=False)[0].text_contents !=
            self.context.bug.description)

    @cachedproperty
    def linked_branches(self):
        """Filter out the bug_branch links to non-visible private branches."""
        linked_branches = []
        for linked_branch in self.context.bug.linked_branches:
            if check_permission('launchpad.View', linked_branch.branch):
                linked_branches.append(linked_branch)
        return linked_branches

    @property
    def days_to_expiration(self):
        """Return the number of days before the bug is expired, or None."""
        if not self.context.bug.isExpirable(days_old=0):
            return None

        expire_after = timedelta(days=config.malone.days_before_expiration)
        expiration_date = self.context.bug.date_last_updated + expire_after
        remaining_time = expiration_date - datetime.now(utc)
        return remaining_time.days

    @property
    def expiration_message(self):
        """Return a message indicating the time to expiration for the bug.

        If the expiration date of the bug has already passed, the
        message returned will indicate this. This deals with situations
        where a bug is due to be marked invalid but has not yet been
        dealt with by the bug expiration script.

        If the bug is not due to be expired None will be returned.
        """
        if not self.context.bug.isExpirable(days_old=0):
            return None

        days_to_expiration = self.days_to_expiration
        if days_to_expiration <= 0:
            # We should always display a positive number to the user,
            # whether we're talking about the past or the future.
            days_to_expiration = -days_to_expiration
            message = ("This bug report was marked for expiration %i days "
                "ago.")
        else:
            message = ("This bug report will be marked for expiration in %i "
                "days if no further activity occurs.")

        return message % days_to_expiration

    @property
    def official_tags(self):
        """The list of official tags for this bug."""
        target_official_tags = set(self.context.bug.official_tags)
        return [tag for tag in self.context.bug.tags
                if tag in target_official_tags]

    @property
    def unofficial_tags(self):
        """The list of unofficial tags for this bug."""
        target_official_tags = set(self.context.bug.official_tags)
        return [tag for tag in self.context.bug.tags
                if tag not in target_official_tags]

    @property
    def available_official_tags_js(self):
        """Return the list of available official tags for the bug as JSON.

        The list comprises of the official tags for all targets for which the
        bug has a task. It is returned as Javascript snippet, to be embedded
        in the bug page.
        """
        # Unwrap the security proxy. - official_tags is a security proxy
        # wrapped list.
        available_tags = list(self.context.bug.official_tags)
        return 'var available_official_tags = %s;' % dumps(available_tags)

    @property
    def user_is_admin(self):
        """Is the user a Launchpad admin?"""
        return check_permission('launchpad.Admin', self.context)

    @property
    def bug_description_html(self):
        """The bug's description as HTML."""
        bug = self.context.bug
        description = IBug['description']
        title = "Bug Description"
        edit_url = canonical_url(self.context, view_name='+edit')
        return TextAreaEditorWidget(
            bug, description, title, edit_url=edit_url)

    @property
    def bug_heat_html(self):
        """HTML representation of the bug heat."""
        if IDistributionSourcePackage.providedBy(self.context.target):
            return bugtask_heat_html(
                self.context, target=self.context.distribution)
        else:
            return bugtask_heat_html(self.context)

    @property
    def privacy_notice_classes(self):
        if not self.context.bug.private:
            return 'hidden'
        else:
            return ''


def calculate_heat_display(heat, max_bug_heat):
    """Calculate the number of heat 'flames' to display."""
    heat = float(heat)
    max_bug_heat = float(max_bug_heat)
    if max_bug_heat == 0:
        return 0
    if heat / max_bug_heat < 0.33333:
        return 0
    if heat / max_bug_heat < 0.66666 or max_bug_heat < 2:
        return int(floor((heat / max_bug_heat) * 4))
    else:
        heat_index = int(floor((log(heat) / log(max_bug_heat)) * 4))
        # ensure that we never return a value > 4, even if
        # max_bug_heat is outdated.
        return min(heat_index, 4)


def bugtask_heat_html(bugtask, target=None):
    """Render the HTML representing bug heat for a given bugask."""
    if target is None:
        target = bugtask.target
    max_bug_heat = target.max_bug_heat
    if max_bug_heat is None:
        max_bug_heat = 5000
    heat_ratio = calculate_heat_display(bugtask.bug.heat, max_bug_heat)
    html = (
        '<span><a href="/+help/bug-heat.html" target="help" class="icon"><img'
        ' src="/@@/bug-heat-%(ratio)i.png" '
        'alt="%(ratio)i out of 4 heat flames" title="Heat: %(heat)i" /></a>'
        '</span>'
        % {'ratio': heat_ratio, 'heat': bugtask.bug.heat})
    return html


class BugTaskPortletView:
    """A portlet for displaying a bug's bugtasks."""

    def alsoReportedIn(self):
        """Return a list of IUpstreamBugTasks in which this bug is reported.

        If self.context is an IUpstreamBugTasks, it will be excluded
        from this list.
        """
        return [
            task for task in self.context.bug.bugtasks
            if task.id is not self.context.id]


def get_prefix(bugtask):
    """Return a prefix that can be used for this form.

    The prefix is constructed using the name of the bugtask's target so as
    to ensure that it's unique within the context of a bug. This is needed
    in order to included multiple edit forms on the bug page, while still
    keeping the field ids unique.
    """
    parts = []
    parts.append(bugtask.pillar.name)

    series = bugtask.productseries or bugtask.distroseries
    if series:
        parts.append(series.name)

    if bugtask.sourcepackagename is not None:
        parts.append(bugtask.sourcepackagename.name)

    return '_'.join(parts)


def get_assignee_vocabulary(context):
    """The vocabulary of bug task assignees the current user can set."""
    if context.userCanSetAnyAssignee(getUtility(ILaunchBag).user):
        return 'ValidAssignee'
    else:
        return 'AllUserTeamsParticipation'


class BugTaskBugWatchMixin:
    """A mixin to be used where a BugTask view displays BugWatch data."""

    @property
    def bug_watch_error_message(self):
        """Return a browser-useable error message for a bug watch."""
        if not self.context.bugwatch:
            return None

        bug_watch = self.context.bugwatch
        if not bug_watch.last_error_type:
            return None

        error_message_mapping = {
            BugWatchActivityStatus.BUG_NOT_FOUND: "%(bugtracker)s bug #"
                "%(bug)s appears not to exist. Check that the bug "
                "number is correct.",
            BugWatchActivityStatus.CONNECTION_ERROR: "Launchpad couldn't "
                "connect to %(bugtracker)s.",
            BugWatchActivityStatus.INVALID_BUG_ID: "Bug ID %(bug)s isn't "
                "valid on %(bugtracker)s. Check that the bug ID is "
                "correct.",
            BugWatchActivityStatus.TIMEOUT: "Launchpad's connection to "
                "%(bugtracker)s timed out.",
            BugWatchActivityStatus.UNKNOWN: "Launchpad couldn't import bug "
                "#%(bug)s from " "%(bugtracker)s.",
            BugWatchActivityStatus.UNPARSABLE_BUG: "Launchpad couldn't "
                "extract a status from %(bug)s on %(bugtracker)s.",
            BugWatchActivityStatus.UNPARSABLE_BUG_TRACKER: "Launchpad "
                "couldn't determine the version of %(bugtrackertype)s "
                "running on %(bugtracker)s.",
            BugWatchActivityStatus.UNSUPPORTED_BUG_TRACKER: "Launchpad "
                "doesn't support importing bugs from %(bugtrackertype)s"
                " bug trackers.",
            BugWatchActivityStatus.PRIVATE_REMOTE_BUG: "The bug is marked as "
                "private on the remote bug tracker. Launchpad cannot import "
                "the status of private remote bugs.",
            }

        if bug_watch.last_error_type in error_message_mapping:
            message = error_message_mapping[bug_watch.last_error_type]
        else:
            message = bug_watch.last_error_type.description

        error_data = {
            'bug': bug_watch.remotebug,
            'bugtracker': bug_watch.bugtracker.title,
            'bugtrackertype': bug_watch.bugtracker.bugtrackertype.title}

        return {
            'message': message % error_data,
            'help_url': '%s#%s' % (
                canonical_url(bug_watch, view_name="+error-help"),
                bug_watch.last_error_type.name),
            }


class BugTaskEditView(LaunchpadEditFormView, BugTaskBugWatchMixin):
    """The view class used for the task +editstatus page."""

    schema = IBugTask
    milestone_source = None
    user_is_subscribed = None
    edit_form = ViewPageTemplateFile('../templates/bugtask-edit-form.pt')

    # The field names that we use by default. This list will be mutated
    # depending on the current context and the permissions of the user viewing
    # the form.
    default_field_names = ['assignee', 'bugwatch', 'importance', 'milestone',
                           'status', 'statusexplanation']
    custom_widget('target', LaunchpadTargetWidget)
    custom_widget('bugwatch', BugTaskBugWatchWidget)
    custom_widget('assignee', BugTaskAssigneeWidget)

    def initialize(self):
        # Initialize user_is_subscribed, if it hasn't already been set.
        if self.user_is_subscribed is None:
            self.user_is_subscribed = self.context.bug.isSubscribed(self.user)
        super(BugTaskEditView, self).initialize()

    page_title = 'Edit status'

    @property
    def show_target_widget(self):
        # Only non-series tasks can be retargetted.
        return not ISeriesBugTarget.providedBy(self.context.target)

    @cachedproperty
    def field_names(self):
        """Return the field names that can be edited by the user."""
        field_names = set(self.default_field_names)

        # The fields that we present to the users change based upon the
        # current context and the user's permissions, so we update field_names
        # with any fields that may need to be added.
        field_names.update(self.editable_field_names)

        # To help with caching, return an immutable object.
        return frozenset(field_names)

    @cachedproperty
    def editable_field_names(self):
        """Return the names of fields the user has permission to edit."""

        if self.context.target_uses_malone:
            # Don't edit self.field_names directly, because it's shared by all
            # BugTaskEditView instances.
            editable_field_names = set(self.default_field_names)
            editable_field_names.discard('bugwatch')

            # XXX: Brad Bollenbach 2006-09-29 bug=63000: Permission checking
            # doesn't belong here!
            if ('milestone' in editable_field_names and
                not self.userCanEditMilestone()):
                editable_field_names.remove("milestone")

            if ('importance' in editable_field_names and
                not self.userCanEditImportance()):
                editable_field_names.remove("importance")
        else:
            editable_field_names = set(('bugwatch', ))
            if self.context.bugwatch is None:
                editable_field_names.update(('status', 'assignee'))
                if ('importance' in self.default_field_names
                    and self.userCanEditImportance()):
                    editable_field_names.add('importance')
            else:
                bugtracker = self.context.bugwatch.bugtracker
                if bugtracker.bugtrackertype == BugTrackerType.EMAILADDRESS:
                    editable_field_names.add('status')
                    if ('importance' in self.default_field_names
                        and self.userCanEditImportance()):
                        editable_field_names.add('importance')

        if self.show_target_widget:
            editable_field_names.add('target')

        # To help with caching, return an immutable object.
        return frozenset(editable_field_names)

    @property
    def is_question(self):
        """Return True or False if this bug was converted into a question.

        Bugtasks cannot be edited if the bug was converted into a question.
        """
        return self.context.bug.getQuestionCreatedFromBug() is not None

    @property
    def next_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    @property
    def initial_values(self):
        """See `LaunchpadFormView.`"""
        field_values = {}
        for name in self.field_names:
            field_values[name] = getattr(self.context, name)

        return field_values

    @property
    def prefix(self):
        """Return a prefix that can be used for this form.

        The prefix is constructed using the name of the bugtask's target so as
        to ensure that it's unique within the context of a bug. This is needed
        in order to included multiple edit forms on the bug page, while still
        keeping the field ids unique.
        """
        return get_prefix(self.context)

    def setUpFields(self):
        """Sets up the fields for the bug task edit form.

        See `LaunchpadFormView`.
        """
        super(BugTaskEditView, self).setUpFields()
        read_only_field_names = self._getReadOnlyFieldNames()

        if 'target' in self.editable_field_names:
            self.form_fields = self.form_fields.omit('target')
            target_field = copy_field(IBugTask['target'], readonly=False)
            self.form_fields += formlib.form.Fields(target_field)

        # The status field is a special case because we alter the vocabulary
        # it uses based on the permissions of the user viewing form.
        if 'status' in self.editable_field_names:
            if self.user is None:
                status_noshow = set(BugTaskStatus.items)
            else:
                status_noshow = set((
                    BugTaskStatus.UNKNOWN, BugTaskStatus.EXPIRED))
                status_noshow.update(
                    status for status in BugTaskStatus.items
                    if not self.context.canTransitionToStatus(
                        status, self.user))

            if self.context.status in status_noshow:
                # The user has to be able to see the current value.
                status_noshow.remove(self.context.status)

            # We shouldn't have to build our vocabulary out of (item.title,
            # item) tuples -- iterating over an EnumeratedType gives us
            # ITokenizedTerms that we could use. However, the terms generated
            # by EnumeratedType have their name as the token and here we need
            # the title as the token for backwards compatibility.
            status_items = [
                (item.title, item) for item in BugTaskStatus.items
                if item not in status_noshow]
            status_field = Choice(
                __name__='status', title=self.schema['status'].title,
                vocabulary=SimpleVocabulary.fromItems(status_items))

            self.form_fields = self.form_fields.omit('status')
            self.form_fields += formlib.form.Fields(status_field)

        # If we have a milestone vocabulary already, create a new field
        # to use it, instead of creating a new one.
        if self.milestone_source is not None:
            milestone_source = self.milestone_source
            milestone_field = Choice(
                __name__='milestone',
                title=self.schema['milestone'].title,
                source=milestone_source, required=False)
        else:
            milestone_field = copy_field(
                IBugTask['milestone'], readonly=False)

        self.form_fields = self.form_fields.omit('milestone')
        self.form_fields += formlib.form.Fields(milestone_field)

        for field in read_only_field_names:
            self.form_fields[field].for_display = True

        # In cases where the status or importance fields are read only we give
        # them a custom widget so that they are rendered correctly.
        for field in ['status', 'importance']:
            if field in read_only_field_names:
                self.form_fields[field].custom_widget = CustomWidgetFactory(
                    DBItemDisplayWidget)

        if 'importance' not in read_only_field_names:
            # Users shouldn't be able to set a bugtask's importance to
            # `UNKNOWN`, only bug watches do that.
            importance_vocab_items = [
                item for item in BugTaskImportance.items.items
                if item != BugTaskImportance.UNKNOWN]
            self.form_fields = self.form_fields.omit('importance')
            self.form_fields += formlib.form.Fields(
                Choice(__name__='importance',
                       title=_('Importance'),
                       values=importance_vocab_items,
                       default=BugTaskImportance.UNDECIDED))

        if self.context.target_uses_malone:
            self.form_fields = self.form_fields.omit('bugwatch')

        elif (self.context.bugwatch is not None and
            self.form_fields.get('assignee', False)):
            self.form_fields['assignee'].custom_widget = CustomWidgetFactory(
                AssigneeDisplayWidget)

        if (self.context.bugwatch is None and
            self.form_fields.get('assignee', False)):
            # Make the assignee field editable
            self.form_fields = self.form_fields.omit('assignee')
            self.form_fields += formlib.form.Fields(PersonChoice(
                __name__='assignee', title=_('Assigned to'), required=False,
                vocabulary=get_assignee_vocabulary(self.context),
                readonly=False))
            self.form_fields['assignee'].custom_widget = CustomWidgetFactory(
                BugTaskAssigneeWidget)

    def _getReadOnlyFieldNames(self):
        """Return the names of fields that will be rendered read only."""
        if self.context.target_uses_malone:
            read_only_field_names = []

            if not self.userCanEditMilestone():
                read_only_field_names.append("milestone")

            if not self.userCanEditImportance():
                read_only_field_names.append("importance")
        else:
            editable_field_names = self.editable_field_names
            read_only_field_names = [
                field_name for field_name in self.field_names
                if field_name not in editable_field_names]

        return read_only_field_names

    def userCanEditMilestone(self):
        """Can the user edit the Milestone field?

        If yes, return True, otherwise return False.
        """
        return self.context.userCanEditMilestone(self.user)

    def userCanEditImportance(self):
        """Can the user edit the Importance field?

        If yes, return True, otherwise return False.
        """
        return self.context.userCanEditImportance(self.user)

    def validate(self, data):
        new_target = data.get('target')
        if new_target and new_target != self.context.target:
            try:
                self.context.validateTransitionToTarget(new_target)
            except IllegalTarget as e:
                self.setFieldError('target', e[0])

    def updateContextFromData(self, data, context=None):
        """Updates the context object using the submitted form data.

        This method overrides that of LaunchpadEditFormView because of the
        fairly involved thread of logic behind updating some BugTask
        attributes, in particular the status, assignee and bugwatch fields.
        """
        if context is None:
            context = self.context
        bugtask = context

        if self.request.form.get('subscribe', False):
            bugtask.bug.subscribe(self.user, self.user)
            self.request.response.addNotification(
                "You have subscribed to this bug report.")

        # Save the field names we extract from the form in a separate
        # list, because we modify this list of names later if the
        # bugtask is reassigned to a different product.
        field_names = data.keys()
        new_values = data.copy()
        data_to_apply = data.copy()

        bugtask_before_modification = Snapshot(
            bugtask, providing=providedBy(bugtask))

        # If the user is reassigning an upstream task to a different
        # product, we'll clear out the milestone value, to avoid
        # violating DB constraints that ensure an upstream task can't
        # be assigned to a milestone on a different product.
        # This is also done by transitionToTarget, but do it here so we
        # can display notifications and remove the milestone from the
        # submitted data.
        milestone_cleared = None
        milestone_ignored = False
        missing = object()
        new_target = new_values.pop("target", missing)
        if new_target is not missing and bugtask.target != new_target:
            # We clear the milestone value if one was already set. We ignore
            # the milestone value if it was currently None, and the user tried
            # to set a milestone value while also changing the product. This
            # allows us to provide slightly clearer feedback messages.
            if bugtask.milestone:
                milestone_cleared = bugtask.milestone
            elif new_values.get('milestone') is not None:
                milestone_ignored = True

            # Regardless of the user's permission, the milestone
            # must be cleared because the milestone is unique to a product.
            removeSecurityProxy(bugtask).milestone = None
            # Remove the "milestone" field from the list of fields
            # whose changes we want to apply, because we don't want
            # the form machinery to try and set this value back to
            # what it was!
            data_to_apply.pop('milestone', None)

        # We special case setting target, status and assignee, because
        # there's a workflow associated with changes to these fields.
        for manual_field in ('target', 'status', 'assignee'):
            data_to_apply.pop(manual_field, None)

        # We grab the comment_on_change field before we update bugtask so as
        # to avoid problems accessing the field if the user has changed the
        # product of the BugTask.
        comment_on_change = self.request.form.get(
            "%s.comment_on_change" % self.prefix)

        changed = formlib.form.applyChanges(
            bugtask, self.form_fields, data_to_apply, self.adapters)

        # Set the "changed" flag properly, just in case status and/or assignee
        # happen to be the only values that changed. We explicitly verify that
        # we got a new status and/or assignee, because the form is not always
        # guaranteed to pass all the values. For example: bugtasks linked to a
        # bug watch don't allow editing the form, and the value is missing
        # from the form.
        if new_target is not missing and bugtask.target != new_target:
            changed = True
            bugtask.transitionToTarget(new_target)

        # Now that we've updated the bugtask we can add messages about
        # milestone changes, if there were any.
        if milestone_cleared:
            self.request.response.addWarningNotification(
                "The %s milestone setting has been removed because "
                "you reassigned the bug to %s." % (
                    milestone_cleared.displayname,
                    bugtask.bugtargetdisplayname))
        elif milestone_ignored:
            self.request.response.addWarningNotification(
                "The milestone setting was ignored because "
                "you reassigned the bug to %s." %
                bugtask.bugtargetdisplayname)

        if comment_on_change:
            bugtask.bug.newMessage(
                owner=getUtility(ILaunchBag).user,
                subject=bugtask.bug.followup_subject(),
                content=comment_on_change)

        new_status = new_values.pop("status", missing)
        new_assignee = new_values.pop("assignee", missing)
        if new_status is not missing and bugtask.status != new_status:
            changed = True
            try:
                bugtask.transitionToStatus(new_status, self.user)
            except UserCannotEditBugTaskStatus:
                # We need to roll back the transaction at this point,
                # since other changes may have been made.
                transaction.abort()
                self.setFieldError(
                    'status',
                    "Only the Bug Supervisor for %s can set the bug's "
                    "status to %s" %
                    (bugtask.target.displayname, new_status.title))
                return

        if new_assignee is not missing and bugtask.assignee != new_assignee:
            if new_assignee is not None and new_assignee != self.user:
                is_contributor = new_assignee.isBugContributorInTarget(
                    user=self.user, target=bugtask.pillar)
                if not is_contributor:
                    # If we have a new assignee who isn't a bug
                    # contributor in this pillar, we display a warning
                    # to the user, in case they made a mistake.
                    self.request.response.addWarningNotification(
                        structured(
                        """<a href="%s">%s</a>
                        did not previously have any assigned bugs in
                        <a href="%s">%s</a>.
                        <br /><br />
                        If this bug was assigned by mistake,
                        you may <a href="%s/+editstatus"
                        >change the assignment</a>.""",
                        canonical_url(new_assignee),
                        new_assignee.displayname,
                        canonical_url(bugtask.pillar),
                        bugtask.pillar.title,
                        canonical_url(bugtask)))
            changed = True
            bugtask.transitionToAssignee(new_assignee)

        if bugtask_before_modification.bugwatch != bugtask.bugwatch:
            bug_importer = getUtility(ILaunchpadCelebrities).bug_importer
            if bugtask.bugwatch is None:
                # Reset the status and importance to the default values,
                # since Unknown isn't selectable in the UI.
                bugtask.transitionToStatus(
                    IBugTask['status'].default, bug_importer)
                bugtask.transitionToImportance(
                    IBugTask['importance'].default, bug_importer)
            else:
                #XXX: Bjorn Tillenius 2006-03-01:
                #     Reset the bug task's status information. The right
                #     thing would be to convert the bug watch's status to a
                #     Launchpad status, but it's not trivial to do at the
                #     moment. I will fix this later.
                bugtask.transitionToStatus(
                    BugTaskStatus.UNKNOWN,
                    bug_importer)
                bugtask.transitionToImportance(
                    BugTaskImportance.UNKNOWN,
                    bug_importer)
                bugtask.transitionToAssignee(None)

        if changed:
            # We only set the statusexplanation field to the value of the
            # change comment if the BugTask has actually been changed in some
            # way. Otherwise, we just leave it as a comment on the bug.
            if comment_on_change:
                bugtask.statusexplanation = comment_on_change
            else:
                bugtask.statusexplanation = ""

            notify(
                ObjectModifiedEvent(
                    object=bugtask,
                    object_before_modification=bugtask_before_modification,
                    edited_fields=field_names))

        if bugtask.sourcepackagename and self.widgets.get('target'):
            real_package_name = bugtask.sourcepackagename.name

            # We get entered_package_name directly from the form here, since
            # validating the sourcepackagename field mutates its value in to
            # the one already in real_package_name, which makes our comparison
            # of the two below useless.
            entered_package_name = self.request.form.get(
                self.widgets['target'].package_widget.name)

            if real_package_name != entered_package_name:
                # The user entered a binary package name which got
                # mapped to a source package.
                self.request.response.addNotification(
                    "'%(entered_package)s' is a binary package. This bug has"
                    " been assigned to its source package '%(real_package)s'"
                    " instead." %
                    {'entered_package': entered_package_name,
                     'real_package': real_package_name})

    @action('Save Changes', name='save')
    def save_action(self, action, data):
        """Update the bugtask with the form data."""
        self.updateContextFromData(data)


class BugTaskStatusView(LaunchpadView):
    """Viewing the status of a bug task."""

    page_title = 'View status'

    def initialize(self):
        """Set up the appropriate widgets.

        Different widgets are shown depending on if it's a remote bug
        task or not.
        """
        field_names = [
            'status', 'importance', 'assignee', 'statusexplanation']
        if not self.context.target_uses_malone:
            field_names += ['bugwatch']
            self.milestone_widget = None
        else:
            field_names += ['milestone']
            self.bugwatch_widget = None

        if self.context.distroseries or self.context.distribution:
            field_names += ['sourcepackagename']

        self.assignee_widget = CustomWidgetFactory(AssigneeDisplayWidget)
        self.status_widget = CustomWidgetFactory(DBItemDisplayWidget)
        self.importance_widget = CustomWidgetFactory(DBItemDisplayWidget)

        setUpWidgets(self, IBugTask, IDisplayWidget, names=field_names)


class BugTaskListingView(LaunchpadView):
    """A view designed for displaying bug tasks in lists."""
    # Note that this right now is only used in tests and to render
    # status in the CVEReportView. It may be a candidate for refactoring
    # or removal.
    @property
    def status(self):
        """Return an HTML representation of the bugtask status.

        The assignee is included.
        """
        bugtask = self.context
        assignee = bugtask.assignee
        status = bugtask.status
        status_title = status.title.capitalize()

        if not assignee:
            return status_title + ' (unassigned)'
        assignee_html = PersonFormatterAPI(assignee).link('+assignedbugs')

        if status in (BugTaskStatus.INVALID,
                      BugTaskStatus.FIXCOMMITTED):
            return '%s by %s' % (status_title, assignee_html)
        else:
            return '%s, assigned to %s' % (status_title, assignee_html)

    @property
    def status_elsewhere(self):
        """Return human-readable representation of the status of this bug
        in other contexts for which it's reported.
        """
        bugtask = self.context
        related_tasks = bugtask.related_tasks
        if not related_tasks:
            return "not filed elsewhere"

        fixes_found = len(
            [task for task in related_tasks
             if task.status in (BugTaskStatus.FIXCOMMITTED,
                                BugTaskStatus.FIXRELEASED)])
        if fixes_found:
            return "fixed in %d of %d places" % (
                fixes_found, len(bugtask.bug.bugtasks))
        elif len(related_tasks) == 1:
            return "filed in 1 other place"
        else:
            return "filed in %d other places" % len(related_tasks)

    def render(self):
        """Make rendering this template-less view not crash."""
        return u""


class BugsInfoMixin:
    """Contains properties giving URLs to bug information."""

    @property
    def bugs_fixed_elsewhere_url(self):
        """A URL to a list of bugs fixed elsewhere."""
        return "%s?field.status_upstream=resolved_upstream" % (
            canonical_url(self.context, view_name='+bugs'))

    @property
    def open_cve_bugs_url(self):
        """A URL to a list of open bugs linked to CVEs."""
        return "%s?field.has_cve=on" % (
            canonical_url(self.context, view_name='+bugs'))

    @property
    def open_cve_bugs_has_report(self):
        """Whether or not the context has a CVE report page."""
        return queryMultiAdapter(
            (self.context, self.request), name='+cve') is not None

    @property
    def pending_bugwatches_url(self):
        """A URL to a list of bugs that need a bugwatch.

        None is returned if the context is not an upstream product.
        """
        if not IProduct.providedBy(self.context):
            return None
        if self.context.bug_tracking_usage == ServiceUsage.LAUNCHPAD:
            return None
        return "%s?field.status_upstream=pending_bugwatch" % (
            canonical_url(self.context, view_name='+bugs'))

    @property
    def expirable_bugs_url(self):
        """A URL to a list of bugs that can expire, or None.

        If the bugtarget is not a supported implementation, or its pillar
        does not have enable_bug_expiration set to True, None is returned.
        The bugtarget may be an `IDistribution`, `IDistroSeries`, `IProduct`,
        or `IProductSeries`.
        """
        if target_has_expirable_bugs_listing(self.context):
            return canonical_url(self.context, view_name='+expirable-bugs')
        else:
            return None

    @property
    def new_bugs_url(self):
        """A URL to a page of new bugs."""
        return get_buglisting_search_filter_url(
            status=BugTaskStatus.NEW.title)

    @property
    def inprogress_bugs_url(self):
        """A URL to a page of inprogress bugs."""
        return get_buglisting_search_filter_url(
            status=BugTaskStatus.INPROGRESS.title)

    @property
    def open_bugs_url(self):
        """A URL to a list of open bugs."""
        return canonical_url(self.context, view_name='+bugs')

    @property
    def critical_bugs_url(self):
        """A URL to a list of critical bugs."""
        return get_buglisting_search_filter_url(
            status=[status.title for status in UNRESOLVED_BUGTASK_STATUSES],
            importance=BugTaskImportance.CRITICAL.title)

    @property
    def high_bugs_url(self):
        """A URL to a list of high priority bugs."""
        return get_buglisting_search_filter_url(
            status=[status.title for status in UNRESOLVED_BUGTASK_STATUSES],
            importance=BugTaskImportance.HIGH.title)

    @property
    def my_bugs_url(self):
        """A URL to a list of bugs assigned to the user, or None."""
        if self.user is None:
            return None
        else:
            return get_buglisting_search_filter_url(assignee=self.user.name)

    @property
    def my_reported_bugs_url(self):
        """A URL to a list of bugs reported by the user, or None."""
        if self.user is None:
            return None
        return get_buglisting_search_filter_url(bug_reporter=self.user.name)


class BugsStatsMixin(BugsInfoMixin):
    """Contains properties giving bug stats.

    These can be expensive to obtain.
    """

    @cachedproperty
    def _bug_stats(self):
        # Circular fail.
        from lp.bugs.model.bugsummary import BugSummary
        bug_task_set = getUtility(IBugTaskSet)
        groups = (BugSummary.status, BugSummary.importance,
            BugSummary.has_patch, BugSummary.fixed_upstream)
        counts = bug_task_set.countBugs(self.user, [self.context], groups)
        # Sum the split out aggregates.
        new = 0
        open = 0
        inprogress = 0
        critical = 0
        high = 0
        with_patch = 0
        resolved_upstream = 0
        for metadata, count in counts.items():
            status = metadata[0]
            importance = metadata[1]
            has_patch = metadata[2]
            was_resolved_upstream = metadata[3]
            if status == BugTaskStatus.NEW:
                new += count
            elif status == BugTaskStatus.INPROGRESS:
                inprogress += count
            if importance == BugTaskImportance.CRITICAL:
                critical += count
            elif importance == BugTaskImportance.HIGH:
                high += count
            if has_patch and DISPLAY_BUG_STATUS_FOR_PATCHES[status]:
                with_patch += count
            if was_resolved_upstream:
                resolved_upstream += count
            open += count
        result = dict(new=new, open=open, inprogress=inprogress, high=high,
            critical=critical, with_patch=with_patch,
            resolved_upstream=resolved_upstream)
        return result

    @property
    def bugs_fixed_elsewhere_count(self):
        """A count of bugs fixed elsewhere."""
        return self._bug_stats['resolved_upstream']

    @property
    def open_cve_bugs_count(self):
        """A count of open bugs linked to CVEs."""
        params = get_default_search_params(self.user)
        params.has_cve = True
        return self.context.searchTasks(params).count()

    @property
    def pending_bugwatches_count(self):
        """A count of bugs that need a bugwatch.

        None is returned if the context is not an upstream product.
        """
        if not IProduct.providedBy(self.context):
            return None
        if self.context.bug_tracking_usage == ServiceUsage.LAUNCHPAD:
            return None
        params = get_default_search_params(self.user)
        params.pending_bugwatch_elsewhere = True
        return self.context.searchTasks(params).count()

    @property
    def expirable_bugs_count(self):
        """A count of bugs that can expire, or None.

        If the bugtarget is not a supported implementation, or its pillar
        does not have enable_bug_expiration set to True, None is returned.
        The bugtarget may be an `IDistribution`, `IDistroSeries`, `IProduct`,
        or `IProductSeries`.
        """
        days_old = config.malone.days_before_expiration

        if target_has_expirable_bugs_listing(self.context):
            return getUtility(IBugTaskSet).findExpirableBugTasks(
                days_old, user=self.user, target=self.context).count()
        else:
            return None

    @property
    def new_bugs_count(self):
        """A count of new bugs."""
        return self._bug_stats['new']

    @property
    def open_bugs_count(self):
        """A count of open bugs."""
        return self._bug_stats['open']

    @property
    def inprogress_bugs_count(self):
        """A count of in-progress bugs."""
        return self._bug_stats['inprogress']

    @property
    def critical_bugs_count(self):
        """A count of critical bugs."""
        return self._bug_stats['critical']

    @property
    def high_bugs_count(self):
        """A count of high priority bugs."""
        return self._bug_stats['high']

    @property
    def my_bugs_count(self):
        """A count of bugs assigned to the user, or None."""
        if self.user is None:
            return None
        else:
            params = get_default_search_params(self.user)
            params.assignee = self.user
            return self.context.searchTasks(params).count()

    @property
    def my_reported_bugs_count(self):
        """A count of bugs reported by the user, or None."""
        if self.user is None:
            return None
        params = get_default_search_params(self.user)
        params.bug_reporter = self.user
        return self.context.searchTasks(params).count()

    @property
    def bugs_with_patches_count(self):
        """A count of unresolved bugs with patches."""
        return self._bug_stats['with_patch']


class BugListingPortletInfoView(LaunchpadView, BugsInfoMixin):
    """Portlet containing available bug listings without stats."""


class BugListingPortletStatsView(LaunchpadView, BugsStatsMixin):
    """Portlet containing available bug listings with stats."""


def get_buglisting_search_filter_url(
        assignee=None, importance=None, status=None, status_upstream=None,
        has_patches=None, bug_reporter=None):
    """Return the given URL with the search parameters specified."""
    search_params = []

    if assignee is not None:
        search_params.append(('field.assignee', assignee))
    if importance is not None:
        search_params.append(('field.importance', importance))
    if status is not None:
        search_params.append(('field.status', status))
    if status_upstream is not None:
        search_params.append(('field.status_upstream', status_upstream))
    if has_patches is not None:
        search_params.append(('field.has_patch', 'on'))
    if bug_reporter is not None:
        search_params.append(('field.bug_reporter', bug_reporter))

    query_string = urllib.urlencode(search_params, doseq=True)

    search_filter_url = "+bugs?search=Search"
    if query_string != '':
        search_filter_url += "&" + query_string

    return search_filter_url


def getInitialValuesFromSearchParams(search_params, form_schema):
    """Build a dictionary that can be given as initial values to
    setUpWidgets, based on the given search params.

    >>> initial = getInitialValuesFromSearchParams(
    ...     {'status': any(*UNRESOLVED_BUGTASK_STATUSES)}, IBugTaskSearch)
    >>> for status in initial['status']:
    ...     print status.name
    NEW
    INCOMPLETE
    CONFIRMED
    TRIAGED
    INPROGRESS
    FIXCOMMITTED

    >>> initial = getInitialValuesFromSearchParams(
    ...     {'status': BugTaskStatus.INVALID}, IBugTaskSearch)
    >>> [status.name for status in initial['status']]
    ['INVALID']

    >>> initial = getInitialValuesFromSearchParams(
    ...     {'importance': [BugTaskImportance.CRITICAL,
    ...                   BugTaskImportance.HIGH]}, IBugTaskSearch)
    >>> [importance.name for importance in initial['importance']]
    ['CRITICAL', 'HIGH']

    >>> getInitialValuesFromSearchParams(
    ...     {'assignee': NULL}, IBugTaskSearch)
    {'assignee': None}
    """
    initial = {}
    for key, value in search_params.items():
        if IList.providedBy(form_schema[key]):
            if isinstance(value, any):
                value = value.query_values
            elif isinstance(value, (list, tuple)):
                value = value
            else:
                value = [value]
        elif value == NULL:
            value = None
        else:
            # Should be safe to pass value as it is to setUpWidgets, no need
            # to worry
            pass

        initial[key] = value

    return initial


class BugTaskListingItem:
    """A decorated bug task.

    Some attributes that we want to display are too convoluted or expensive
    to get on the fly for each bug task in the listing.  These items are
    prefetched by the view and decorate the bug task.
    """
    delegates(IBugTask, 'bugtask')

    def __init__(self, bugtask, has_bug_branch,
                 has_specification, has_patch, request=None,
                 target_context=None):
        self.bugtask = bugtask
        self.review_action_widget = None
        self.has_bug_branch = has_bug_branch
        self.has_specification = has_specification
        self.has_patch = has_patch
        self.request = request
        self.target_context = target_context

    @property
    def last_significant_change_date(self):
        """The date of the last significant change."""
        return (self.bugtask.date_closed or self.bugtask.date_fix_committed or
                self.bugtask.date_inprogress or self.bugtask.date_left_new or
                self.bugtask.datecreated)

    @property
    def bug_heat_html(self):
        """Returns the bug heat flames HTML."""
        return bugtask_heat_html(self.bugtask, target=self.target_context)


class BugListingBatchNavigator(TableBatchNavigator):
    """A specialised batch navigator to load smartly extra bug information."""

    def __init__(self, tasks, request, columns_to_show, size,
                 target_context=None):
        # XXX sinzui 2009-05-29 bug=381672: Extract the BugTaskListingItem
        # rules to a mixin so that MilestoneView and others can use it.
        self.request = request
        self.target_context = target_context
        TableBatchNavigator.__init__(
            self, tasks, request, columns_to_show=columns_to_show, size=size)

    @cachedproperty
    def bug_badge_properties(self):
        return getUtility(IBugTaskSet).getBugTaskBadgeProperties(
            self.currentBatch())

    def _getListingItem(self, bugtask):
        """Return a decorated bugtask for the bug listing."""
        badge_property = self.bug_badge_properties[bugtask]
        if (IMaloneApplication.providedBy(self.target_context) or
            IPerson.providedBy(self.target_context)):
            # XXX Tom Berger bug=529846
            # When we have a specific interface for things that have bug heat
            # it would be better to use that for the check here instead.
            target_context = None
        else:
            target_context = self.target_context
        return BugTaskListingItem(
            bugtask,
            badge_property['has_branch'],
            badge_property['has_specification'],
            badge_property['has_patch'],
            request=self.request,
            target_context=target_context)

    def getBugListingItems(self):
        """Return a decorated list of visible bug tasks."""
        return [self._getListingItem(bugtask) for bugtask in self.batch]


class NominatedBugReviewAction(EnumeratedType):
    """Enumeration for nomination review actions"""

    ACCEPT = Item("""
        Accept

        Accept the bug nomination.
        """)

    DECLINE = Item("""
        Decline

        Decline the bug nomination.
        """)

    NO_CHANGE = Item("""
        No change

        Do not change the status of the bug nomination.
        """)


class NominatedBugListingBatchNavigator(BugListingBatchNavigator):
    """Batch navigator for nominated bugtasks. """

    implements(INominationsReviewTableBatchNavigator)

    def __init__(self, tasks, request, columns_to_show, size,
                 nomination_target, user):
        BugListingBatchNavigator.__init__(
            self, tasks, request, columns_to_show, size)
        self.nomination_target = nomination_target
        self.user = user

    def _getListingItem(self, bugtask):
        """See BugListingBatchNavigator."""
        bugtask_listing_item = BugListingBatchNavigator._getListingItem(
            self, bugtask)
        bug_nomination = bugtask_listing_item.bug.getNominationFor(
            self.nomination_target)
        if self.user is None or not bug_nomination.canApprove(self.user):
            return bugtask_listing_item

        review_action_field = Choice(
            __name__='review_action_%d' % bug_nomination.id,
            vocabulary=NominatedBugReviewAction,
            title=u'Review action', required=True)

        # This is so setUpWidget expects a view, and so
        # view.request. We're not passing a view but we still want it
        # to work.
        bugtask_listing_item.request = self.request

        bugtask_listing_item.review_action_widget = CustomWidgetFactory(
            NominationReviewActionWidget)
        setUpWidget(
            bugtask_listing_item,
            'review_action',
            review_action_field,
            IInputWidget,
            value=NominatedBugReviewAction.NO_CHANGE,
            context=bug_nomination)

        return bugtask_listing_item


class IBugTaskSearchListingMenu(Interface):
    """A marker interface for the search listing navigation menu."""


class BugTaskSearchListingMenu(NavigationMenu):
    """The search listing navigation menu."""
    usedfor = IBugTaskSearchListingMenu
    facet = 'bugs'

    @property
    def links(self):
        bug_target = self.context.context
        if IDistribution.providedBy(bug_target):
            return (
                'bugsupervisor',
                'securitycontact',
                'cve',
                )
        elif IDistroSeries.providedBy(bug_target):
            return (
                'cve',
                'nominations',
                )
        elif IProduct.providedBy(bug_target):
            return (
                'bugsupervisor',
                'securitycontact',
                'cve',
                )
        elif IProductSeries.providedBy(bug_target):
            return (
                'nominations',
                )
        else:
            return ()

    def cve(self):
        return Link('+cve', 'CVE reports', icon='cve')

    @enabled_with_permission('launchpad.Edit')
    def bugsupervisor(self):
        return Link('+bugsupervisor', 'Change bug supervisor', icon='edit')

    @enabled_with_permission('launchpad.Edit')
    def securitycontact(self):
        return Link(
            '+securitycontact', 'Change security contact', icon='edit')

    def nominations(self):
        return Link('+nominations', 'Review nominations', icon='bug')


class BugTaskSearchListingView(LaunchpadFormView, FeedsMixin, BugsInfoMixin):
    """View that renders a list of bugs for a given set of search criteria."""

    implements(IBugTaskSearchListingMenu)

    # Only include <link> tags for bug feeds when using this view.
    feed_types = (
        BugTargetLatestBugsFeedLink,
        )

    # These widgets are customised so as to keep the presentation of this view
    # and its descendants consistent after refactoring to use
    # LaunchpadFormView as a parent.
    custom_widget('searchtext', NewLineToSpacesWidget)
    custom_widget('status_upstream', LabeledMultiCheckBoxWidget)
    custom_widget('tag', BugTagsWidget)
    custom_widget('tags_combinator', RadioWidget)
    custom_widget('component', LabeledMultiCheckBoxWidget)

    @cachedproperty
    def bug_tracking_usage(self):
        """Whether the context tracks bugs in Launchpad.

        :returns: ServiceUsage enum value
        """
        service_usage = IServiceUsage(self.context)
        return service_usage.bug_tracking_usage

    @cachedproperty
    def external_bugtracker(self):
        """External bug tracking system designated for the context.

        :returns: `IBugTracker` or None
        """
        has_external_bugtracker = IHasExternalBugTracker(self.context, None)
        if has_external_bugtracker is None:
            return None
        else:
            return has_external_bugtracker.getExternalBugTracker()

    @property
    def has_bugtracker(self):
        """Does the `IBugTarget` have a bug tracker or use Launchpad?"""
        usage = IServiceUsage(self.context)
        uses_lp = usage.bug_tracking_usage == ServiceUsage.LAUNCHPAD
        if self.external_bugtracker or uses_lp:
            return True
        return False

    @property
    def upstream_launchpad_project(self):
        """The linked upstream `IProduct` for the package.

        If this `IBugTarget` is a `IDistributionSourcePackage` or an
        `ISourcePackage` and it is linked to an upstream project that uses
        Launchpad to track bugs, return the `IProduct`. Otherwise,
        return None

        :returns: `IProduct` or None
        """
        if self._sourcePackageContext():
            sp = self.context
        elif self._distroSourcePackageContext():
            sp = self.context.development_version
        else:
            sp = None
        if sp is not None:
            packaging = sp.packaging
            if packaging is not None:
                product = packaging.productseries.product
                if product.bug_tracking_usage == ServiceUsage.LAUNCHPAD:
                    return product
        return None

    @property
    def page_title(self):
        return "Bugs in %s" % self.context.title

    label = page_title

    @property
    def schema(self):
        """Return the schema that defines the form."""
        if self._personContext():
            return IPersonBugTaskSearch
        elif self.isUpstreamProduct:
            return IUpstreamProductBugTaskSearch
        else:
            return IBugTaskSearch

    @property
    def feed_links(self):
        """Prevent conflicts between the page and the atom feed.

        The latest-bugs atom feed matches the default output of this
        view, but it does not match this view's bug listing when
        any search parameters are passed in.
        """
        if self.request.get('QUERY_STRING', '') == '':
            # There is no query in this request, so it's okay for this page to
            # have its feed links.
            return super(BugTaskSearchListingView, self).feed_links
        else:
            # The query changes the results so that they would not match the
            # feed.  In this case, suppress the feed links.
            return []

    def initialize(self):
        """Initialize the view with the request.

        Look for old status names and redirect to a new location if found.
        """
        query_string = self.request.get('QUERY_STRING')
        if query_string:
            query_string_rewritten = (
                rewrite_old_bugtask_status_query_string(query_string))
            if query_string_rewritten != query_string:
                redirect_uri = URI(self.request.getURL()).replace(
                    query=query_string_rewritten)
                self.request.response.redirect(str(redirect_uri), status=301)
                return

        self._migrateOldUpstreamStatus()
        LaunchpadFormView.initialize(self)

        # We call self._validate() here because LaunchpadFormView only
        # validates the form if an action is submitted but, because this form
        # can be called through a query string, we don't want to require an
        # action. We pass an empty dict to _validate() because all the data
        # needing validation is already available internally to self.
        self._validate(None, {})

        expose_structural_subscription_data_to_js(
            self.context, self.request, self.user)

    @property
    def columns_to_show(self):
        """Returns a sequence of column names to be shown in the listing."""
        upstream_context = self._upstreamContext()
        productseries_context = self._productSeriesContext()
        project_context = self._projectContext()
        distribution_context = self._distributionContext()
        distroseries_context = self._distroSeriesContext()
        distrosourcepackage_context = self._distroSourcePackageContext()
        sourcepackage_context = self._sourcePackageContext()

        if (upstream_context or productseries_context or
            distrosourcepackage_context or sourcepackage_context):
            return ["id", "summary", "importance", "status", "heat"]
        elif distribution_context or distroseries_context:
            return [
                "id", "summary", "packagename", "importance", "status",
                "heat"]
        elif project_context:
            return [
                "id", "summary", "productname", "importance", "status",
                "heat"]
        else:
            raise AssertionError(
                "Unrecognized context; don't know which report "
                "columns to show.")

    def validate_search_params(self):
        """Validate the params passed for the search.

        An UnexpectedFormData exception is raised if the user submitted a URL
        that could not have been created from the UI itself.
        """
        # The only way the user should get these field values incorrect is
        # through a stale bookmark or a hand-hacked URL.
        for field_name in ("status", "importance", "milestone", "component",
                           "status_upstream"):
            if self.getFieldError(field_name):
                raise UnexpectedFormData(
                    "Unexpected value for field '%s'. Perhaps your bookmarks "
                    "are out of date or you changed the URL by hand?" %
                    field_name)

        orderby = get_sortorder_from_request(self.request)
        bugset = getUtility(IBugTaskSet)
        for orderby_col in orderby:
            if orderby_col.startswith("-"):
                orderby_col = orderby_col[1:]

            try:
                bugset.getOrderByColumnDBName(orderby_col)
            except KeyError:
                raise UnexpectedFormData(
                    "Unknown sort column '%s'" % orderby_col)

    def setUpWidgets(self):
        """Customize the onKeyPress event of the assignee chooser."""
        LaunchpadFormView.setUpWidgets(self)

        self.widgets["assignee"].onKeyPress = (
            "selectWidget('assignee_option', event)")

    def validate(self, data):
        """Validates the form."""
        self.validateVocabulariesAdvancedForm()
        self.validate_search_params()

    def _migrateOldUpstreamStatus(self):
        """Converts old upstream status value parameters to new ones.

        Before Launchpad version 1.1.6 (build 4412), the upstream parameter
        in the request was a single string value, coming from a set of
        radio buttons. From that version on, the user can select multiple
        values in the web UI. In order to keep old bookmarks working,
        convert the old string parameter into a list.
        """
        old_upstream_status_values_to_new_values = {
            'only_resolved_upstream': 'resolved_upstream'}

        status_upstream = self.request.get('field.status_upstream')
        if status_upstream in old_upstream_status_values_to_new_values.keys():
            self.request.form['field.status_upstream'] = [
                old_upstream_status_values_to_new_values[status_upstream]]
        elif status_upstream == '':
            del self.request.form['field.status_upstream']
        else:
            # The value of status_upstream is either correct, so nothing to
            # do, or it has some other error, which is handled in
            # LaunchpadFormView's own validation.
            pass

    def buildSearchParams(self, searchtext=None, extra_params=None):
        """Build the BugTaskSearchParams object for the given arguments and
        values specified by the user on this form's widgets.
        """
        # Calling _validate populates the data dictionary as a side-effect
        # of validation.
        data = {}
        self._validate(None, data)

        if extra_params:
            data.update(extra_params)

        if data:
            searchtext = data.get("searchtext")
            if searchtext and searchtext.isdigit():
                try:
                    bug = getUtility(IBugSet).get(searchtext)
                except NotFoundError:
                    pass
                else:
                    self.request.response.redirect(canonical_url(bug))

            assignee_option = self.request.form.get("assignee_option")
            if assignee_option == "none":
                data['assignee'] = NULL

            has_patch = data.pop("has_patch", False)
            if has_patch:
                data["attachmenttype"] = BugAttachmentType.PATCH

            has_branches = data.get('has_branches', True)
            has_no_branches = data.get('has_no_branches', True)
            if has_branches and not has_no_branches:
                data['linked_branches'] = BugBranchSearch.BUGS_WITH_BRANCHES
            elif not has_branches and has_no_branches:
                data['linked_branches'] = (
                    BugBranchSearch.BUGS_WITHOUT_BRANCHES)
            else:
                data['linked_branches'] = BugBranchSearch.ALL

            has_blueprints = data.get('has_blueprints', True)
            has_no_blueprints = data.get('has_no_blueprints', True)
            if has_blueprints and not has_no_blueprints:
                data['linked_blueprints'] = (
                    BugBlueprintSearch.BUGS_WITH_BLUEPRINTS)
            elif not has_blueprints and has_no_blueprints:
                data['linked_blueprints'] = (
                    BugBlueprintSearch.BUGS_WITHOUT_BLUEPRINTS)
            else:
                data['linked_blueprints'] = BugBlueprintSearch.ALL

            # Filter appropriately if the user wants to restrict the
            # search to only bugs with no package information.
            has_no_package = data.pop("has_no_package", False)
            if has_no_package:
                data["sourcepackagename"] = NULL

        self._buildUpstreamStatusParams(data)

        # "Normalize" the form data into search arguments.
        form_values = {}
        for key, value in data.items():
            if key in ('tag'):
                # Skip tag-related parameters, they
                # are handled later on.
                continue
            if zope_isinstance(value, (list, tuple)):
                if len(value) > 0:
                    form_values[key] = any(*value)
            else:
                form_values[key] = value

        if 'tag' in data:
            # Tags require special handling, since they can be used
            # to search either inclusively or exclusively.
            # We take a look at the `tags_combinator` field, and wrap
            # the tag list in the appropriate search directive (either
            # `any` or `all`). If no value is supplied, we assume `any`,
            # in order to remain compatible with old saved search URLs.
            tags = data['tag']
            tags_combinator_all = (
                'tags_combinator' in data and
                data['tags_combinator'] == BugTagsSearchCombinator.ALL)
            if zope_isinstance(tags, (list, tuple)) and len(tags) > 0:
                if tags_combinator_all:
                    form_values['tag'] = all(*tags)
                else:
                    form_values['tag'] = any(*tags)
            else:
                form_values['tag'] = tags

        search_params = get_default_search_params(self.user)
        search_params.orderby = get_sortorder_from_request(self.request)
        for name, value in form_values.items():
            setattr(search_params, name, value)
        return search_params

    def _buildUpstreamStatusParams(self, data):
        """ Convert the status_upstream value to parameters we can
        send to BugTaskSet.search().
        """
        if 'status_upstream' in data:
            status_upstream = data['status_upstream']
            if 'pending_bugwatch' in status_upstream:
                data['pending_bugwatch_elsewhere'] = True
            if 'resolved_upstream' in status_upstream:
                data['resolved_upstream'] = True
            if 'open_upstream' in status_upstream:
                data['open_upstream'] = True
            if 'hide_upstream' in status_upstream:
                data['has_no_upstream_bugtask'] = True
            del data['status_upstream']

    def _getBatchNavigator(self, tasks):
        """Return the batch navigator to be used to batch the bugtasks."""
        return BugListingBatchNavigator(
            tasks, self.request, columns_to_show=self.columns_to_show,
            size=config.malone.buglist_batch_size,
            target_context=self.context)

    def buildBugTaskSearchParams(self, searchtext=None, extra_params=None):
        """Build the parameters to submit to the `searchTasks` method.

        Use the data submitted in the form to populate a dictionary
        which, when expanded (using **params notation) can serve as the
        input for searchTasks().
        """

        # We force the view to populate the data dictionary by calling
        # _validate here.
        data = {}
        self._validate(None, data)

        searchtext = data.get("searchtext")
        if searchtext and searchtext.isdigit():
            try:
                bug = getUtility(IBugSet).get(searchtext)
            except NotFoundError:
                pass
            else:
                self.request.response.redirect(canonical_url(bug))

        if extra_params:
            data.update(extra_params)

        params = {}

        # A mapping of parameters that appear in the destination
        # with a different name, or are being dropped altogether.
        param_names_map = {
            'searchtext': 'search_text',
            'omit_dupes': 'omit_duplicates',
            'subscriber': 'bug_subscriber',
            'tag': 'tags',
            # The correct value is being retrieved
            # using get_sortorder_from_request()
            'orderby': None,
            }

        for key, value in data.items():
            if key in param_names_map:
                param_name = param_names_map[key]
                if param_name is not None:
                    params[param_name] = value
            else:
                params[key] = value

        assignee_option = self.request.form.get("assignee_option")
        if assignee_option == "none":
            params['assignee'] = NULL

        params['order_by'] = get_sortorder_from_request(self.request)

        return params

    def search(self, searchtext=None, context=None, extra_params=None):
        """Return an `ITableBatchNavigator` for the GET search criteria.

        :param searchtext: Text that must occur in the bug report. If
            searchtext is None, the search text will be gotten from the
            request.

        :param extra_params: A dict that provides search params added to
            the search criteria taken from the request. Params in
            `extra_params` take precedence over request params.
        """
        unbatchedTasks = self.searchUnbatched(
            searchtext, context, extra_params)
        return self._getBatchNavigator(unbatchedTasks)

    def searchUnbatched(self, searchtext=None, context=None,
                        extra_params=None, prejoins=[]):
        """Return a `SelectResults` object for the GET search criteria.

        :param searchtext: Text that must occur in the bug report. If
            searchtext is None, the search text will be gotten from the
            request.

        :param extra_params: A dict that provides search params added to
            the search criteria taken from the request. Params in
            `extra_params` take precedence over request params.
        """
        # Base classes can provide an explicit search context.
        if not context:
            context = self.context

        search_params = self.buildSearchParams(
            searchtext=searchtext, extra_params=extra_params)
        search_params.user = self.user
        tasks = context.searchTasks(search_params, prejoins=prejoins)
        return tasks

    def getWidgetValues(
        self, vocabulary_name=None, vocabulary=None, default_values=()):
        """Return data used to render a field's widget.

        Either `vocabulary_name` or `vocabulary` must be supplied."""
        widget_values = []

        if vocabulary is None:
            assert vocabulary_name is not None, 'No vocabulary specified.'
            vocabulary_registry = getVocabularyRegistry()
            vocabulary = vocabulary_registry.get(
                self.context, vocabulary_name)
        for term in vocabulary:
            widget_values.append(
                dict(
                    value=term.token, title=term.title or term.token,
                    checked=term.value in default_values))
        return helpers.shortlist(widget_values, longest_expected=12)

    def getStatusWidgetValues(self):
        """Return data used to render the status checkboxes."""
        return self.getWidgetValues(
            vocabulary=BugTaskStatusSearchDisplay,
            default_values=DEFAULT_SEARCH_BUGTASK_STATUSES_FOR_DISPLAY)

    def getImportanceWidgetValues(self):
        """Return data used to render the Importance checkboxes."""
        return self.getWidgetValues(vocabulary=BugTaskImportance)

    def getMilestoneWidgetValues(self):
        """Return data used to render the milestone checkboxes."""
        return self.getWidgetValues("Milestone")

    def getSimpleSearchURL(self):
        """Return a URL that can be used as an href to the simple search."""
        return canonical_url(self.context) + "/+bugs"

    def shouldShowAssigneeWidget(self):
        """Should the assignee widget be shown on the advanced search page?"""
        return True

    def shouldShowCommenterWidget(self):
        """Show the commenter widget on the advanced search page?"""
        return True

    def shouldShowComponentWidget(self):
        """Show the component widget on the advanced search page?"""
        context = self.context
        return (
            (IDistribution.providedBy(context) and
             context.currentseries is not None) or
            IDistroSeries.providedBy(context) or
            ISourcePackage.providedBy(context))

    def shouldShowSupervisorWidget(self):
        """
        Should the bug supervisor widget be shown on the advanced search page?
        """
        return True

    def shouldShowNoPackageWidget(self):
        """Should the widget to filter on bugs with no package be shown?

        The widget will be shown only on a distribution or
        distroseries's advanced search page.
        """
        return (IDistribution.providedBy(self.context) or
                IDistroSeries.providedBy(self.context))

    def shouldShowReporterWidget(self):
        """Should the reporter widget be shown on the advanced search page?"""
        return True

    def shouldShowTagsCombinatorWidget(self):
        """Should the tags combinator widget show on the search page?"""
        return True

    def shouldShowReleaseCriticalPortlet(self):
        """Should the page include a portlet showing release-critical bugs
        for different series.
        """
        return (
            IDistribution.providedBy(self.context) and self.context.series
            or IDistroSeries.providedBy(self.context)
            or IProduct.providedBy(self.context) and self.context.series
            or IProductSeries.providedBy(self.context))

    def shouldShowSubscriberWidget(self):
        """Show the subscriber widget on the advanced search page?"""
        return True

    def shouldShowUpstreamStatusBox(self):
        """Should the upstream status filtering widgets be shown?"""
        return self.isUpstreamProduct or not (
            IProduct.providedBy(self.context) or
            IProjectGroup.providedBy(self.context))

    def getSortLink(self, colname):
        """Return a link that can be used to sort results by colname."""
        form = self.request.form
        sortlink = ""
        if form.get("search") is None:
            # There is no search criteria to preserve.
            sortlink = "%s?search=Search&orderby=%s" % (
                str(self.request.URL), colname)
            return sortlink

        # XXX: kiko 2005-08-23:
        # Is it not possible to get the exact request supplied and
        # just sneak a "-" in front of the orderby argument, if it
        # exists? If so, the code below could be a lot simpler.

        # There is search criteria to preserve.
        sortlink = str(self.request.URL) + "?"
        for fieldname in form:
            fieldvalue = form.get(fieldname)
            if isinstance(fieldvalue, (list, tuple)):
                fieldvalue = [value.encode("utf-8") for value in fieldvalue]
            else:
                fieldvalue = fieldvalue.encode("utf-8")

            if fieldname != "orderby":
                sortlink += "%s&" % urllib.urlencode(
                    {fieldname: fieldvalue}, doseq=True)

        sorted, ascending = self._getSortStatus(colname)
        if sorted and ascending:
            # If we are currently ascending, revert the direction
            colname = "-" + colname

        sortlink += "orderby=%s" % colname

        return sortlink

    def getSortedColumnCSSClass(self, colname):
        """Return a class appropriate for sorted columns"""
        sorted, ascending = self._getSortStatus(colname)
        if not sorted:
            return ""
        if ascending:
            return "sorted ascending"
        return "sorted descending"

    def _getSortStatus(self, colname):
        """Finds out if the list is sorted by the column specified.

        Returns a tuple (sorted, ascending), where sorted is true if the
        list is currently sorted by the column specified, and ascending
        is true if sorted in ascending order.
        """
        current_sort_column = self.request.form.get("orderby")
        if current_sort_column is None:
            return (False, False)

        ascending = True
        sorted = True
        if current_sort_column.startswith("-"):
            ascending = False
            current_sort_column = current_sort_column[1:]

        if current_sort_column != colname:
            sorted = False

        return (sorted, ascending)

    def shouldShowTargetName(self):
        """Should the bug target name be displayed in the list of results?

        This is mainly useful for the listview.
        """
        # It doesn't make sense to show the target name when viewing product
        # bugs.
        if IProduct.providedBy(self.context):
            return False
        else:
            return True

    def shouldShowAdvancedForm(self):
        """Return True if the advanced form should be shown, or False."""
        if (self.request.form.get('advanced')
            or self.form_has_errors):
            return True
        else:
            return False

    @property
    def should_show_bug_information(self):
        return self.bug_tracking_usage == ServiceUsage.LAUNCHPAD

    @property
    def form_has_errors(self):
        """Return True if the form has errors, otherwise False."""
        return len(self.errors) > 0

    def validateVocabulariesAdvancedForm(self):
        """Provides a meaningful message for vocabulary validation errors."""
        error_message = _(
            "There's no person with the name or email address '%s'.")

        for name in ('assignee', 'bug_reporter', 'bug_supervisor',
                     'bug_commenter', 'subscriber'):
            if self.getFieldError(name):
                self.setFieldError(
                    name, error_message %
                        self.request.get('field.%s' % name))

    @property
    def isUpstreamProduct(self):
        """Is the context a Product that does not use Malone?"""
        return (
            IProduct.providedBy(self.context)
            and self.context.bug_tracking_usage != ServiceUsage.LAUNCHPAD)

    def _upstreamContext(self):
        """Is this page being viewed in an upstream context?

        Return the IProduct if yes, otherwise return None.
        """
        return IProduct(self.context, None)

    def _productSeriesContext(self):
        """Is this page being viewed in a product series context?

        Return the IProductSeries if yes, otherwise return None.
        """
        return IProductSeries(self.context, None)

    def _projectContext(self):
        """Is this page being viewed in a project context?

        Return the IProjectGroup if yes, otherwise return None.
        """
        return IProjectGroup(self.context, None)

    def _personContext(self):
        """Is this page being viewed in a person context?

        Return the IPerson if yes, otherwise return None.
        """
        return IPerson(self.context, None)

    def _distributionContext(self):
        """Is this page being viewed in a distribution context?

        Return the IDistribution if yes, otherwise return None.
        """
        return IDistribution(self.context, None)

    def _distroSeriesContext(self):
        """Is this page being viewed in a distroseries context?

        Return the IDistroSeries if yes, otherwise return None.
        """
        return IDistroSeries(self.context, None)

    def _sourcePackageContext(self):
        """Is this view in a [distroseries] sourcepackage context?

        Return the ISourcePackage if yes, otherwise return None.
        """
        return ISourcePackage(self.context, None)

    def _distroSourcePackageContext(self):
        """Is this page being viewed in a distribution sourcepackage context?

        Return the IDistributionSourcePackage if yes, otherwise return None.
        """
        return IDistributionSourcePackage(self.context, None)

    @property
    def addquestion_url(self):
        """Return the URL for the +addquestion view for the context."""
        if IQuestionTarget.providedBy(self.context):
            return canonical_url(
                self.context, rootsite='answers', view_name='+addquestion')
        else:
            return None


class BugNominationsView(BugTaskSearchListingView):
    """View for accepting/declining bug nominations."""

    def _getBatchNavigator(self, tasks):
        """See BugTaskSearchListingView."""
        batch_navigator = NominatedBugListingBatchNavigator(
            tasks, self.request, columns_to_show=self.columns_to_show,
            size=config.malone.buglist_batch_size,
            nomination_target=self.context, user=self.user)
        return batch_navigator

    def search(self):
        """Return all the nominated tasks for this series."""
        if IDistroSeries.providedBy(self.context):
            main_context = self.context.distribution
        elif IProductSeries.providedBy(self.context):
            main_context = self.context.product
        else:
            raise AssertionError(
                'Unknown nomination target: %r' % self.context)
        return BugTaskSearchListingView.search(
            self, context=main_context,
            extra_params=dict(nominated_for=self.context))


class NominationsReviewTableBatchNavigatorView(LaunchpadFormView):
    """View for displaying a list of nominated bugs."""

    def canApproveNominations(self, action=None):
        """Whether the user can approve any of the shown nominations."""
        return len(list(self.widgets)) > 0

    def setUpFields(self):
        """See LaunchpadFormView."""
        # We set up the widgets ourselves.
        self.form_fields = []

    def setUpWidgets(self):
        """See LaunchpadFormView."""
        widgets_list = [
            (True, bug_listing_item.review_action_widget)
            for bug_listing_item in self.context.getBugListingItems()
            if bug_listing_item.review_action_widget is not None]
        self.widgets = formlib.form.Widgets(
            widgets_list, len(self.prefix) + 1)

    @action('Save changes', name='submit', condition=canApproveNominations)
    def submit_action(self, action, data):
        """Accept/Decline bug nominations."""
        accepted = declined = 0

        for name, review_action in data.items():
            if review_action == NominatedBugReviewAction.NO_CHANGE:
                continue
            field = self.widgets[name].context
            bug_nomination = field.context
            if review_action == NominatedBugReviewAction.ACCEPT:
                bug_nomination.approve(self.user)
                accepted += 1
            elif review_action == NominatedBugReviewAction.DECLINE:
                bug_nomination.decline(self.user)
                declined += 1
            else:
                raise AssertionError(
                    'Unknown NominatedBugReviewAction: %r' % review_action)

        if accepted > 0:
            self.request.response.addInfoNotification(
                '%d nomination(s) accepted' % accepted)
        if declined > 0:
            self.request.response.addInfoNotification(
                '%d nomination(s) declined' % declined)

        self.next_url = self.request.getURL()
        query_string = self.request.get('QUERY_STRING')
        if query_string:
            self.next_url += '?%s' % query_string


class BugTargetView(LaunchpadView):
    """Used to grab bugs for a bug target; used by the latest bugs portlet"""

    def latestBugTasks(self, quantity=5):
        """Return <quantity> latest bugs reported against this target."""
        params = BugTaskSearchParams(orderby="-datecreated",
                                     omit_dupes=True,
                                     user=getUtility(ILaunchBag).user)

        tasklist = self.context.searchTasks(params)
        return tasklist[:quantity]

    def getMostRecentlyUpdatedBugTasks(self, limit=5):
        """Return the most recently updated bugtasks for this target."""
        params = BugTaskSearchParams(
            orderby="-date_last_updated", omit_dupes=True, user=self.user)
        return list(self.context.searchTasks(params)[:limit])


class TextualBugTaskSearchListingView(BugTaskSearchListingView):
    """View that renders a list of bug IDs for a given set of search criteria.
    """

    def render(self):
        """Render the BugTarget for text display."""
        self.request.response.setHeader(
            'Content-type', 'text/plain')

        # This uses the BugTaskSet internal API instead of using the
        # standard searchTasks() because the latter can retrieve a lot
        # of bugs and we don't want to load all of that data in memory.
        # Retrieving only the bug numbers is much more efficient.
        search_params = self.buildSearchParams()

        # XXX flacoste 2008/04/24 This should be moved to a
        # BugTaskSearchParams.setTarget().
        if (IDistroSeries.providedBy(self.context) or
            IProductSeries.providedBy(self.context)):
            search_params.setTarget(self.context)
        elif IDistribution.providedBy(self.context):
            search_params.setDistribution(self.context)
        elif IProduct.providedBy(self.context):
            search_params.setProduct(self.context)
        elif IProjectGroup.providedBy(self.context):
            search_params.setProject(self.context)
        elif (ISourcePackage.providedBy(self.context) or
              IDistributionSourcePackage.providedBy(self.context)):
            search_params.setSourcePackage(self.context)
        else:
            raise AssertionError('Uknown context type: %s' % self.context)

        return u"".join("%d\n" % bug_id for bug_id in
            getUtility(IBugTaskSet).searchBugIds(search_params))


def _by_targetname(bugtask):
    """Normalize the bugtask.targetname, for sorting."""
    return re.sub(r"\W", "", bugtask.bugtargetdisplayname)


class CachedMilestoneSourceFactory:
    """A factory for milestone vocabularies.

    When rendering a page with many bug tasks, this factory is useful,
    in order to avoid the number of db queries issues. For each bug task
    target, we cache the milestone vocabulary, so we don't have to
    create a new one for each target.
    """

    implements(IContextSourceBinder)

    def __init__(self):
        self.vocabularies = {}
        self.contexts = set()

    def __call__(self, context):
        assert context in self.contexts, ("context %r not added to "
            "self.contexts (%r)." % (context, self.contexts))
        self._load()
        target = MilestoneVocabulary.getMilestoneTarget(context)
        return self.vocabularies[target]

    def _load(self):
        """Load all the vocabularies, once only."""
        if self.vocabularies:
            return
        targets = set(
            map(MilestoneVocabulary.getMilestoneTarget, self.contexts))
        # TODO: instantiate for all targets at once.
        for target in targets:
            milestone_vocabulary = MilestoneVocabulary(target)
            self.vocabularies[target] = milestone_vocabulary


class BugTasksAndNominationsView(LaunchpadView):
    """Browser class for rendering the bugtasks and nominations table."""

    target_releases = None

    def __init__(self, context, request):
        """Ensure we always have a bug context."""
        LaunchpadView.__init__(self, IBug(context), request)

    def initialize(self):
        """Cache the list of bugtasks and set up the release mapping."""
        # Cache some values, so that we don't have to recalculate them
        # for each bug task.
        # Note: even though the publisher queries all the bugtasks and we in
        # theory could just reuse that already loaded list here, it's better
        # to do another query to only load the bug tasks for active projects
        # so we don't incur the cost of setting up data structures for tasks
        # we will not be showing in the listing.
        bugtask_set = getUtility(IBugTaskSet)
        search_params = BugTaskSearchParams(user=self.user, bug=self.context)
        self.bugtasks = list(bugtask_set.search(search_params))
        self.many_bugtasks = len(self.bugtasks) >= 10
        self.cached_milestone_source = CachedMilestoneSourceFactory()
        self.user_is_subscribed = self.context.isSubscribed(self.user)

        # Pull all of the related milestones, if any, into the storm cache,
        # since they'll be needed for the vocabulary used in this view.
        if self.bugtasks:
            self.milestones = list(
                bugtask_set.getBugTaskTargetMilestones(self.bugtasks))
        else:
            self.milestones = []
        distro_packages = defaultdict(list)
        distro_series_packages = defaultdict(list)
        for bugtask in self.bugtasks:
            target = bugtask.target
            if IDistributionSourcePackage.providedBy(target):
                distro_packages[target.distribution].append(
                    target.sourcepackagename)
            if ISourcePackage.providedBy(target):
                distro_series_packages[target.distroseries].append(
                    target.sourcepackagename)
        distro_set = getUtility(IDistributionSet)
        self.target_releases = dict(distro_set.getCurrentSourceReleases(
            distro_packages))
        distro_series_set = getUtility(IDistroSeriesSet)
        self.target_releases.update(
            distro_series_set.getCurrentSourceReleases(
                distro_series_packages))
        ids = set()
        for release_person_ids in map(attrgetter('creatorID', 'maintainerID'),
            self.target_releases.values()):
            ids.update(release_person_ids)
        ids.discard(None)
        if ids:
            list(getUtility(IPersonSet).getPrecachedPersonsFromIDs(ids))

    def getTargetLinkTitle(self, target):
        """Return text to put as the title for the link to the target."""
        if not (IDistributionSourcePackage.providedBy(target) or
                ISourcePackage.providedBy(target)):
            return None
        current_release = self.target_releases.get(target)
        if current_release is None:
            return "No current release for this source package in %s" % (
                target.distribution.displayname)
        uploader = current_release.creator
        maintainer = current_release.maintainer
        return (
            "Latest release: %(version)s, uploaded to %(component)s"
            " on %(date_uploaded)s by %(uploader)s,"
            " maintained by %(maintainer)s" % dict(
                version=current_release.version,
                component=current_release.component.name,
                date_uploaded=current_release.dateuploaded,
                uploader=uploader.unique_displayname,
                maintainer=maintainer.unique_displayname,
                ))

    def _getTableRowView(self, context, is_converted_to_question,
                         is_conjoined_slave):
        """Get the view for the context, and initialize it.

        The view's is_conjoined_slave and is_converted_to_question
        attributes are set, as well as the edit view.
        """
        self.cached_milestone_source.contexts.add(context)
        view = getMultiAdapter(
            (context, self.request),
            name='+bugtasks-and-nominations-table-row')
        view.is_converted_to_question = is_converted_to_question
        view.is_conjoined_slave = is_conjoined_slave
        if IBugTask.providedBy(context):
            view.target_link_title = self.getTargetLinkTitle(context.target)

        view.edit_view = getMultiAdapter(
            (context, self.request), name='+edit-form')
        view.milestone_source = self.cached_milestone_source
        view.edit_view.milestone_source = self.cached_milestone_source
        view.edit_view.user_is_subscribed = self.user_is_subscribed
        # Hint to optimize when there are many bugtasks.
        view.many_bugtasks = self.many_bugtasks
        return view

    def getBugTaskAndNominationViews(self):
        """Return the IBugTasks and IBugNominations views for this bug.

        Returns a list of views, sorted by the context's targetname,
        with upstream tasks sorted before distribution tasks, and
        nominations sorted after tasks. Approved nominations are not
        included in the returned results.
        """
        bug = self.context
        bugtasks = self.bugtasks

        upstream_tasks = [
            bugtask for bugtask in bugtasks
            if bugtask.product or bugtask.productseries]

        distro_tasks = [
            bugtask for bugtask in bugtasks
            if bugtask.distribution or bugtask.distroseries]

        upstream_tasks.sort(key=_by_targetname)
        distro_tasks.sort(key=_by_targetname)
        all_bugtasks = upstream_tasks + distro_tasks

        # Cache whether the bug was converted to a question, since
        # bug.getQuestionCreatedFromBug issues a db query each time it
        # is called.
        is_converted_to_question = bug.getQuestionCreatedFromBug() is not None
        # Insert bug nominations in between the appropriate tasks.
        bugtask_and_nomination_views = []
        # Having getNominations() get the list of bug nominations each
        # time it gets called in the for loop is expensive. Get the
        # nominations here, so we can pass it to getNominations() later
        # on.
        nominations = list(bug.getNominations())
        # Eager load validity for all the persons we know of that will be
        # displayed.
        ids = set(map(attrgetter('ownerID'), nominations))
        ids.discard(None)
        if ids:
            list(getUtility(IPersonSet).getPrecachedPersonsFromIDs(
                ids, need_validity=True))

        # Build a cache we can pass on to getConjoinedMaster(), so that
        # it doesn't have to iterate over all the bug tasks in each loop
        # iteration.
        bugtasks_by_package = bug.getBugTasksByPackageName(all_bugtasks)

        latest_parent = None

        for bugtask in all_bugtasks:
            # Series bug targets only display the series name, so they
            # must always be preceded by their parent context. Normally
            # the parent will have a task, but if not we need to show a
            # fake one.
            if ISeriesBugTarget.providedBy(bugtask.target):
                parent = bugtask.target.bugtarget_parent
            else:
                latest_parent = parent = bugtask.target

            if parent != latest_parent:
                latest_parent = parent
                bugtask_and_nomination_views.append(
                    getMultiAdapter(
                        (parent, self.request),
                        name='+bugtasks-and-nominations-table-row'))

            conjoined_master = bugtask.getConjoinedMaster(
                bugtasks, bugtasks_by_package)
            view = self._getTableRowView(
                bugtask, is_converted_to_question,
                conjoined_master is not None)
            bugtask_and_nomination_views.append(view)
            target = bugtask.product or bugtask.distribution
            if not target:
                continue

            target_nominations = bug.getNominations(
                target, nominations=nominations)
            bugtask_and_nomination_views.extend(
                self._getTableRowView(
                    nomination, is_converted_to_question, False)
                for nomination in target_nominations
                if nomination.status != BugNominationStatus.APPROVED)

        return bugtask_and_nomination_views

    @property
    def current_bugtask(self):
        """Return the current `IBugTask`.

        'current' is determined by simply looking in the ILaunchBag utility.
        """
        return getUtility(ILaunchBag).bugtask

    def displayAlsoAffectsLinks(self):
        """Return True if the Also Affects links should be displayed."""
        # Hide the links when the bug is viewed in a CVE context
        return self.request.getNearest(ICveSet) == (None, None)

    @cachedproperty
    def current_user_affected_status(self):
        """Is the current user marked as affected by this bug?"""
        return self.context.isUserAffected(self.user)

    @property
    def current_user_affected_js_status(self):
        """A javascript literal indicating if the user is affected."""
        affected = self.current_user_affected_status
        if affected is None:
            return 'null'
        elif affected:
            return 'true'
        else:
            return 'false'

    @property
    def other_users_affected_count(self):
        """The number of other users affected by this bug."""
        if self.current_user_affected_status:
            return self.context.users_affected_count - 1
        else:
            return self.context.users_affected_count

    @property
    def affected_statement(self):
        """The default "this bug affects" statement to show.

        The outputs of this method should be mirrored in
        MeTooChoiceSource._getSourceNames() (Javascript).
        """
        if self.other_users_affected_count == 1:
            if self.current_user_affected_status is None:
                return "This bug affects 1 person. Does this bug affect you?"
            elif self.current_user_affected_status:
                return "This bug affects you and 1 other person"
            else:
                return "This bug affects 1 person, but not you"
        elif self.other_users_affected_count > 1:
            if self.current_user_affected_status is None:
                return (
                    "This bug affects %d people. Does this bug "
                    "affect you?" % (self.other_users_affected_count))
            elif self.current_user_affected_status:
                return "This bug affects you and %d other people" % (
                    self.other_users_affected_count)
            else:
                return "This bug affects %d people, but not you" % (
                    self.other_users_affected_count)
        else:
            if self.current_user_affected_status is None:
                return "Does this bug affect you?"
            elif self.current_user_affected_status:
                return "This bug affects you"
            else:
                return "This bug doesn't affect you"

    @property
    def anon_affected_statement(self):
        """The "this bug affects" statement to show to anonymous users.

        The outputs of this method should be mirrored in
        MeTooChoiceSource._getSourceNames() (Javascript).
        """
        if self.context.users_affected_count == 1:
            return "This bug affects 1 person"
        elif self.context.users_affected_count > 1:
            return "This bug affects %d people" % (
                self.context.users_affected_count)
        else:
            return None


class BugTaskTableRowView(LaunchpadView, BugTaskBugWatchMixin):
    """Browser class for rendering a bugtask row on the bug page."""

    is_conjoined_slave = None
    is_converted_to_question = None
    target_link_title = None
    many_bugtasks = False

    def __init__(self, context, request):
        super(BugTaskTableRowView, self).__init__(context, request)
        self.milestone_source = MilestoneVocabulary

    def canSeeTaskDetails(self):
        """Whether someone can see a task's status details.

        Return True if this is not a conjoined task, and the bug is
        not a duplicate, and a question was not made from this report.
        It is independent of whether they can *change* the status; you
        need to expand the details to see any milestone set.
        """
        assert self.is_conjoined_slave is not None, (
            'is_conjoined_slave should be set before rendering the page.')
        assert self.is_converted_to_question is not None, (
            'is_converted_to_question should be set before rendering the'
            ' page.')
        return (self.displayEditForm() and
                not self.is_conjoined_slave and
                self.context.bug.duplicateof is None and
                not self.is_converted_to_question)

    def getTaskRowCSSClass(self):
        """The appropriate CSS class for the row in the Affects table.

        Currently this consists solely of highlighting the current context.
        """
        bugtask = self.context
        if bugtask == getUtility(ILaunchBag).bugtask:
            return 'highlight'
        else:
            return None

    def shouldIndentTask(self):
        """Should this task be indented in the task listing on the bug page?

        Returns True or False.
        """
        return ISeriesBugTarget.providedBy(self.context.target)

    def taskLink(self):
        """Return the proper link to the bugtask whether it's editable."""
        user = getUtility(ILaunchBag).user
        bugtask = self.context
        if check_permission('launchpad.Edit', user):
            return canonical_url(bugtask) + "/+editstatus"
        else:
            return canonical_url(bugtask) + "/+viewstatus"

    def _getSeriesTargetNameHelper(self, bugtask):
        """Return the short name of bugtask's targeted series."""
        series = bugtask.distroseries or bugtask.productseries
        if not series:
            return None
        return series.name.capitalize()

    def getSeriesTargetName(self):
        """Get the series to which this task is targeted."""
        return self._getSeriesTargetNameHelper(self.context)

    def getConjoinedMasterName(self):
        """Get the conjoined master's name for displaying."""
        return self._getSeriesTargetNameHelper(self.context.conjoined_master)

    @property
    def bugtask_icon(self):
        """Which icon should be shown for the task, if any?"""
        return getAdapter(self.context, IPathAdapter, 'image').sprite_css()

    def displayEditForm(self):
        """Return true if the BugTask edit form should be shown."""
        # Hide the edit form when the bug is viewed in a CVE context
        return self.request.getNearest(ICveSet) == (None, None)

    @property
    def status_widget_items(self):
        """The available status items as JSON."""
        if self.user is not None:
            # We shouldn't have to build our vocabulary out of (item.title,
            # item) tuples -- iterating over an EnumeratedType gives us
            # ITokenizedTerms that we could use. However, the terms generated
            # by EnumeratedType have their name as the token and here we need
            # the title as the token for backwards compatibility.
            status_items = [
                (item.title, item) for item in BugTaskStatus.items
                if item not in (BugTaskStatus.UNKNOWN,
                                BugTaskStatus.EXPIRED)]

            disabled_items = [status for status in BugTaskStatus.items
                if not self.context.canTransitionToStatus(status, self.user)]

            items = vocabulary_to_choice_edit_items(
                SimpleVocabulary.fromItems(status_items),
                css_class_prefix='status',
                disabled_items=disabled_items)
        else:
            items = '[]'

        return items

    @property
    def importance_widget_items(self):
        """The available status items as JSON."""
        if self.user is not None:
            # We shouldn't have to build our vocabulary out of (item.title,
            # item) tuples -- iterating over an EnumeratedType gives us
            # ITokenizedTerms that we could use. However, the terms generated
            # by EnumeratedType have their name as the token and here we need
            # the title as the token for backwards compatibility.
            importance_items = [
                (item.title, item) for item in BugTaskImportance.items
                if item != BugTaskImportance.UNKNOWN]

            items = vocabulary_to_choice_edit_items(
                SimpleVocabulary.fromItems(importance_items),
                css_class_prefix='importance')
        else:
            items = '[]'

        return items

    @cachedproperty
    def _visible_milestones(self):
        """The visible milestones for this context."""
        return self.milestone_source(self.context).visible_milestones

    @property
    def milestone_widget_items(self):
        """The available milestone items as JSON."""
        if self.user is not None:
            items = vocabulary_to_choice_edit_items(
                self._visible_milestones,
                value_fn=lambda item: canonical_url(
                    item, request=IWebServiceClientRequest(self.request)))
            items.append({
                "name": "Remove milestone",
                "disabled": False,
                "value": None})
        else:
            items = '[]'

        return items

    @cachedproperty
    def target_has_milestones(self):
        """Are there any milestones we can target?

        We always look up all milestones, so there's no harm
        using len on the list here and avoid the COUNT query.
        """
        return len(self._visible_milestones) > 0

    def bugtask_canonical_url(self):
        """Return the canonical url for the bugtask."""
        return canonical_url(self.context)

    @property
    def user_can_edit_importance(self):
        """Can the user edit the Importance field?

        If yes, return True, otherwise return False.
        """
        return self.context.userCanEditImportance(self.user)

    @property
    def user_can_edit_assignee(self):
        """Can the user edit the Milestone field?

        If yes, return True, otherwise return False.
        """
        return self.user is not None

    @property
    def user_can_edit_milestone(self):
        """Can the user edit the Milestone field?

        If yes, return True, otherwise return False.
        """
        return self.context.userCanEditMilestone(self.user)

    @property
    def style_for_add_milestone(self):
        if self.context.milestone is None:
            return ''
        else:
            return 'display: none'

    @property
    def style_for_edit_milestone(self):
        if self.context.milestone is None:
            return 'display: none'
        else:
            return ''

    def js_config(self):
        """Configuration for the JS widgets on the row, JSON-serialized."""
        assignee_vocabulary = get_assignee_vocabulary(self.context)
        # Display the search field only if the user can set any person
        # or team
        user = getUtility(ILaunchBag).user
        hide_assignee_team_selection = (
            not self.context.userCanSetAnyAssignee(user) and
            (user is None or user.teams_participated_in.count() == 0))
        return dumps({
            'row_id': 'tasksummary%s' % self.context.id,
            'bugtask_path': '/'.join(
                [''] + canonical_url(self.context).split('/')[3:]),
            'prefix': get_prefix(self.context),
            'assignee_value': self.context.assignee
                and self.context.assignee.name,
            'assignee_is_team': self.context.assignee
                and self.context.assignee.is_team,
            'assignee_vocabulary': assignee_vocabulary,
            'hide_assignee_team_selection': hide_assignee_team_selection,
            'user_can_unassign': self.context.userCanUnassign(user),
            'target_is_product': IProduct.providedBy(self.context.target),
            'status_widget_items': self.status_widget_items,
            'status_value': self.context.status.title,
            'importance_widget_items': self.importance_widget_items,
            'importance_value': self.context.importance.title,
            'milestone_widget_items': self.milestone_widget_items,
            'milestone_value': (self.context.milestone and
                                canonical_url(
                                    self.context.milestone,
                                    request=IWebServiceClientRequest(
                                        self.request)) or
                                None),
            'user_can_edit_assignee': self.user_can_edit_assignee,
            'user_can_edit_milestone': self.user_can_edit_milestone,
            'user_can_edit_status': not self.context.bugwatch,
            'user_can_edit_importance': (
                self.user_can_edit_importance and
                not self.context.bugwatch)})


class BugsBugTaskSearchListingView(BugTaskSearchListingView):
    """Search all bug reports."""

    columns_to_show = ["id", "summary", "bugtargetdisplayname",
                       "importance", "status", "heat"]
    schema = IFrontPageBugTaskSearch
    custom_widget('scope', ProjectScopeWidget)
    page_title = 'Search'

    def initialize(self):
        """Initialize the view for the request."""
        BugTaskSearchListingView.initialize(self)
        if not self._isRedirected():
            self._redirectToSearchContext()

    def _redirectToSearchContext(self):
        """Check wether a target was given and redirect to it.

        All the URL parameters will be passed on to the target's +bugs
        page.

        If the target widget contains errors, redirect to the front page
        which will handle the error.
        """
        try:
            search_target = self.widgets['scope'].getInputValue()
        except InputErrors:
            query_string = self.request['QUERY_STRING']
            bugs_url = "%s?%s" % (canonical_url(self.context), query_string)
            self.request.response.redirect(bugs_url)
        else:
            if search_target is not None:
                query_string = self.request['QUERY_STRING']
                search_url = "%s/+bugs?%s" % (
                    canonical_url(search_target), query_string)
                self.request.response.redirect(search_url)

    def getSearchPageHeading(self):
        """Return the heading to search all Bugs."""
        return "Search all bug reports"

    @property
    def label(self):
        return self.getSearchPageHeading()


class BugTaskPrivacyAdapter:
    """Provides `IObjectPrivacy` for `IBugTask`."""

    implements(IObjectPrivacy)

    def __init__(self, context):
        self.context = context

    @property
    def is_private(self):
        """Return True if the bug is private, otherwise False."""
        return self.context.bug.private


class BugTaskCreateQuestionView(LaunchpadFormView):
    """View for creating a question from a bug."""
    schema = ICreateQuestionFromBugTaskForm

    def setUpFields(self):
        """See `LaunchpadFormView`."""
        LaunchpadFormView.setUpFields(self)
        if not self.can_be_a_question:
            self.form_fields = self.form_fields.omit('comment')

    @property
    def next_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    @property
    def can_be_a_question(self):
        """Return True if this bug can become a question, otherwise False."""
        return self.context.bug.canBeAQuestion()

    @action('Convert this Bug into a Question', name='create')
    def create_action(self, action, data):
        """Create a question from this bug and set this bug to Invalid.

        The bugtask's status will be set to Invalid. The question
        will be linked to this bug.

        A question will not be created if a question was previously created,
        the pillar does not use Launchpad to track bugs, or there is more
        than one valid bugtask.
        """
        if not self.context.bug.canBeAQuestion():
            self.request.response.addNotification(
                'This bug could not be converted into a question.')
            return

        comment = data.get('comment', None)
        self.context.bug.convertToQuestion(self.user, comment=comment)

    label = 'Convert this bug to a question'

    page_title = label


class BugTaskRemoveQuestionView(LaunchpadFormView):
    """View for creating a question from a bug."""
    schema = IRemoveQuestionFromBugTaskForm

    def setUpFields(self):
        """See `LaunchpadFormView`."""
        LaunchpadFormView.setUpFields(self)
        if not self.has_question:
            self.form_fields = self.form_fields.omit('comment')

    @property
    def next_url(self):
        """See `LaunchpadFormView`."""
        return canonical_url(self.context)

    @property
    def has_question(self):
        """Return True if a question was created from this bug, or False."""
        return self.context.bug.getQuestionCreatedFromBug() is not None

    @action('Convert Back to Bug', name='remove')
    def remove_action(self, action, data):
        """Remove a question from this bug.

        The question will be unlinked from the bug. The question is not
        altered in any other way; it belongs to the question workflow.
        The bug's bugtasks are editable, though none are changed. Bug
        supervisors are responsible for updating the bugtasks.
        """
        question = self.context.bug.getQuestionCreatedFromBug()
        if question is None:
            self.request.response.addNotification(
                'This bug does not have a question to remove')
            return

        owner_is_subscribed = question.isSubscribed(self.context.bug.owner)
        question.unlinkBug(self.context.bug)
        # The question.owner was implicitly unsubscribed when the bug
        # was unlinked. We resubscribe the owner if he was subscribed.
        if owner_is_subscribed is True:
            self.context.bug.subscribe(question.owner, self.user)
        self.request.response.addNotification(
            structured(
                'Removed Question #%s: <a href="%s">%s<a>.',
                str(question.id),
                canonical_url(question),
                question.title))

        comment = data.get('comment', None)
        if comment is not None:
            self.context.bug.newMessage(
                owner=getUtility(ILaunchBag).user,
                subject=self.context.bug.followup_subject(),
                content=comment)

    @property
    def label(self):
        return ('Bug #%i - Convert this question back to a bug'
                % self.context.bug.id)

    page_title = label


class BugTaskExpirableListingView(LaunchpadView):
    """View for listing Incomplete bugs that can expire."""

    @property
    def can_show_expirable_bugs(self):
        """Return True or False if expirable bug listing can be shown."""
        return target_has_expirable_bugs_listing(self.context)

    @property
    def inactive_expiration_age(self):
        """Return the number of days an bug must be inactive to expire."""
        return config.malone.days_before_expiration

    @property
    def columns_to_show(self):
        """Show the columns that summarise expirable bugs."""
        if (IDistribution.providedBy(self.context)
            or IDistroSeries.providedBy(self.context)):
            return [
                'id', 'summary', 'packagename', 'date_last_updated', 'heat']
        else:
            return ['id', 'summary', 'date_last_updated', 'heat']

    @property
    def search(self):
        """Return an `ITableBatchNavigator` for the expirable bugtasks."""
        days_old = config.malone.days_before_expiration
        bugtaskset = getUtility(IBugTaskSet)
        bugtasks = bugtaskset.findExpirableBugTasks(
            days_old, user=self.user, target=self.context)
        return BugListingBatchNavigator(
            bugtasks, self.request, columns_to_show=self.columns_to_show,
            size=config.malone.buglist_batch_size)

    @property
    def page_title(self):
        return "Bugs that can expire in %s" % self.context.title


class BugActivityItem:
    """A decorated BugActivity."""
    delegates(IBugActivity, 'activity')

    def __init__(self, activity):
        self.activity = activity

    @property
    def change_summary(self):
        """Return a formatted summary of the change."""
        if self.target is not None:
            # This is a bug task.  We want the attribute, as filtered out.
            return self.attribute
        else:
            # Otherwise, the attribute is more normalized than what we want.
            # Use "whatchanged," which sometimes is more descriptive.
            return self.whatchanged

    @property
    def _formatted_tags_change(self):
        """Return a tags change as lists of added and removed tags."""
        assert self.whatchanged == 'tags', (
            "Can't return a formatted tags change for a change in %s."
            % self.whatchanged)

        # Turn the strings of newvalue and oldvalue into sets so we
        # can work out the differences.
        if self.newvalue != '':
            new_tags = set(re.split('\s+', self.newvalue))
        else:
            new_tags = set()

        if self.oldvalue != '':
            old_tags = set(re.split('\s+', self.oldvalue))
        else:
            old_tags = set()

        added_tags = sorted(new_tags.difference(old_tags))
        removed_tags = sorted(old_tags.difference(new_tags))

        return_string = ''
        if len(added_tags) > 0:
            return_string = "added: %s\n" % ' '.join(added_tags)
        if len(removed_tags) > 0:
            return_string = (
                return_string + "removed: %s" % ' '.join(removed_tags))

        # Trim any leading or trailing \ns and then convert the to
        # <br />s so they're displayed correctly.
        return return_string.strip('\n')

    @property
    def change_details(self):
        """Return a detailed description of the change."""
        # Our default return dict. We may mutate this depending on
        # what's changed.
        return_dict = {
            'old_value': self.oldvalue,
            'new_value': self.newvalue,
            }
        attribute = self.attribute
        if attribute == 'title':
            # We display summary changes as a unified diff, replacing
            # \ns with <br />s so that the lines are separated properly.
            diff = cgi.escape(
                get_unified_diff(self.oldvalue, self.newvalue, 72), True)
            return diff.replace("\n", "<br />")

        elif attribute == 'description':
            # Description changes can be quite long, so we just return
            # 'updated' rather than returning the whole new description
            # or a diff.
            return 'updated'

        elif attribute == 'tags':
            # We special-case tags because we can work out what's been
            # added and what's been removed.
            return cgi.escape(self._formatted_tags_change).replace(
                '\n', '<br />')

        elif attribute == 'assignee':
            for key in return_dict:
                if return_dict[key] is None:
                    return_dict[key] = 'nobody'
                else:
                    return_dict[key] = cgi.escape(return_dict[key])

        elif attribute == 'milestone':
            for key in return_dict:
                if return_dict[key] is None:
                    return_dict[key] = 'none'
                else:
                    return_dict[key] = cgi.escape(return_dict[key])

        else:
            # Our default state is to just return oldvalue and newvalue.
            # Since we don't necessarily know what they are, we escape
            # them.
            for key in return_dict:
                return_dict[key] = cgi.escape(return_dict[key])

        return "%(old_value)s &#8594; %(new_value)s" % return_dict


class BugTaskBreadcrumb(Breadcrumb):
    """Breadcrumb for an `IBugTask`."""

    def __init__(self, context):
        super(BugTaskBreadcrumb, self).__init__(context)
        # If the user does not have permission to view the bug for
        # whatever reason, raise ComponentLookupError.
        try:
            context.bug.displayname
        except Unauthorized:
            raise ComponentLookupError()

    @property
    def text(self):
        return self.context.bug.displayname
