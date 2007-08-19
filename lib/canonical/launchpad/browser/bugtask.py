# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

"""IBugTask-related browser views."""

__metaclass__ = type

__all__ = [
    'get_comments_for_bugtask',
    'BugTargetTraversalMixin',
    'BugTaskNavigation',
    'BugTaskSetNavigation',
    'BugTaskContextMenu',
    'BugTaskEditView',
    'BugTaskPortletView',
    'BugTaskStatusView',
    'BugTaskListingView',
    'BugListingPortletView',
    'BugTaskSearchListingView',
    'BugNominationsView',
    'NominationsReviewTableBatchNavigatorView',
    'BugTaskTableRowView',
    'BugTargetView',
    'BugTasksAndNominationsView',
    'BugTaskView',
    'get_sortorder_from_request',
    'get_buglisting_search_filter_url',
    'BugTargetTextView',
    'BugListingBatchNavigator',
    'BugsBugTaskSearchListingView',
    'BugTaskSOP',
    ]

import cgi
import re
import urllib
from operator import attrgetter

from zope.app.form import CustomWidgetFactory
from zope.app.form.browser.itemswidgets import RadioWidget
from zope.app.form.interfaces import (
    IInputWidget, IDisplayWidget, InputErrors, WidgetsError)
from zope.app.form.utility import setUpWidget, setUpWidgets
from zope.component import getUtility, getMultiAdapter
from zope.event import notify
from zope.formlib import form
from zope.interface import implements, providedBy
from zope.schema import Choice
from zope.schema.interfaces import IList
from zope.schema.vocabulary import (
    getVocabularyRegistry, SimpleVocabulary, SimpleTerm)
from zope.security.proxy import isinstance as zope_isinstance

from canonical.config import config
from canonical.lp import dbschema, decorates
from canonical.launchpad import _
from canonical.cachedproperty import cachedproperty
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.webapp import (
    action, custom_widget, canonical_url, GetitemNavigation,
    LaunchpadEditFormView, LaunchpadFormView, LaunchpadView, Navigation,
    redirection, stepthrough)
from canonical.launchpad.webapp.uri import URI
from canonical.launchpad.interfaces import (
    IBug, IBugBranchSet, BugTaskSearchParams, IBugAttachmentSet,
    IBugExternalRefSet, IBugSet, IBugTask, IBugTaskSet, IBugTaskSearch,
    IDistribution, IDistributionSourcePackage,
    IDistroBugTask, IDistroSeries, IDistroSeriesBugTask,
    IFrontPageBugTaskSearch, ILaunchBag, INullBugTask, IPerson,
    IPersonBugTaskSearch, IProduct, IProject, ISourcePackage,
    IUpstreamBugTask, NotFoundError, RESOLVED_BUGTASK_STATUSES,
    UnexpectedFormData, UNRESOLVED_BUGTASK_STATUSES, validate_distrotask,
    valid_upstreamtask, IProductSeriesBugTask, IBugNominationSet,
    IProductSeries, INominationsReviewTableBatchNavigator)

from canonical.launchpad.searchbuilder import any, NULL

from canonical.launchpad import helpers

from canonical.launchpad.event.sqlobjectevent import SQLObjectModifiedEvent

from canonical.launchpad.browser.bug import BugContextMenu
from canonical.launchpad.browser.bugcomment import build_comments_from_chunks
from canonical.launchpad.browser.mentoringoffer import CanBeMentoredView
from canonical.launchpad.browser.launchpad import StructuralObjectPresentation

from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.batching import TableBatchNavigator
from canonical.launchpad.webapp.snapshot import Snapshot
from canonical.launchpad.webapp.tales import PersonFormatterAPI
from canonical.launchpad.webapp.vocabulary import vocab_factory

from canonical.lazr import EnumeratedType, Item
from canonical.lp.dbschema import BugTaskImportance, BugTaskStatus

from canonical.widgets.bug import BugTagsWidget
from canonical.widgets.bugtask import (
    AssigneeDisplayWidget, BugTaskAssigneeWidget, BugTaskBugWatchWidget,
    BugTaskSourcePackageNameWidget, DBItemDisplayWidget,
    NewLineToSpacesWidget, NominationReviewActionWidget)
from canonical.widgets.itemswidgets import LabeledMultiCheckBoxWidget
from canonical.widgets.project import ProjectScopeWidget


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


def get_comments_for_bugtask(bugtask, truncate=False):
    """Return BugComments related to a bugtask.

    This code builds a sorted list of BugComments in one shot,
    requiring only two database queries. It removes the titles
    for those comments which do not have a "new" subject line
    """
    chunks = bugtask.bug.getMessageChunks()
    comments = build_comments_from_chunks(chunks, bugtask, truncate=truncate)
    for attachment in bugtask.bug.attachments:
        message_id = attachment.message.id
        # All attachments are related to a message, so we can be
        # sure that the BugComment is already created.
        assert comments.has_key(message_id)
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
    return comments


def get_sortorder_from_request(request):
    """Get the sortorder from the request.

    >>> from zope.publisher.browser import TestRequest
    >>> get_sortorder_from_request(TestRequest(form={}))
    ['-importance']
    >>> get_sortorder_from_request(TestRequest(form={'orderby': '-status'}))
    ['-status']
    >>> get_sortorder_from_request(
    ...     TestRequest(form={'orderby': 'status,-severity,importance'}))
    ['status', 'importance']
    >>> get_sortorder_from_request(
    ...     TestRequest(form={'orderby': 'priority,-severity'}))
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
        NullBugTask will be returned.

        Raises NotFoundError if no bug with the given name is found.

        If the context type does provide IProduct, IDistribution,
        IDistroSeries, ISourcePackage or IDistributionSourcePackage
        a TypeError is raised.
        """
        context = self.context

        # Raises NotFoundError if no bug is found
        bug = getUtility(IBugSet).getByNameOrID(name)

        # Loop through this bug's tasks to try and find the appropriate task
        # for this context. We always want to return a task, whether or not
        # the user has the permission to see it so that, for example, an
        # anonymous user is presented with a login screen at the correct URL,
        # rather than making it look as though this task was "not found",
        # because it was filtered out by privacy-aware code.
        for bugtask in helpers.shortlist(bug.bugtasks):
            if bugtask.target == context:
                # Security proxy this object on the way out.
                return getUtility(IBugTaskSet).get(bugtask.id)

        # If we've come this far, it means that no actual task exists in this
        # context, so we'll return a null bug task. This makes it possible to,
        # for example, return a bug page for a context in which the bug hasn't
        # yet been reported.
        if IProduct.providedBy(context):
            null_bugtask = bug.getNullBugTask(product=context)
        elif IProductSeries.providedBy(context):
            null_bugtask = bug.getNullBugTask(productseries=context)
        elif IDistribution.providedBy(context):
            null_bugtask = bug.getNullBugTask(distribution=context)
        elif IDistributionSourcePackage.providedBy(context):
            null_bugtask = bug.getNullBugTask(
                distribution=context.distribution,
                sourcepackagename=context.sourcepackagename)
        elif IDistroSeries.providedBy(context):
            null_bugtask = bug.getNullBugTask(distroseries=context)
        elif ISourcePackage.providedBy(context):
            null_bugtask = bug.getNullBugTask(
                distroseries=context.distroseries,
                sourcepackagename=context.sourcepackagename)
        else:
            raise TypeError(
                "Unknown context type for bug task: %s" % repr(context))

        return null_bugtask


class BugTaskNavigation(Navigation):

    usedfor = IBugTask

    def traverse(self, name):
        # Are we traversing to the view or edit status page of the
        # bugtask? If so, and the task actually exists, return the
        # appropriate page. If the task doesn't yet exist (i.e. it's a
        # NullBugTask), then return a 404. In other words, the URL:
        #
        #   /products/foo/+bug/1/+viewstatus
        #
        # will return the +viewstatus page if bug 1 has actually been
        # reported in "foo". If bug 1 has not yet been reported in "foo",
        # a 404 will be returned.
        if name not in ("+viewstatus", "+editstatus"):
            # You're going in the wrong direction.
            return None
        if INullBugTask.providedBy(self.context):
            # The bug has not been reported in this context.
            return None
        # Yes! The bug has been reported in this context.
        return getMultiAdapter((self.context, self.request), name=name+"-page")

    @stepthrough('attachments')
    def traverse_attachments(self, name):
        if name.isdigit():
            return getUtility(IBugAttachmentSet)[name]

    @stepthrough('references')
    def traverse_references(self, name):
        if name.isdigit():
            return getUtility(IBugExternalRefSet)[name]

    @stepthrough('comments')
    def traverse_comments(self, name):
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
            return comments[index]
        except IndexError:
            return None

    @stepthrough('nominations')
    def traverse_nominations(self, nomination_id):
        if not nomination_id.isdigit():
            return None
        return getUtility(IBugNominationSet).get(nomination_id)

    redirection('references', '..')


class BugTaskSetNavigation(GetitemNavigation):

    usedfor = IBugTaskSet


class BugTaskContextMenu(BugContextMenu):
    usedfor = IBugTask


class BugTaskView(LaunchpadView, CanBeMentoredView):
    """View class for presenting information about an IBugTask."""

    def __init__(self, context, request):
        LaunchpadView.__init__(self, context, request)

        self.notices = []

        # Make sure we always have the current bugtask.
        if not IBugTask.providedBy(context):
            self.context = getUtility(ILaunchBag).bugtask
        else:
            self.context = context

    def initialize(self):
        """Set up the needed widgets."""
        bug = self.context.bug
        # See render() for how this flag is used.
        self._redirecting_to_bug_list = False

        if self.user is None:
            return

        # Set up widgets in order to handle subscription requests.
        if (bug.isSubscribed(self.user) or bug.isSubscribedToDupes(self.user)):
            subscription_terms = [
                SimpleTerm(
                    self.user, self.user.name, 'Unsubscribe me from this bug')]
        else:
            subscription_terms = [
                SimpleTerm(
                    self.user, self.user.name, 'Subscribe me to this bug')]
        for team in self.user.teams_participated_in:
            if (bug.isSubscribed(team) or bug.isSubscribedToDupes(team)):
                subscription_terms.append(
                    SimpleTerm(
                        team, team.name,
                        'Unsubscribe <a href="%s">%s</a> from this bug' % (
                            canonical_url(team), cgi.escape(team.displayname))))
        subscription_vocabulary = SimpleVocabulary(subscription_terms)
        person_field = Choice(
            __name__='subscription',
            vocabulary=subscription_vocabulary, required=True)
        self.subscription_widget = CustomWidgetFactory(RadioWidget)
        setUpWidget(
            self, 'subscription', person_field, IInputWidget, value=self.user)

        self.handleSubscriptionRequest()

    def userIsSubscribed(self):
        """Is the user subscribed to this bug?"""
        return (
            self.context.bug.isSubscribed(self.user) or
            self.context.bug.isSubscribedToDupes(self.user))

    def shouldShowUnsubscribeFromDupesWarning(self):
        """Should we warn the user about unsubscribing and duplicates?

        The warning should tell the user that, when unsubscribing, they
        will also be unsubscribed from dupes of this bug.
        """
        if self.userIsSubscribed():
            return True

        bug = self.context.bug
        for team in self.user.teams_participated_in:
            if bug.isSubscribed(team) or bug.isSubscribedToDupes(team):
                return True

        return False

    def render(self):
        # Prevent normal rendering when redirecting to the bug list
        # after unsubscribing from a private bug, because rendering the
        # bug page would raise Unauthorized errors!
        if self._redirecting_to_bug_list:
            return u''
        else:
            return LaunchpadView.render(self)

    def handleSubscriptionRequest(self):
        """Subscribe or unsubscribe the user from the bug, if requested."""
        if not self._isSubscriptionRequest():
            return

        subscription_person = self.subscription_widget.getInputValue()

        # 'subscribe' appears in the request whether the request is to
        # subscribe or unsubscribe. Since "subscribe someone else" is
        # handled by a different view we can assume that 'subscribe' +
        # current user as a parameter means "subscribe the current
        # user", and any other kind of 'subscribe' request actually
        # means "unsubscribe". (Yes, this *is* very confusing!)
        if ('subscribe' in self.request.form and
            (subscription_person == self.user)):
            self._handleSubscribe()
        else:
            self._handleUnsubscribe(subscription_person)

    def _isSubscriptionRequest(self):
        # Figure out if this looks like a request to
        # subscribe/unsubscribe
        return (
            self.user and
            self.request.method == 'POST' and
            'cancel' not in self.request.form and
            self.subscription_widget.hasValidInput())

    def _handleSubscribe(self):
        # Handle a subscribe request.
        self.context.bug.subscribe(self.user)
        self.notices.append("You have been subscribed to this bug.")

    def _handleUnsubscribe(self, user):
        # Handle an unsubscribe request.
        if user == self.user:
            self._handleUnsubscribeCurrentUser()
        else:
            self._handleUnsubscribeOtherUser(user)

    def _handleUnsubscribeCurrentUser(self):
        # Handle unsubscribing the current user, which requires special-casing
        # when the bug is private. The user must be unsubscribed from all dupes
        # too, or they would keep getting mail about this bug!

        # ** Important ** We call unsubscribeFromDupes() before
        # unsubscribe(), because if the bug is private, the current user
        # will be prevented from calling methods on the main bug after
        # they unsubscribe from it!
        unsubed_dupes = self.context.bug.unsubscribeFromDupes(self.user)
        self.context.bug.unsubscribe(self.user)

        self.request.response.addNotification(
            self._getUnsubscribeNotification(self.user, unsubed_dupes))

        if not check_permission("launchpad.View", self.context.bug):
            # Redirect the user to the bug listing, because they can no
            # longer see a private bug from which they've unsubscribed.
            self.request.response.redirect(
                canonical_url(self.context.target) + "/+bugs")
            self._redirecting_to_bug_list = True

    def _handleUnsubscribeOtherUser(self, user):
        # Handle unsubscribing someone other than the current user.
        assert user != self.user, (
            "Expected a user other than the currently logged-in user.")

        # We'll also unsubscribe the other user from dupes of this bug,
        # otherwise they'll keep getting this bug's mail.
        self.context.bug.unsubscribe(user)
        unsubed_dupes = self.context.bug.unsubscribeFromDupes(user)
        self.request.response.addNotification(
            self._getUnsubscribeNotification(user, unsubed_dupes))

    def _getUnsubscribeNotification(self, user, unsubed_dupes):
        """Construct and return the unsubscribe-from-bug feedback message.

        :user: The IPerson or ITeam that was unsubscribed from the bug.
        :unsubed_dupes: The list of IBugs that are dupes from which the
                        user was unsubscribed.
        """
        current_bug = self.context.bug
        current_user = self.user
        unsubed_dupes_msg_fragment = self._getUnsubscribedDupesMsgFragment(
            unsubed_dupes)

        if user == current_user:
            # Consider that the current user may have been "locked out"
            # of a bug if they unsubscribed themselves from a private
            # bug!
            if check_permission("launchpad.View", current_bug):
                # The user still has permission to see this bug, so no
                # special-casing needed.
                return (
                    "You have been unsubscribed from this bug%s." %
                    unsubed_dupes_msg_fragment)
            else:
                return (
                    "You have been unsubscribed from bug %d%s. You no "
                    "longer have access to this private bug.") % (
                        current_bug.id, unsubed_dupes_msg_fragment)
        else:
            return "%s has been unsubscribed from this bug%s." % (
                cgi.escape(user.displayname), unsubed_dupes_msg_fragment)

    def _getUnsubscribedDupesMsgFragment(self, unsubed_dupes):
        """Return the duplicates fragment of the unsubscription notification.

        This piece lists the duplicates from which the user was
        unsubscribed.
        """
        if not unsubed_dupes:
            return ""

        dupe_links = []
        for unsubed_dupe in unsubed_dupes:
            dupe_links.append(
                '<a href="%s" title="%s">#%d</a>' % (
                canonical_url(unsubed_dupe), unsubed_dupe.title,
                unsubed_dupe.id))
        dupe_links_string = ", ".join(dupe_links)

        num_dupes = len(unsubed_dupes)
        if num_dupes > 1:
            plural_suffix = "s"
        else:
            plural_suffix = ""

        return (
            " and %(num_dupes)d duplicate%(plural_suffix)s "
            "(%(dupe_links_string)s)") % ({
                'num_dupes': num_dupes,
                'plural_suffix': plural_suffix,
                'dupe_links_string': dupe_links_string})

    def _nominateBug(self, series):
        """Nominate the bug for the series and redirect to the bug page."""
        self.context.bug.addNomination(self.user, series)
        self.request.response.addInfoNotification(
            'This bug has been nominated to be fixed in %(target)s.',
            target=series.bugtargetdisplayname)
        self.request.response.redirect(canonical_url(self.context))

    def reportBugInContext(self):
        form = self.request.form
        fake_task = self.context
        if form.get("reportbug"):
            if self.isReportedInContext():
                self.notices.append(
                    "The bug is already reported in this context.")
                return
            # The user has requested that the bug be reported in this
            # context.
            if IUpstreamBugTask.providedBy(fake_task):
                # Create a real upstream task in this context.
                real_task = getUtility(IBugTaskSet).createTask(
                    bug=fake_task.bug, owner=getUtility(ILaunchBag).user,
                    product=fake_task.product)
            elif IDistroBugTask.providedBy(fake_task):
                # Create a real distro bug task in this context.
                real_task = getUtility(IBugTaskSet).createTask(
                    bug=fake_task.bug, owner=getUtility(ILaunchBag).user,
                    distribution=fake_task.distribution,
                    sourcepackagename=fake_task.sourcepackagename)
            elif IDistroSeriesBugTask.providedBy(fake_task):
                self._nominateBug(fake_task.distroseries)
                return
            elif IProductSeriesBugTask.providedBy(fake_task):
                self._nominateBug(fake_task.productseries)
                return
            else:
                raise TypeError(
                    "Unknown bug task type: %s" % repr(fake_task))

            self.context = real_task

            # Add an appropriate feedback message
            self.notices.append("Thank you for your bug report.")

    def isReportedInContext(self):
        """Is the bug reported in this context? Returns True or False.

        It considers a nominated bug to be reported.

        This is particularly useful for views that may render a
        NullBugTask.
        """
        params = BugTaskSearchParams(user=self.user, bug=self.context.bug)
        matching_bugtasks = self.context.target.searchTasks(params)
        if self.context.productseries is not None:
            nomination_target = self.context.productseries
        elif self.context.distroseries is not None:
            nomination_target = self.context.distroseries
        else:
            nomination_target = None
        if nomination_target is not None:
            try:
                nomination = self.context.bug.getNominationFor(
                    nomination_target)
            except NotFoundError:
                nomination = None
        else:
            nomination = None

        return nomination is not None or matching_bugtasks.count() > 0

    def isSeriesTargetableContext(self):
        """Is the context something that supports Series targeting?

        Returns True or False.
        """
        return (
            IDistroBugTask.providedBy(self.context) or
            IDistroSeriesBugTask.providedBy(self.context))

    @cachedproperty
    def comments(self):
        comments = get_comments_for_bugtask(self.context, truncate=True)
        assert len(comments) > 0, "A bug should have at least one comment."
        return comments

    def getBugCommentsForDisplay(self):
        """Return all the bug comments together with their index."""
        # The first comment is generally identical to the description,
        # and we include a special link to it in the template if it
        # isn't.
        comments = self.comments[1:]

        visible_comments = []
        previous_comment = None
        for comment in comments:
            # Omit comments that are identical to their previous
            # comment, which were probably produced by
            # double-submissions or user errors, and which don't add
            # anything useful to the bug itself.
            if previous_comment and previous_comment.isIdenticalTo(comment):
                continue
            visible_comments.append(comment)
            previous_comment = comment

        return visible_comments

    def wasDescriptionModified(self):
        """Return a boolean indicating whether the description was modified"""
        return self.comments[0].text_contents != self.context.bug.description

    @cachedproperty
    def bug_branches(self):
        """Filter out the bug_branch links to non-visible private branches."""
        bug_branches = []
        for bug_branch in self.context.bug.bug_branches:
            if check_permission('launchpad.View', bug_branch.branch):
                bug_branches.append(bug_branch)
        return bug_branches


class BugTaskPortletView:
    def alsoReportedIn(self):
        """Return a list of IUpstreamBugTasks in which this bug is reported.

        If self.context is an IUpstreamBugTasks, it will be excluded
        from this list.
        """
        return [
            task for task in self.context.bug.bugtasks
            if task.id is not self.context.id]


class BugTaskEditView(LaunchpadEditFormView):
    """The view class used for the task +editstatus page."""

    schema = IBugTask

    # The field names that we use by default. This list will be mutated
    # depending on the current context and the permissions of the user viewing
    # the form.
    default_field_names = ['assignee', 'bugwatch', 'importance', 'milestone',
                           'product', 'sourcepackagename', 'status',
                           'statusexplanation']
    custom_widget('sourcepackagename', BugTaskSourcePackageNameWidget)
    custom_widget('bugwatch', BugTaskBugWatchWidget)
    custom_widget('assignee', BugTaskAssigneeWidget)

    @cachedproperty
    def field_names(self):
        field_names = list(self.default_field_names)

        # The fields that we present to the users change based upon the
        # current context and the user's permissions, so we update field_names
        # with any fields that may need to be added.
        for field in self.editable_field_names:
            if field not in field_names:
                field_names.append(field)

        return field_names

    @cachedproperty
    def editable_field_names(self):
        """Return the names of fields the user has permission to edit."""
        if self.context.target_uses_malone:
            # Don't edit self.field_names directly, because it's shared by all
            # BugTaskEditView instances.
            editable_field_names = list(self.default_field_names)

            if 'bugwatch' in editable_field_names:
                editable_field_names.remove('bugwatch')

            # XXX, Brad Bollenbach, 2006-09-29: Permission checking
            # doesn't belong here! See https://launchpad.net/bugs/63000
            if (not self.userCanEditMilestone() and
                'milestone' in editable_field_names):
                editable_field_names.remove("milestone")

            if (not self.userCanEditImportance() and
                'importance' in editable_field_names):
                editable_field_names.remove("importance")
        else:
            editable_field_names = ['bugwatch']
            if not IUpstreamBugTask.providedBy(self.context):
                #XXX: Bjorn Tillenius 2006-03-01:
                #     Should be possible to edit the product as well,
                #     but that's harder due to complications with bug
                #     watches. The new product might use Launchpad
                #     officially, thus we need to handle that case.
                #     Let's deal with that later.
                editable_field_names += ['sourcepackagename']
            if self.context.bugwatch is None:
                editable_field_names += ['status', 'assignee']
                if ('importance' in self.default_field_names
                    and self.userCanEditImportance()):
                    editable_field_names += ["importance"]

        return editable_field_names

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
        parts = []
        if IUpstreamBugTask.providedBy(self.context):
            parts.append(self.context.product.name)

        elif IProductSeriesBugTask.providedBy(self.context):
            parts.append(self.context.productseries.name)
            parts.append(self.context.productseries.product.name)

        elif IDistroBugTask.providedBy(self.context):
            parts.append(self.context.distribution.name)
            if self.context.sourcepackagename is not None:
                parts.append(self.context.sourcepackagename.name)

        elif IDistroSeriesBugTask.providedBy(self.context):
            parts.append(self.context.distroseries.distribution.name)
            parts.append(self.context.distroseries.name)

            if self.context.sourcepackagename is not None:
                parts.append(self.context.sourcepackagename.name)

        else:
            raise AssertionError("Unknown IBugTask: %r" % self.context)
        return '_'.join(parts)

    def setUpFields(self):
        """Sets up the fields for the bug task edit form.

        See `LaunchpadFormView`.
        """
        super(BugTaskEditView, self).setUpFields()
        read_only_field_names = self._getReadOnlyFieldNames()

        # The status field is a special case because we alter the vocabulary
        # it uses based on the permissions of the user viewing form.
        if 'status' in self.editable_field_names:
            if self.user is None:
                status_noshow = list(BugTaskStatus.items)
            else:
                status_noshow = [BugTaskStatus.UNKNOWN]
                status_noshow.extend(
                    status for status in BugTaskStatus.items
                    if not self.context.canTransitionToStatus(
                        status, self.user))

            if self.context.status in status_noshow:
                # The user has to be able to see the current value.
                status_noshow.remove(self.context.status)

            status_vocab_factory = vocab_factory(
                BugTaskStatus, noshow=status_noshow)
            status_field = Choice(
                __name__='status',
                title=self.schema['status'].title,
                vocabulary=status_vocab_factory(self.context))

            self.form_fields = self.form_fields.omit('status')
            self.form_fields += form.Fields(status_field)

        for field in read_only_field_names:
            self.form_fields[field].for_display = True

        # In cases where the status or importance fields are read only we give
        # them a custom widget so that they are rendered correctly.
        for field in ['status', 'importance']:
            if field in read_only_field_names:
                self.form_fields[field].custom_widget = CustomWidgetFactory(
                    DBItemDisplayWidget)

        if self.context.target_uses_malone:
            self.form_fields = self.form_fields.omit('bugwatch')

        elif (self.context.bugwatch is not None and
            self.form_fields.get('assignee', False)):
            self.form_fields['assignee'].custom_widget = CustomWidgetFactory(
                AssigneeDisplayWidget)

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
        product_or_distro = self._getProductOrDistro()

        return (
            ((product_or_distro.bugcontact and
                 self.user and
                 self.user.inTeam(product_or_distro.bugcontact)) or
                check_permission("launchpad.Edit", product_or_distro)))

    def userCanEditImportance(self):
        """Can the user edit the Importance field?

        If yes, return True, otherwise return False.
        """
        product_or_distro = self._getProductOrDistro()

        return (
            ((product_or_distro.bugcontact and
                 self.user and
                 self.user.inTeam(product_or_distro.bugcontact)) or
                check_permission("launchpad.Edit", product_or_distro)))

    def _getProductOrDistro(self):
        """Return the product or distribution relevant to the context."""
        bugtask = self.context
        if IUpstreamBugTask.providedBy(bugtask):
            return bugtask.product
        elif IProductSeriesBugTask.providedBy(bugtask):
            return bugtask.productseries.product
        elif IDistroBugTask.providedBy(bugtask):
            return bugtask.distribution
        else:
            return bugtask.distroseries.distribution

    def validate(self, data):
        """See `LaunchpadFormView`."""
        bugtask = self.context
        if bugtask.distroseries is not None:
            distro = bugtask.distroseries.distribution
        else:
            distro = bugtask.distribution
        sourcename = bugtask.sourcepackagename
        product = bugtask.product

        if distro is not None and sourcename != data.get('sourcepackagename'):
            try:
                validate_distrotask(
                    bugtask.bug, distro, data.get('sourcepackagename'))
            except LaunchpadValidationError, error:
                self.setFieldError('sourcepackagename', str(error))

        if (product is not None and 'product' in data and
            product != data.get('product')):
            try:
                valid_upstreamtask(bugtask.bug, data.get('product'))
            except WidgetsError, errors:
                self.setFieldError('product', errors.args[0])

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
            bugtask.bug.subscribe(self.user)
            self.request.response.addNotification(
                "You have been subscribed to this bug.")

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
        milestone_cleared = None
        milestone_ignored = False
        if (IUpstreamBugTask.providedBy(bugtask) and
            (bugtask.product != new_values.get("product")) and
            'milestone' in field_names):
            # We clear the milestone value if one was already set. We ignore
            # the milestone value if it was currently None, and the user tried
            # to set a milestone value while also changing the product. This
            # allows us to provide slightly clearer feedback messages.
            if bugtask.milestone:
                milestone_cleared = bugtask.milestone
            elif new_values.get('milestone') is not None:
                milestone_ignored = True

            bugtask.milestone = None
            # Remove the "milestone" field from the list of fields
            # whose changes we want to apply, because we don't want
            # the form machinery to try and set this value back to
            # what it was!
            del data_to_apply["milestone"]

        # We special case setting assignee and status, because there's
        # a workflow associated with changes to these fields.
        if "assignee" in data_to_apply:
            del data_to_apply["assignee"]
        if "status" in data_to_apply:
            del data_to_apply["status"]

        # We grab the comment_on_change field before we update bugtask so as
        # to avoid problems accessing the field if the user has changed the
        # product of the BugTask.
        comment_on_change = self.request.form.get(
            "%s.comment_on_change" % self.prefix)

        changed = form.applyChanges(
            bugtask, self.form_fields, data_to_apply, self.adapters)

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

        # Set the "changed" flag properly, just in case status and/or assignee
        # happen to be the only values that changed. We explicitly verify that
        # we got a new status and/or assignee, because our test suite doesn't
        # always pass all form values.
        new_status = new_values.pop("status", False)
        new_assignee = new_values.pop("assignee", False)
        if ((new_status is not False) and
            (bugtask.status != new_status)):
            changed = True
            bugtask.transitionToStatus(new_status, self.user)

        if ((new_assignee is not False) and
            (bugtask.assignee != new_assignee)):
            changed = True
            bugtask.transitionToAssignee(new_assignee)

        if bugtask_before_modification.bugwatch != bugtask.bugwatch:
            if bugtask.bugwatch is None:
                # Reset the status and importance to the default values,
                # since Unknown isn't selectable in the UI.
                bugtask.transitionToStatus(
                    IBugTask['status'].default, self.user)
                bugtask.importance = IBugTask['importance'].default
            else:
                #XXX: Bjorn Tillenius 2006-03-01:
                #     Reset the bug task's status information. The right
                #     thing would be to convert the bug watch's status to a
                #     Launchpad status, but it's not trivial to do at the
                #     moment. I will fix this later.
                bugtask.transitionToStatus(
                    BugTaskStatus.UNKNOWN, self.user)
                bugtask.importance = BugTaskImportance.UNKNOWN
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
                SQLObjectModifiedEvent(
                    object=bugtask,
                    object_before_modification=bugtask_before_modification,
                    edited_fields=field_names))

        if bugtask.sourcepackagename is not None:
            real_package_name = bugtask.sourcepackagename.name

            # We get entered_package_name directly from the form here, since
            # validating the sourcepackagename field mutates its value in to
            # the one already in real_package_name, which makes our comparison
            # of the two below useless.
            entered_package_name = self.request.form.get(
                self.widgets['sourcepackagename'].name)

            if real_package_name != entered_package_name:
                # The user entered a binary package name which got
                # mapped to a source package.
                self.request.response.addNotification(
                    "'%(entered_package)s' is a binary package. This bug has"
                    " been assigned to its source package '%(real_package)s'"
                    " instead." %
                    {'entered_package': entered_package_name,
                     'real_package': real_package_name})

        if (bugtask_before_modification.sourcepackagename !=
            bugtask.sourcepackagename):
            # The source package was changed, so tell the user that we've
            # subscribed the new bug contacts.
            self.request.response.addNotification(
                "The bug contacts for %s have been subscribed to this bug." % (
                    bugtask.bugtargetdisplayname))

    @action('Save Changes', name='save')
    def save_action(self, action, data):
        self.updateContextFromData(data)


class BugTaskStatusView(LaunchpadView):
    """Viewing the status of a bug task."""

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

        if not IUpstreamBugTask.providedBy(self.context):
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
        """Return an HTML representation of the bugtask status and assignee."""
        bugtask = self.context

        if INullBugTask.providedBy(bugtask):
            return u"Not reported in %s" % bugtask.bugtargetname

        assignee = bugtask.assignee
        status = bugtask.status
        status_title = status.title.capitalize()

        if not assignee:
            return status_title + ' (unassigned)'

        assignee_html = PersonFormatterAPI(assignee).link('+assignedbugs')

        if status in (dbschema.BugTaskStatus.INVALID,
                      dbschema.BugTaskStatus.FIXCOMMITTED):
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


class BugListingPortletView(LaunchpadView):
    """Portlet containing all available bug listings."""
    def getOpenBugsURL(self):
        """Return the URL for open bugs on this bug target."""
        return get_buglisting_search_filter_url(
            self.request.URL,
            status=[status.title for status in UNRESOLVED_BUGTASK_STATUSES])

    def getBugsAssignedToMeURL(self):
        """Return the URL for bugs assigned to the current user on target."""
        if self.user:
            return get_buglisting_search_filter_url(
                self.request.URL, assignee=self.user.name)
        else:
            return str(self.request.URL) + "/+login"

    def getBugsAssignedToMeCount(self):
        assert self.user, (
            "Counting 'bugs assigned to me' requires a logged-in user")

        search_params = BugTaskSearchParams(
            user=self.user, assignee=self.user,
            status=any(*UNRESOLVED_BUGTASK_STATUSES),
            omit_dupes=True)

        return self.context.searchTasks(search_params).count()

    def getCriticalBugsURL(self):
        """Return the URL for critical bugs on this bug target."""
        return get_buglisting_search_filter_url(
            self.request.URL,
            status=[status.title for status in UNRESOLVED_BUGTASK_STATUSES],
            importance=dbschema.BugTaskImportance.CRITICAL.title)

    def getUnassignedBugsURL(self):
        """Return the URL for critical bugs on this bug target."""
        unresolved_tasks_query_string = get_buglisting_search_filter_url(
            self.request.URL,
            status=[status.title for status in UNRESOLVED_BUGTASK_STATUSES])

        return unresolved_tasks_query_string + "&assignee_option=none"

    def getNewBugsURL(self):
        """Return the URL for new bugs on this bug target."""
        return get_buglisting_search_filter_url(
            self.request.URL, status=dbschema.BugTaskStatus.NEW.title)

    def getAllBugsEverReportedURL(self):
        all_statuses = UNRESOLVED_BUGTASK_STATUSES + RESOLVED_BUGTASK_STATUSES
        all_status_query_string = get_buglisting_search_filter_url(
            self.request.URL, status=[status.title for status in all_statuses])

        # Add the bit that simulates the "omit dupes" checkbox being unchecked.
        return all_status_query_string + "&field.omit_dupes.used="


def get_buglisting_search_filter_url(
        url, assignee=None, importance=None, status=None):
    """Return the given URL with the search parameters specified."""
    search_params = []

    if assignee:
        search_params.append(('field.assignee', assignee))
    if importance:
        search_params.append(('field.importance', importance))
    if status:
        search_params.append(('field.status', status))

    query_string = urllib.urlencode(search_params, doseq=True)

    search_filter_url = str(url) + "?search=Search"
    if query_string:
        search_filter_url += "&" + query_string

    return search_filter_url


def getInitialValuesFromSearchParams(search_params, form_schema):
    """Build a dictionary that can be given as initial values to
    setUpWidgets, based on the given search params.

    >>> initial = getInitialValuesFromSearchParams(
    ...     {'status': any(*UNRESOLVED_BUGTASK_STATUSES)}, IBugTaskSearch)
    >>> [status.name for status in initial['status']]
    ['NEW', 'INCOMPLETE', 'CONFIRMED', 'TRIAGED', 'INPROGRESS', 'FIXCOMMITTED']

    >>> initial = getInitialValuesFromSearchParams(
    ...     {'status': dbschema.BugTaskStatus.INVALID}, IBugTaskSearch)
    >>> [status.name for status in initial['status']]
    ['INVALID']

    >>> initial = getInitialValuesFromSearchParams(
    ...     {'importance': [dbschema.BugTaskImportance.CRITICAL,
    ...                   dbschema.BugTaskImportance.HIGH]}, IBugTaskSearch)
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
    decorates(IBugTask, 'bugtask')

    def __init__(self, bugtask, bugbranches):
        self.bugtask = bugtask
        self.bugbranches = bugbranches
        self.review_action_widget = None


class BugListingBatchNavigator(TableBatchNavigator):
    """A specialised batch navigator to load smartly extra bug information."""

    def __init__(self, tasks, request, columns_to_show, size):
        TableBatchNavigator.__init__(
            self, tasks, request, columns_to_show=columns_to_show, size=size)
        # Now load the bug-branch links for this batch
        bugbranches = getUtility(IBugBranchSet).getBugBranchesForBugTasks(
            self.currentBatch())
        # Create a map from the bug id to the branches.
        self.bug_id_mapping = {}
        for bugbranch in bugbranches:
            if check_permission('launchpad.View', bugbranch.branch):
                self.bug_id_mapping.setdefault(
                    bugbranch.bug.id, []).append(bugbranch)

    def _getListingItem(self, bugtask):
        """Return a decorated bugtask for the bug listing."""
        return BugTaskListingItem(
            bugtask, self.bug_id_mapping.get(bugtask.bug.id, None))

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
        BugListingBatchNavigator.__init__(self, tasks, request, columns_to_show, size)
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
            __name__='review_action_%d' % (bug_nomination.id,),
            vocabulary=NominatedBugReviewAction,
            title=u'Review action', required=True)

        # This is so setUpWidget expects a view, and so
        # view.request. We're not passing a view but we still want it
        # to work.
        bugtask_listing_item.request = self.request

        bugtask_listing_item.review_action_widget = CustomWidgetFactory(
            NominationReviewActionWidget)
        setUpWidget(
            bugtask_listing_item, 'review_action', review_action_field, IInputWidget,
            value=NominatedBugReviewAction.NO_CHANGE, context=bug_nomination)

        return bugtask_listing_item


class BugTaskSearchListingView(LaunchpadFormView):
    """Base class for bug listings."""

    # These widgets are customised so as to keep the presentation of this view
    # and its descendants consistent after refactoring to use
    # LaunchpadFormView as a parent.
    custom_widget('searchtext', NewLineToSpacesWidget)
    custom_widget('status_upstream', LabeledMultiCheckBoxWidget)
    custom_widget('tag', BugTagsWidget)
    custom_widget('component', LabeledMultiCheckBoxWidget)

    @property
    def schema(self):
        if self._personContext():
            return IPersonBugTaskSearch
        else:
            return IBugTaskSearch

    def initialize(self):
        # Look for old status names and redirect to a new location if
        # found.
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
            return ["id", "summary", "importance", "status"]
        elif distribution_context or distroseries_context:
            return ["id", "summary", "packagename", "importance", "status"]
        elif project_context:
            return ["id", "summary", "productname", "importance", "status"]
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
            if self.getWidgetError(field_name):
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

    def _getDefaultSearchParams(self):
        """Return a BugTaskSearchParams instance with default values.

        By default, a search includes any bug that is unresolved and not
        a duplicate of another bug.
        """
        search_params = BugTaskSearchParams(
            user=self.user, status=any(*UNRESOLVED_BUGTASK_STATUSES),
            omit_dupes=True)
        search_params.orderby = get_sortorder_from_request(self.request)
        return search_params

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
                data["attachmenttype"] = dbschema.BugAttachmentType.PATCH

            # Filter appropriately if the user wants to restrict the
            # search to only bugs with no package information.
            has_no_package = data.pop("has_no_package", False)
            if has_no_package:
                data["sourcepackagename"] = NULL

        self._buildUpstreamStatusParams(data)

        # "Normalize" the form data into search arguments.
        form_values = {}
        for key, value in data.items():
            if zope_isinstance(value, (list, tuple)):
                if len(value) > 0:
                    form_values[key] = any(*value)
            else:
                form_values[key] = value

        search_params = self._getDefaultSearchParams()
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
            size=config.malone.buglist_batch_size)

    def search(self, searchtext=None, context=None, extra_params=None):
        """Return an ITableBatchNavigator for the GET search criteria.

        If :searchtext: is None, the searchtext will be gotten from the
        request.

        :extra_params: is a dict that provides search params added to the
        search criteria taken from the request. Params in :extra_params: take
        precedence over request params.
        """
        # Base classes can provide an explicit search context.
        if not context:
            context = self.context

        search_params = self.buildSearchParams(
            searchtext=searchtext, extra_params=extra_params)
        tasks = context.searchTasks(search_params)
        return self._getBatchNavigator(tasks)

    def getWidgetValues(self, vocabulary_name, default_values=()):
        """Return data used to render a field's widget."""
        widget_values = []

        vocabulary_registry = getVocabularyRegistry()
        for term in vocabulary_registry.get(self.context, vocabulary_name):
            widget_values.append(
                dict(
                    value=term.token, title=term.title or term.token,
                    checked=term.value in default_values))

        return helpers.shortlist(widget_values, longest_expected=10)

    def getStatusWidgetValues(self):
        """Return data used to render the status checkboxes."""
        return self.getWidgetValues(
            vocabulary_name="BugTaskStatus",
            default_values=UNRESOLVED_BUGTASK_STATUSES)

    def getImportanceWidgetValues(self):
        """Return data used to render the Importance checkboxes."""
        return self.getWidgetValues("BugTaskImportance")

    def getMilestoneWidgetValues(self):
        """Return data used to render the milestone checkboxes."""
        return self.getWidgetValues("Milestone")

    def getAdvancedSearchPageHeading(self):
        """The header for the advanced search page."""
        return "Bugs in %s: Advanced search" % self.context.displayname

    def getSimpleSearchURL(self):
        """Return a URL that can be used as an href to the simple search."""
        return canonical_url(self.context) + "/+bugs"

    def shouldShowAssigneeWidget(self):
        """Should the assignee widget be shown on the advanced search page?"""
        return True

    def shouldShowCommenterWidget(self):
        """Should the commenter widget be shown on the advanced search page?"""
        return True

    def shouldShowComponentWidget(self):
        """Should the component widget be shown on the advanced search page?"""
        context = self.context
        return (
            (IDistribution.providedBy(context) and
             context.currentseries is not None) or
            IDistroSeries.providedBy(context) or
            ISourcePackage.providedBy(context))

    def shouldShowContactWidget(self):
        """Should the contact widget be shown on the advanced search page?"""
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

    def shouldShowReleaseCriticalPortlet(self):
        """Should the page include a portlet showing release-critical bugs
        for different series.
        """
        return (
            IDistribution.providedBy(self.context) and self.context.serieses or
            IDistroSeries.providedBy(self.context) or
            IProduct.providedBy(self.context) and self.context.serieses or
            IProductSeries.providedBy(self.context))

    def shouldShowSubscriberWidget(self):
        """Should the subscriber widget be shown on the advanced search page?"""
        return True

    def shouldShowUpstreamStatusBox(self):
        """Should the upstream status filtering widgets be shown?"""
        return not (
            IProduct.providedBy(self.context) or
            IProject.providedBy(self.context))

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
                    {fieldname : fieldvalue}, doseq=True)

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
        if (self.request.form.get('advanced')
            or self.form_has_errors):
            return True
        else:
            return False

    @property
    def form_has_errors(self):
        return len(self.errors) > 0

    def validateVocabulariesAdvancedForm(self):
        """Provides a meaningful message for vocabulary validation errors."""
        error_message = _(
            "There's no person with the name or email address '%s'.")

        for name in ('assignee', 'bug_reporter', 'bug_contact',
                     'bug_commenter', 'subscriber'):
            if self.getWidgetError(name):
                self.setFieldError(
                    name, error_message %
                        cgi.escape(self.request.get('field.%s' % name)))

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

        Return the IProject if yes, otherwise return None.
        """
        return IProject(self.context, None)

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
        """Is this page being viewed in a [distroseries] sourcepackage context?

        Return the ISourcePackage if yes, otherwise return None.
        """
        return ISourcePackage(self.context, None)

    def _distroSourcePackageContext(self):
        """Is this page being viewed in a distribution sourcepackage context?

        Return the IDistributionSourcePackage if yes, otherwise return None.
        """
        return IDistributionSourcePackage(self.context, None)

    def getBugsFixedElsewhereInfo(self):
        """Return a dict with count and URL of bugs fixed elsewhere."""
        params = self._getDefaultSearchParams()
        params.resolved_upstream = True
        fixed_elsewhere = self.context.searchTasks(params)
        search_url = (
            "%s/+bugs?field.status_upstream=resolved_upstream" %
                canonical_url(self.context))
        return dict(count=fixed_elsewhere.count(), url=search_url)

    def getOpenCVEBugsInfo(self):
        """Return a dict with count and URL of open bugs linked to CVEs."""
        params = self._getDefaultSearchParams()
        params.has_cve = True
        open_cve_bugs = self.context.searchTasks(params)
        search_url = (
            "%s/+bugs?field.has_cve=on" % canonical_url(self.context))
        return dict(count=open_cve_bugs.count(), url=search_url)


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
        self.widgets = form.Widgets(widgets_list, len(self.prefix)+1)

    @action('Save changes', name='submit',
            condition=canApproveNominations)
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
                    'Unknown NominatedBugReviewAction: %r' % (
                        review_action,))

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
        return self.context.searchTasks(params)[:limit]



class BugTargetTextView(LaunchpadView):
    """View for simple text page showing bugs filed against a bug target."""

    def render(self):
        self.request.response.setHeader('Content-type', 'text/plain')
        tasks = self.context.searchTasks(BugTaskSearchParams(self.user))

        # We use task.bugID rather than task.bug.id here as the latter
        # would require an extra query per task.
        return u''.join('%d\n' % task.bugID for task in tasks)


def _by_targetname(bugtask):
    """Normalize the bugtask.targetname, for sorting."""
    return re.sub(r"\W", "", bugtask.bugtargetdisplayname)

class BugTasksAndNominationsView(LaunchpadView):
    """Browser class for rendering the bugtasks and nominations table."""

    def __init__(self, context, request):
        """Ensure we always have a bug context."""
        LaunchpadView.__init__(self, IBug(context), request)

    def getBugTasksAndNominations(self):
        """Return the IBugTasks and IBugNominations associated with this bug.

        Returns a list, sorted by targetname, with upstream tasks sorted
        before distribution tasks, and nominations sorted after
        tasks. Approved nominations are not included in the returned
        results.
        """
        bug = self.context
        bugtasks = helpers.shortlist(bug.bugtasks)

        upstream_tasks = [
            bugtask for bugtask in bugtasks
            if bugtask.product or bugtask.productseries]

        distro_tasks = [
            bugtask for bugtask in bugtasks
            if bugtask.distribution or bugtask.distroseries]

        upstream_tasks.sort(key=_by_targetname)
        distro_tasks.sort(key=_by_targetname)

        all_bugtasks = upstream_tasks + distro_tasks

        # Insert bug nominations in between the appropriate tasks.
        bugtasks_and_nominations = []
        for bugtask in all_bugtasks:
            bugtasks_and_nominations.append(bugtask)

            target = bugtask.product or bugtask.distribution
            if not target:
                continue

            bugtasks_and_nominations += [
                nomination for nomination in bug.getNominations(target)
                if (nomination.status !=
                    dbschema.BugNominationStatus.APPROVED)
                ]

        return bugtasks_and_nominations

    def currentBugTask(self):
        """Return the current IBugTask.

        'current' is determined by simply looking in the ILaunchBag utility.
        """
        return getUtility(ILaunchBag).bugtask


class BugTaskTableRowView(LaunchpadView):
    """Browser class for rendering a bugtask row on the bug page."""

    def canSeeTaskDetails(self):
        """Whether someone can see a task's status details.

        This returns true if this is not a conjoined task, and if the bug is
        not a duplicate. It is independent of whether they can *change* the
        status; you need to expand the details to see any milestone set.
        """
        return (self.context.conjoined_master is None and
                self.context.bug.duplicateof is None)

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
        bugtask = self.context
        return (IDistroSeriesBugTask.providedBy(bugtask) or
                IProductSeriesBugTask.providedBy(bugtask))

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
        if IDistroSeriesBugTask.providedBy(bugtask):
            return bugtask.distroseries.name.capitalize()
        elif IProductSeriesBugTask.providedBy(bugtask):
            return bugtask.productseries.name.capitalize()
        else:
            assert (
                "Expected IDistroSeriesBugTask or IProductSeriesBugTask. "
                "Got: %r" % bugtask)

    def getSeriesTargetName(self):
        """Get the series to which this task is targeted."""
        return self._getSeriesTargetNameHelper(self.context)

    def getConjoinedMasterName(self):
        """Get the conjoined master's name for displaying."""
        return self._getSeriesTargetNameHelper(self.context.conjoined_master)

    @property
    def bugtask_icon(self):
        """Which icon should be shown for the task, if any?"""
        if IDistroBugTask.providedBy(self.context):
            if self.context.sourcepackagename:
                return "/@@/package-source"
            else:
                return "/@@/distribution"
        elif IUpstreamBugTask.providedBy(self.context):
            return "/@@/product"
        else:
            return None


class BugsBugTaskSearchListingView(BugTaskSearchListingView):
    """Search all bug reports."""

    columns_to_show = ["id", "summary", "bugtargetdisplayname",
                       "importance", "status"]
    schema = IFrontPageBugTaskSearch
    custom_widget('scope', ProjectScopeWidget)

    def initialize(self):
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
        return "Search all bug reports"


class BugTaskSOP(StructuralObjectPresentation):

    def getIntroHeading(self):
        return None

    def getMainHeading(self):
        bugtask = self.context
        if INullBugTask.providedBy(bugtask):
            return 'Bug #%s is not in %s' % (
                bugtask.bug.id, bugtask.bugtargetdisplayname)
        else:
            return 'Bug #%s in %s' % (
                bugtask.bug.id, bugtask.bugtargetdisplayname)

    def listChildren(self, num):
        return []

    def listAltChildren(self, num):
        return None

