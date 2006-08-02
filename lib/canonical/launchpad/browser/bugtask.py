# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""IBugTask-related browser views."""

__metaclass__ = type

__all__ = [
    'get_comments_for_bugtask',
    'BugNominationView',
    'BugTargetTraversalMixin',
    'BugTaskNavigation',
    'BugTaskSetNavigation',
    'BugTaskContextMenu',
    'BugTaskEditView',
    'BugTaskPortletView',
    'BugTaskStatusView',
    'BugListingPortletView',
    'BugTaskSearchListingView',
    'BugTargetView',
    'BugTaskView',
    'BugTaskBackportView',
    'get_sortorder_from_request',
    'BugTargetTextView',
    'upstream_status_vocabulary_factory']

import cgi
import urllib
from operator import attrgetter

from zope.app.form import CustomWidgetFactory
from zope.app.form.browser.itemswidgets import MultiCheckBoxWidget, RadioWidget
from zope.app.form.interfaces import IInputWidget, IDisplayWidget, WidgetsError
from zope.app.form.utility import (
    setUpWidget, setUpWidgets, setUpDisplayWidgets, getWidgetsData,
    applyWidgetsChanges)
from zope.component import getUtility, getView
from zope.event import notify
from zope.interface import providedBy
from zope.schema import Choice
from zope.schema.interfaces import IList
from zope.schema.vocabulary import (
    getVocabularyRegistry, SimpleVocabulary, SimpleTerm)
from zope.security.proxy import isinstance as zope_isinstance

from canonical.config import config
from canonical.lp import dbschema
from canonical.launchpad import _
from canonical.launchpad.webapp import (
    canonical_url, GetitemNavigation, Navigation, stepthrough,
    redirection, LaunchpadView)
from canonical.launchpad.interfaces import (
    BugDistroReleaseTargetDetails, BugTaskSearchParams, IBugAttachmentSet,
    IBugExternalRefSet, IBugSet, IBugTask, IBugTaskSet, IBugTaskSearch,
    IBugWatchSet, IDistribution, IDistributionSourcePackage, IBug,
    IDistroBugTask, IDistroRelease, IDistroReleaseBugTask,
    IDistroReleaseSet, ILaunchBag, INullBugTask, IPerson,
    IPersonBugTaskSearch, IProduct, IProject, ISourcePackage,
    ISourcePackageNameSet, IUpstreamBugTask, NotFoundError,
    RESOLVED_BUGTASK_STATUSES, UnexpectedFormData, IProductSeriesSet,
    UNRESOLVED_BUGTASK_STATUSES, valid_distrotask, valid_upstreamtask)
from canonical.launchpad.searchbuilder import any, NULL
from canonical.launchpad import helpers
from canonical.launchpad.event.sqlobjectevent import SQLObjectModifiedEvent
from canonical.launchpad.browser.bug import BugContextMenu
from canonical.launchpad.browser.bugcomment import build_comments_from_chunks
from canonical.launchpad.components.bugtask import NullBugTask

from canonical.launchpad.webapp.generalform import GeneralFormView
from canonical.launchpad.webapp.batching import TableBatchNavigator
from canonical.launchpad.webapp.snapshot import Snapshot

from canonical.lp.dbschema import BugTaskImportance, BugTaskStatus

from canonical.widgets.bug import BugTagsWidget
from canonical.widgets.bugtask import (
    AssigneeDisplayWidget, BugTaskBugWatchWidget, DBItemDisplayWidget,
    NewLineToSpacesWidget)


def get_comments_for_bugtask(bugtask, truncate=False):
    """Return BugComments related to a bugtask.

    This code builds a sorted list of BugComments in one shot,
    requiring only two database queries.
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
        IDistroRelease, ISourcePackage or IDistributionSourcePackage
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
            null_bugtask = NullBugTask(bug=bug, product=context)
        elif IDistribution.providedBy(context):
            null_bugtask = NullBugTask(bug=bug, distribution=context)
        elif IDistributionSourcePackage.providedBy(context):
            null_bugtask = NullBugTask(
                bug=bug, distribution=context.distribution,
                sourcepackagename=context.sourcepackagename)
        elif IDistroRelease.providedBy(context):
            null_bugtask = NullBugTask(bug=bug, distrorelease=context)
        elif ISourcePackage.providedBy(context):
            null_bugtask = NullBugTask(
                bug=bug, distrorelease=context.distrorelease,
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
        if name in ("+viewstatus", "+editstatus"):
            if INullBugTask.providedBy(self.context):
                # The bug has not been reported in this context.
                return None
            else:
                # The bug has been reported in this context.
                return getView(self.context, name + "-page", self.request)

    @stepthrough('attachments')
    def traverse_attachments(self, name):
        if name.isdigit():
            return getUtility(IBugAttachmentSet)[name]

    @stepthrough('references')
    def traverse_references(self, name):
        if name.isdigit():
            return getUtility(IBugExternalRefSet)[name]

    @stepthrough('watches')
    def traverse_watches(self, name):
        if name.isdigit():
            return getUtility(IBugWatchSet)[name]

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

    redirection('references', '..')


class BugTaskSetNavigation(GetitemNavigation):

    usedfor = IBugTaskSet


class BugTaskContextMenu(BugContextMenu):
    usedfor = IBugTask


class BugTaskView(LaunchpadView):
    """View class for presenting information about an IBugTask."""

    def __init__(self, context, request):
        LaunchpadView.__init__(self, context, request)

        # Make sure we always have the current bugtask.
        if not IBugTask.providedBy(context):
            self.context = getUtility(ILaunchBag).bugtask
        else:
            self.context = context

        self.notices = []

    def initialize(self):
        """Set up the needed widgets."""
        # See render() for how this flag is used.
        self._redirecting_to_bug_list = False

        if self.user is None:
            return

        # Set up widgets in order to handle subscription requests.
        if self.context.bug.isSubscribed(self.user):
            subscription_terms = [
                SimpleTerm(
                    self.user, self.user.name, 'Unsubscribe me from this bug')]
        else:
            subscription_terms = [
                SimpleTerm(
                    self.user, self.user.name, 'Subscribe me to this bug')]
        for team in self.user.teams_participated_in:
            if self.context.bug.isSubscribed(team):
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
        """Return whether the user is subscribed to the bug or not."""
        return self.context.bug.isSubscribed(self.user)

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
        # Handle unsubscribing the current user, which requires
        # special-casing when the bug is private.
        self.context.bug.unsubscribe(self.user)

        if helpers.check_permission("launchpad.View", self.context.bug):
            # The user still has permission to see this bug, so no
            # special-casing needed.
            self.notices.append("You have been unsubscribed from this bug.")
        else:
            # Add a notification message rather than appending to
            # .notices, because this message has to cross a redirect.
            self.request.response.addNotification((
                "You have been unsubscribed from bug %d. You no "
                "longer have access to this private bug.") %
                self.context.bug.id)

            # Redirect the user to the bug listing, because they can no
            # longer see a private bug from which they've unsubscribed.
            self.request.response.redirect(
                canonical_url(self.context.target) + "/+bugs")
            self._redirecting_to_bug_list = True

    def _handleUnsubscribeOtherUser(self, user):
        # Handle unsubscribing someone other than the current user.
        assert user != self.user, (
            "Expected a user other than the currently logged-in user.")

        self.context.bug.unsubscribe(user)
        self.notices.append(
            "%s has been unsubscribed from this bug." %
            cgi.escape(user.displayname))

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
            elif IDistroReleaseBugTask.providedBy(fake_task):
                # Create a real distro release bug task in this context.
                real_task = getUtility(IBugTaskSet).createTask(
                    bug=fake_task.bug, owner=getUtility(ILaunchBag).user,
                    distrorelease=fake_task.distrorelease,
                    sourcepackagename=fake_task.sourcepackagename)
            else:
                raise TypeError(
                    "Unknown bug task type: %s" % repr(fake_task))

            self.context = real_task

            # Add an appropriate feedback message
            self.notices.append("Thank you for your bug report.")

    def isReportedInContext(self):
        """Is the bug reported in this context? Returns True or False.

        This is particularly useful for views that may render a
        NullBugTask.
        """
        params = BugTaskSearchParams(user=self.user, bug=self.context.bug)
        matching_bugtasks = self.context.target.searchTasks(params)

        return matching_bugtasks.count() > 0

    def isReleaseTargetableContext(self):
        """Is the context something that supports release targeting?

        Returns True or False.
        """
        return (
            IDistroBugTask.providedBy(self.context) or
            IDistroReleaseBugTask.providedBy(self.context))

    def getBugComments(self):
        """Return all the bug comments together with their index."""
        comments = get_comments_for_bugtask(self.context, truncate=True)
        assert len(comments) > 0, "A bug should have at least one comment."
        # The first comment doesn't add any value if it's the same as the
        # description.
        initial_comment = comments[0]
        if initial_comment.text_contents == self.context.bug.description:
            return comments[1:]
        else:
            return comments


class BugTaskPortletView:
    def alsoReportedIn(self):
        """Return a list of IUpstreamBugTasks in which this bug is reported.

        If self.context is an IUpstreamBugTasks, it will be excluded
        from this list.
        """
        return [
            task for task in self.context.bug.bugtasks
            if task.id is not self.context.id]


class BugTaskBackportView:
    """View class for targeting bugs to IDistroReleases."""

    @property
    def release_target_details(self):
        """Return a list of BugDistroReleaseTargetDetails objects.

        Releases are filtered to only include distributions relevant
        to the context.distribution or .distrorelease (whichever is
        not None.)

        If the context does not provide IDistroBugTask or
        IDistroReleaseBugTask, a TypeError is raised.
        """
        # Ensure we have what we need.
        distribution = None
        context = self.context
        if IDistroBugTask.providedBy(context):
            distribution = context.distribution
        elif IDistroReleaseBugTask.providedBy(context):
            distribution = context.distrorelease.distribution
        else:
            raise TypeError(
                "retrieving related releases: need IDistroBugTask or "
                "IDistribution, found %s" % type(context))

        # First, let's gather the already-targeted
        # IDistroReleaseBugTasks relevant to this context.
        distro_release_tasks = {}
        for bugtask in context.bug.bugtasks:
            if not IDistroReleaseBugTask.providedBy(bugtask):
                continue

            release_targeted = bugtask.distrorelease
            if release_targeted.distribution == distribution:
                distro_release_tasks[release_targeted] = bugtask

        release_target_details = []
        sourcepackagename = bugtask.sourcepackagename
        for possible_target in distribution.releases:
            # Exclude the current release from this list, because it doesn't
            # make sense to "backport a fix" to the current release.
            if possible_target == distribution.currentrelease:
                continue

            if sourcepackagename is not None:
                sourcepackage = possible_target.getSourcePackage(
                    sourcepackagename)
            else:
                sourcepackage = None
            bug_distrorelease_target_details = BugDistroReleaseTargetDetails(
                release=possible_target, sourcepackage=sourcepackage)

            if possible_target in distro_release_tasks:
                # This release is already a target for this bugfix, so
                # let's grab some more data about this task.
                task = distro_release_tasks[possible_target]

                bug_distrorelease_target_details.istargeted = True
                bug_distrorelease_target_details.assignee = task.assignee
                bug_distrorelease_target_details.status = task.status

            release_target_details.append(bug_distrorelease_target_details)

        return release_target_details

    def createBackportTasks(self):
        """Create distrorelease-targeted tasks for this bug."""
        form = self.request.form

        if not form.get("savetargets"):
            # The form doesn't look like it was submitted; nothing to
            # do here.
            return

        targets = form.get("target")
        if not isinstance(targets, (list, tuple)):
            targets = [targets]

        bugtask = self.context
        bug = bugtask.bug

        # Grab the distribution, for use in looking up distro releases
        # by name later on.
        if IDistroBugTask.providedBy(bugtask):
            distribution = bugtask.distribution
        else:
            distribution = bugtask.distrorelease.distribution

        for target in targets:
            if target is None:
                # If the user didn't change anything a single target
                # with the value of None is submitted, so just skip.
                continue
            # A target value looks like 'warty.mozilla-firefox'. If
            # there was no specific sourcepackage targeted, it would
            # look like 'warty.'.
            if "." in target:
                # We need to ensure we split into two parts, because
                # some packages names contains dots.
                releasename, spname = target.split(".", 1)
                spname = getUtility(ISourcePackageNameSet).queryByName(spname)
            else:
                releasename = target
                spname = None
            release = getUtility(IDistroReleaseSet).queryByName(
                distribution, releasename)

            if not release:
                raise ValueError(
                    "Failed to locate matching IDistroRelease: %s" %
                    releasename)

            user = getUtility(ILaunchBag).user
            assert user is not None, 'Not logged in'
            getUtility(IBugTaskSet).createTask(
                    bug=bug, owner=user, distrorelease=release,
                    sourcepackagename=spname)

        # Redirect the user back to the task form.
        self.request.response.redirect(canonical_url(bugtask))


class BugTaskEditView(GeneralFormView):
    """The view class used for the task +editstatus page."""

    _missing_value = object()

    def __init__(self, context, request):
        GeneralFormView.__init__(self, context, request)

    def _setUpWidgets(self):
        """Set up a combination of display and edit widgets.

        Set up the widgets depending on if it's a remote bug task, where
        only the bug watch should be editable, or if it's a normal
        bug task, where everything should be editable except for the bug
        watch.
        """
        editable_field_names = self._getEditableFieldNames()
        read_only_field_names = self._getReadOnlyFieldNames()

        if self.context.target_uses_malone:
            self.bugwatch_widget = None
        else:
            self.bugwatch_widget = CustomWidgetFactory(BugTaskBugWatchWidget)
            if self.context.bugwatch is not None:
                self.assignee_widget = CustomWidgetFactory(
                    AssigneeDisplayWidget)
                self.status_widget = CustomWidgetFactory(DBItemDisplayWidget)
                self.importance_widget = CustomWidgetFactory(
                    DBItemDisplayWidget)

        setUpWidgets(
            self, self.schema, IInputWidget, names=editable_field_names,
            initial=self.initial_values)
        setUpDisplayWidgets(
            self, self.schema, names=read_only_field_names)

        self.fieldNames = editable_field_names

    def _getEditableFieldNames(self):
        """Return the names of fields the user has perms to edit."""
        if self.context.target_uses_malone:
            # Don't edit self.fieldNames directly, because it's shared by all
            # BugTaskEditView instances.
            editable_field_names = list(self.fieldNames)
            editable_field_names.remove('bugwatch')

            if not self._userCanEditMilestone():
                editable_field_names.remove("milestone")

            if not self._userCanEditImportance():
                editable_field_names.remove("importance")
        else:
            editable_field_names = ['bugwatch']
            if not IUpstreamBugTask.providedBy(self.context):
                #XXX: Should be possible to edit the product as well,
                #     but that's harder due to complications with bug
                #     watches. The new product might use Malone
                #     officially, thus we need to handle that case.
                #     Let's deal with that later.
                #     -- Bjorn Tillenius, 2006-03-01
                editable_field_names += ['sourcepackagename']
            if self.context.bugwatch is None:
                editable_field_names += ['status', 'assignee']
                if self._userCanEditImportance():
                    editable_field_names += ["importance"]

        return editable_field_names

    def _getReadOnlyFieldNames(self):
        """Return the names of fields that will be rendered read only."""
        if self.context.target_uses_malone:
            read_only_field_names = []

            if not self._userCanEditMilestone():
                read_only_field_names.append("milestone")

            if not self._userCanEditImportance():
                read_only_field_names.append("importance")
        else:
            editable_field_names = self._getEditableFieldNames()
            read_only_field_names = [
                field_name for field_name in self.fieldNames
                if field_name not in editable_field_names]

        return read_only_field_names

    def _userCanEditMilestone(self):
        """Can the user edit the Milestone field?

        If yes, return True, otherwise return False.
        """
        product_or_distro = self._getProductOrDistro()

        return (
            "milestone" in self.fieldNames and
            helpers.check_permission("launchpad.Edit", product_or_distro))

    def _userCanEditImportance(self):
        """Can the user edit the Importance field?

        If yes, return True, otherwise return False.
        """
        product_or_distro = self._getProductOrDistro()

        return (
            ("importance" in self.fieldNames) and (
                (product_or_distro.bugcontact and
                 self.user and
                 self.user.inTeam(product_or_distro.bugcontact)) or
                helpers.check_permission("launchpad.Edit", product_or_distro)))

    def _getProductOrDistro(self):
        """Return the product or distribution relevant to the context."""
        return (
            self.context.product or
            self.context.distribution or
            self.context.distrorelease.distribution)

    @property
    def initial_values(self):
        """See canonical.launchpad.webapp.generalform.GeneralFormView."""
        field_values = {}
        for name in self.fieldNames:
            field_values[name] = getattr(self.context, name)

        return field_values

    def validate(self, data):
        """See canonical.launchpad.webapp.generalform.GeneralFormView."""
        bugtask = self.context
        comment_on_change = self.request.form.get("comment_on_change")
        if comment_on_change:
            # There was a comment on this change, so make sure that a
            # change was actually made.
            changed = False
            for field_name in data:
                current_value = getattr(bugtask, field_name)
                if current_value != data[field_name]:
                    changed = True
                    break

            if not changed:
                # Pass the change comment error message as a list because
                # WidgetsError expects a list.
                raise WidgetsError([
                    "You provided a change comment without changing anything."])
        distro = bugtask.distribution
        sourcename = bugtask.sourcepackagename
        product = bugtask.product
        if distro is not None and sourcename != data['sourcepackagename']:
            valid_distrotask(bugtask.bug, distro, data['sourcepackagename'])
        if (product is not None and
            'product' in data and product != data['product']):
            valid_upstreamtask(bugtask.bug, data['product'])

        return data

    def process(self):
        """See canonical.launchpad.webapp.generalform.GeneralFormView."""
        bugtask = self.context

        if self.request.form.get('subscribe', False):
            bugtask.bug.subscribe(self.user)
            self.request.response.addNotification(
                "You have been subscribed to this bug.")

        # Save the field names we extract from the form in a separate
        # list, because we modify this list of names later if the
        # bugtask is reassigned to a different product.
        field_names = list(self.fieldNames)
        new_values = getWidgetsData(self, self.schema, field_names)

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
            # We *clear* the milestone value if one was already set. We *ignore*
            # the milestone value if it was currently None, and the user tried
            # to set a milestone value while also changing the product. This
            # allows us to provide slightly clearer feedback messages.
            if bugtask.milestone:
                milestone_cleared = bugtask.milestone
            else:
                if self.milestone_widget.getInputValue() is not None:
                    milestone_ignored = True

            bugtask.milestone = None
            # Remove the "milestone" field from the list of fields
            # whose changes we want to apply, because we don't want
            # the form machinery to try and set this value back to
            # what it was!
            field_names.remove("milestone")

        # We special case setting assignee and status, because there's
        # a workflow associated with changes to these fields.
        field_names_to_apply = list(field_names)
        if "assignee" in field_names_to_apply:
            field_names_to_apply.remove("assignee")
        if "status" in field_names_to_apply:
            field_names_to_apply.remove("status")

        changed = applyWidgetsChanges(
            self, self.schema, target=bugtask,
            names=field_names_to_apply)

        new_status = new_values.pop("status", self._missing_value)
        new_assignee = new_values.pop("assignee", self._missing_value)
        # Set the "changed" flag properly, just in case status and/or assignee
        # happen to be the only values that changed. We explicitly verify that
        # we got a new status and/or assignee, because our test suite doesn't
        # always pass all form values.
        if ((new_status is not self._missing_value) and
            (bugtask.status != new_status)):
            changed = True
            bugtask.transitionToStatus(new_status)

        if ((new_assignee is not self._missing_value) and
            (bugtask.assignee != new_assignee)):
            changed = True
            bugtask.transitionToAssignee(new_assignee)

        if bugtask_before_modification.bugwatch != bugtask.bugwatch:
            if bugtask.bugwatch is None:
                # Reset the status and importance to the default values,
                # since Unknown isn't selectable in the UI.
                bugtask.transitionToStatus(IBugTask['status'].default)
                bugtask.importance = IBugTask['importance'].default
            else:
                #XXX: Reset the bug task's status information. The right
                #     thing would be to convert the bug watch's status to a
                #     Malone status, but it's not trivial to do at the
                #     moment. I will fix this later.
                #     -- Bjorn Tillenius, 2006-03-01
                bugtask.transitionToStatus(BugTaskStatus.UNKNOWN)
                bugtask.importance = BugTaskImportance.UNKNOWN
                bugtask.transitionToAssignee(None)

        if milestone_cleared:
            self.request.response.addWarningNotification(
                "The bug report for %s was removed from the %s milestone "
                "because it was reassigned to a new product" % (
                    bugtask.targetname, milestone_cleared.displayname))
        elif milestone_ignored:
            self.request.response.addWarningNotification(
                "The milestone setting was ignored because you reassigned the "
                "bug to a new product")

        comment_on_change = self.request.form.get("comment_on_change")

        # The statusexplanation field is being display as a "Comment on most
        # recent change" field now, so set it to the current change comment if
        # there is one, otherwise clear it out.
        if comment_on_change:
            # Add the change comment as a comment on the bug.
            bugtask.bug.newMessage(
                owner=getUtility(ILaunchBag).user,
                subject=bugtask.bug.followup_subject(),
                content=comment_on_change)

            bugtask.statusexplanation = comment_on_change
        else:
            bugtask.statusexplanation = ""

        if changed:
            notify(
                SQLObjectModifiedEvent(
                    object=bugtask,
                    object_before_modification=bugtask_before_modification,
                    edited_fields=field_names))

        if (bugtask_before_modification.sourcepackagename !=
            bugtask.sourcepackagename):
            # The source package was changed, so tell the user that we've
            # subscribed the new bug contacts.
            self.request.response.addNotification(
                "The bug contacts for %s have been subscribed to this bug." % (
                    bugtask.targetname))

    def nextURL(self):
        """See canonical.launchpad.webapp.generalform.GeneralFormView."""
        return canonical_url(self.context)


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

        if IUpstreamBugTask.providedBy(self.context):
            self.label = 'Product fix request'
        else:
            field_names += ['sourcepackagename']
            self.label = 'Source package fix request'

        self.assignee_widget = CustomWidgetFactory(AssigneeDisplayWidget)
        self.status_widget = CustomWidgetFactory(DBItemDisplayWidget)
        self.importance_widget = CustomWidgetFactory(DBItemDisplayWidget)

        setUpWidgets(self, IBugTask, IDisplayWidget, names=field_names)


class BugListingPortletView(LaunchpadView):
    """Portlet containing all available bug listings."""
    def getOpenBugsURL(self):
        """Return the URL for open bugs on this bug target."""
        return self.getSearchFilterURL(
            status=[status.title for status in UNRESOLVED_BUGTASK_STATUSES])

    def getBugsAssignedToMeURL(self):
        """Return the URL for bugs assigned to the current user on target."""
        if self.user:
            return self.getSearchFilterURL(assignee=self.user.name)
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
        return self.getSearchFilterURL(
            status=[status.title for status in UNRESOLVED_BUGTASK_STATUSES],
            importance=dbschema.BugTaskImportance.CRITICAL.title)

    def getUnassignedBugsURL(self):
        """Return the URL for critical bugs on this bug target."""
        unresolved_tasks_query_string = self.getSearchFilterURL(
            status=[status.title for status in UNRESOLVED_BUGTASK_STATUSES])

        return unresolved_tasks_query_string + "&assignee_option=none"

    def getUnconfirmedBugsURL(self):
        """Return the URL for unconfirmed bugs on this bug target."""
        return self.getSearchFilterURL(
            status=dbschema.BugTaskStatus.UNCONFIRMED.title)

    def getAllBugsEverReportedURL(self):
        all_statuses = UNRESOLVED_BUGTASK_STATUSES + RESOLVED_BUGTASK_STATUSES
        all_status_query_string = self.getSearchFilterURL(
            status=[status.title for status in all_statuses])

        # Add the bit that simulates the "omit dupes" checkbox being unchecked.
        return all_status_query_string + "&field.omit_dupes.used="

    def getSearchFilterURL(self, assignee=None, importance=None, status=None):
        """Return a URL with search parameters."""
        search_params = []

        if assignee:
            search_params.append(('field.assignee', assignee))
        if importance:
            search_params.append(('field.importance', importance))
        if status:
            search_params.append(('field.status', status))

        query_string = urllib.urlencode(search_params, doseq=True)

        search_filter_url = str(self.request.URL) + "?search=Search"
        if query_string:
            search_filter_url += "&" + query_string

        return search_filter_url


def getInitialValuesFromSearchParams(search_params, form_schema):
    """Build a dictionary that can be given as initial values to
    setUpWidgets, based on the given search params.

    >>> initial = getInitialValuesFromSearchParams(
    ...     {'status': any(*UNRESOLVED_BUGTASK_STATUSES)}, IBugTaskSearch)
    >>> [status.name for status in initial['status']]
    ['UNCONFIRMED', 'CONFIRMED', 'INPROGRESS', 'NEEDSINFO', 'FIXCOMMITTED']

    >>> initial = getInitialValuesFromSearchParams(
    ...     {'status': dbschema.BugTaskStatus.REJECTED}, IBugTaskSearch)
    >>> [status.name for status in initial['status']]
    ['REJECTED']

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


def upstream_status_vocabulary_factory(context):
    """Create a vocabulary for filtering on upstream status.

    This is used to show a radio widget on the advanced search form.
    """
    terms = [
        SimpleTerm(
            'pending_bugwatch',
            title='Show only bugs that need to be linked to an upstream'
                  ' bug report'),
        SimpleTerm(
            'hide_open', title='Hide bugs that are open upstream'),
        SimpleTerm(
            'only_closed', title='Show only bugs that are closed upstream'),
            ]
    return SimpleVocabulary(terms)


class BugTaskSearchListingView(LaunchpadView):
    """Base class for bug listings.

    Subclasses should define getExtraSearchParams() to filter the
    search.
    """

    form_has_errors = False
    owner_error = ""
    assignee_error = ""

    def __init__(self, context, request):
        LaunchpadView.__init__(self, context, request)

        if self._personContext():
            self.schema = IPersonBugTaskSearch
        else:
            self.schema = IBugTaskSearch

        if self.shouldShowComponentWidget():
            # CustomWidgetFactory doesn't work with
            # MultiCheckBoxWidget, so we work around this by manually
            # instantiating the widget.
            #
            # XXX, Brad Bollenbach, 2006-03-22: Integrate BjornT's
            # MultiCheckBoxWidget workaround once that lands, which
            # will also fix the widget to use <label>'s.
            self.component_widget = MultiCheckBoxWidget(
                self.schema['component'].bind(self.context),
                getVocabularyRegistry().get(None, "Component"),
                self.request)

        self.searchtext_widget = CustomWidgetFactory(NewLineToSpacesWidget)
        self.status_upstream_widget = CustomWidgetFactory(
            RadioWidget, _messageNoValue="Doesn't matter")
        self.tag_widget = CustomWidgetFactory(BugTagsWidget)
        setUpWidgets(self, self.schema, IInputWidget)
        self.validateVocabulariesAdvancedForm()

    @property
    def columns_to_show(self):
        """Returns a sequence of column names to be shown in the listing."""
        upstream_context = self._upstreamContext()
        project_context = self._projectContext()
        distribution_context = self._distributionContext()
        distrorelease_context = self._distroReleaseContext()
        distrosourcepackage_context = self._distroSourcePackageContext()
        sourcepackage_context = self._sourcePackageContext()

        assert (
            upstream_context or project_context or distribution_context or
            distrorelease_context or distrosourcepackage_context or
            sourcepackage_context), (
            "Unrecognized context; don't know which report "
            "columns to show.")

        if (upstream_context or distrosourcepackage_context or
            sourcepackage_context):
            return ["id", "summary", "importance", "status"]
        elif distribution_context or distrorelease_context:
            return ["id", "summary", "packagename", "importance", "status"]
        elif project_context:
            return ["id", "summary", "productname", "importance", "status"]

    def validate_search_params(self):
        """Validate the params passed for the search.

        An UnexpectedFormData exception is raised if the user submitted a URL
        that could not have been created from the UI itself.
        """
        # The only way the user should get these field values incorrect is
        # through a stale bookmark or a hand-hacked URL.
        for field_name in ("status", "importance", "milestone", "component"):
            try:
                getWidgetsData(self, schema=self.schema, names=[field_name])
            except WidgetsError:
                raise UnexpectedFormData(
                    "Unexpected value for field '%s'. Perhaps your bookmarks "
                    "are out of date or you changed the URL by hand?" % field_name)

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

    def search(self, searchtext=None, context=None, extra_params=None):
        """Return an ITableBatchNavigator for the GET search criteria.

        If :searchtext: is None, the searchtext will be gotten from the
        request.

        :extra_params: is a dict that provides search params added to the
        search criteria taken from the request. Params in :extra_params: take
        precedence over request params.
        """
        self.validate_search_params()

        widget_names = [
                "searchtext", "status", "assignee", "importance",
                "owner", "omit_dupes", "has_patch",
                "milestone", "component", "has_no_package",
                "status_upstream", "tag",
                ]
        # widget_names are the possible widget names, only include the
        # ones that are actually in the schema.
        widget_names = [name for name in widget_names if name in self.schema]
        data = getWidgetsData(self, self.schema, names=widget_names)

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

        if data.get("omit_dupes") is None:
            # The "omit dupes" parameter wasn't provided, so default to omitting
            # dupes from reports, of course.
            data["omit_dupes"] = True

        if data.get("status") is None:
            # Show only open bugtasks as default
            data['status'] = UNRESOLVED_BUGTASK_STATUSES

        if 'status_upstream' in data:
            # Convert the status_upstream value to parameters we can
            # send to BugTaskSet.search().
            status_upstream = data['status_upstream']
            if status_upstream == 'pending_bugwatch':
                data['pending_bugwatch_elsewhere'] = True
            elif status_upstream == 'only_closed':
                data['status_elsewhere'] = RESOLVED_BUGTASK_STATUSES
            elif status_upstream == 'hide_open':
                data['omit_status_elsewhere'] = UNRESOLVED_BUGTASK_STATUSES
            del data['status_upstream']

        # "Normalize" the form data into search arguments.
        form_values = {}
        for key, value in data.items():
            if value:
                if zope_isinstance(value, (list, tuple)):
                    form_values[key] = any(*value)
                else:
                    form_values[key] = value

        # Base classes can provide an explicit search context.
        if not context:
            context = self.context

        search_params = BugTaskSearchParams(user=self.user, **form_values)
        search_params.orderby = get_sortorder_from_request(self.request)
        tasks = context.searchTasks(search_params)

        return TableBatchNavigator(
            tasks, self.request, columns_to_show=self.columns_to_show,
            size=config.malone.buglist_batch_size)

    def getWidgetValues(self, vocabulary_name, default_values=()):
        """Return data used to render a field's widget."""
        widget_values = []

        vocabulary_registry = getVocabularyRegistry()
        for term in vocabulary_registry.get(None, vocabulary_name):
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

    def shouldShowComponentWidget(self):
        """Should the component widget be shown on the advanced search page?"""
        context = self.context
        return (
            (IDistribution.providedBy(context) and
             context.currentrelease is not None) or
            IDistroRelease.providedBy(context) or
            ISourcePackage.providedBy(context))

    def shouldShowNoPackageWidget(self):
        """Should the widget to filter on bugs with no package be shown?

        The widget will be shown only on a distribution or
        distrorelease's advanced search page.
        """
        return (IDistribution.providedBy(self.context) or
                IDistroRelease.providedBy(self.context))

    def shouldShowReporterWidget(self):
        """Should the reporter widget be shown on the advanced search page?"""
        return True

    def shouldShowBugsElsewhereBox(self):
        """Should the "Bugs elsewhere" widgets be shown?"""
        return 'status_upstream' in self.schema

    def getSortLink(self, colname):
        """Return a link that can be used to sort results by colname."""
        form = self.request.form
        sortlink = ""
        if form.get("search") is None:
            # There is no search criteria to preserve.
            sortlink = "%s?search=Search&orderby=%s" % (
                str(self.request.URL), colname)
            return sortlink

        # XXX: is it not possible to get the exact request supplied and
        # just sneak a "-" in front of the orderby argument, if it
        # exists? If so, the code below could be a lot simpler.
        #       -- kiko, 2005-08-23

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

    def validateVocabulariesAdvancedForm(self):
        """Validate person vocabularies in advanced form.

        If a vocabulary lookup fail set a custom error message and set
        self.form_has_errors to True.
        """
        error_message = _(
            "There's no person with the name or email address '%s'")
        try:
            getWidgetsData(self, self.schema, names=["assignee"])
        except WidgetsError:
            self.assignee_error = error_message % (
                cgi.escape(self.request.get('field.assignee')))
        try:
            getWidgetsData(self, self.schema, names=["owner"])
        except WidgetsError:
            self.owner_error = error_message % (
                cgi.escape(self.request.get('field.owner')))

        if self.assignee_error or self.owner_error:
            self.form_has_errors = True

    def _upstreamContext(self):
        """Is this page being viewed in an upstream context?

        Return the IProduct if yes, otherwise return None.
        """
        return IProduct(self.context, None)

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

    def _distroReleaseContext(self):
        """Is this page being viewed in a distrorelease context?

        Return the IDistroRelease if yes, otherwise return None.
        """
        return IDistroRelease(self.context, None)

    def _sourcePackageContext(self):
        """Is this page being viewed in a [distrorelease] sourcepackage context?

        Return the ISourcePackage if yes, otherwise return None.
        """
        return ISourcePackage(self.context, None)

    def _distroSourcePackageContext(self):
        """Is this page being viewed in a distribution sourcepackage context?

        Return the IDistributionSourcePackage if yes, otherwise return None.
        """
        return IDistributionSourcePackage(self.context, None)


class BugTargetView:
    """Used to grab bugs for a bug target; used by the latest bugs portlet"""
    def latestBugTasks(self, quantity=5):
        """Return <quantity> latest bugs reported against this target."""
        params = BugTaskSearchParams(orderby="-datecreated",
                                     omit_dupes=True,
                                     user=getUtility(ILaunchBag).user)

        tasklist = self.context.searchTasks(params)
        return tasklist[:quantity]


class BugTargetTextView(LaunchpadView):
    """View for simple text page showing bugs filed against a bug target."""

    def render(self):
        self.request.response.setHeader('Content-type', 'text/plain')
        tasks = self.context.searchTasks(BugTaskSearchParams(self.user))

        # We use task.bugID rather than task.bug.id here as the latter
        # would require an extra query per task.
        return u''.join('%d\n' % task.bugID for task in tasks)


class BugNominationView(LaunchpadView):
    def __init__(self, context, request):
        # Adapt the context to an IBug, because we don't need anything
        # task-specific on the nomination page.
        LaunchpadView.__init__(self, IBug(context), request)

    def processNominations(self):
        form = self.request.form

        if form.get("cancel"):
            self._returnToBugPage()

        bug = self.context
        distro_release_set = getUtility(IDistroReleaseSet)
        product_series_set = getUtility(IProductSeriesSet)
        owner = self.user
        if form.get("nominate"):
            for distro_release_id in form.get("distrorelease", []):
                distrorelease = distro_release_set.get(distro_release_id)
                bug.addNomination(
                    distrorelease=distrorelease, owner=owner)
            for product_series_id in form.get("productseries", []):
                productseries = product_series_set.get(product_series_id)
                bug.addNomination(
                    productseries=productseries, owner=owner)

            self._returnToBugPage()

    def getUpcomingReleases(self):
        """Return a list of upcoming releases for nomination.

        For example, if the bug had a task open on a Debian package and
        an Ubuntu package, a list containing two elements would be
        returned: Debian's current development release and Ubuntu's
        current development release, assuming each distribution has a
        current development release.

        This method does not currently consider products, since products
        have no notion of "current series".
        """
        distribution_targets = set()
        for bugtask in self.context.bugtasks:
            if bugtask.distribution:
                distribution_targets.add(bugtask.distribution)

        return [distribution.currentrelease
                for distribution in distribution_targets
                if distribution.currentrelease]

    def getCurrentNominations(self):
        """Return the currently nominated IDistroReleases and IProductSeries.

        Returns a list of dicts.
        """
        

    def getUpstreamSeriesList(self):
        """Return a list of IProductSeries associated with this bug."""
        series_list = []
        for bugtask in self.context.bugtasks:
            if bugtask.product:
                for series in bugtask.product.serieslist:
                    series_list.append(series)

        return series_list


    def getOtherDistroReleases(self):
        """Return a list of other IDistroReleases associated with this bug.

        This list excludes current development releases.
        """
        distroreleases = []
        for bugtask in self.context.bugtasks:
            if bugtask.distribution:
                for distrorelease in bugtask.distribution.releases:
                    if distrorelease.releasestatus not in (
                        dbschema.DistributionReleaseStatus.DEVELOPMENT,
                        dbschema.DistributionReleaseStatus.OBSOLETE):
                        distroreleases.append(distrorelease)

        return distroreleases

    def _returnToBugPage(self):
        self.request.response.redirect(canonical_url(self.context))
