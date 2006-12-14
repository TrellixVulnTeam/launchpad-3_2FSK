# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""IBugTarget-related browser views."""

__metaclass__ = type

__all__ = [
    "BugTargetBugListingView",
    "BugTargetBugTagsView",
    "FileBugViewBase",
    "FileBugAdvancedView",
    "FileBugGuidedView",
    "FileBugInPackageView"
    ]

import urllib

from zope.app.form.browser import TextWidget
from zope.app.form.interfaces import IInputWidget, WidgetsError, InputErrors
from zope.app.form.utility import setUpWidgets
from zope.app.pagetemplate import ViewPageTemplateFile
from zope.component import getUtility
from zope.event import notify

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.event.sqlobjectevent import SQLObjectCreatedEvent
from canonical.launchpad.interfaces import (
    IBugTaskSet, ILaunchBag, IDistribution, IDistroRelease, IDistroReleaseSet,
    IProduct, IDistributionSourcePackage, NotFoundError, CreateBugParams,
    IBugAddForm, BugTaskSearchParams, ILaunchpadCelebrities)
from canonical.launchpad.webapp import (
    canonical_url, LaunchpadView, LaunchpadFormView, action, custom_widget)
from canonical.launchpad.webapp.batching import TableBatchNavigator
from canonical.launchpad.webapp.generalform import GeneralFormView


class FileBugViewBase(LaunchpadFormView):
    """Base class for views related to filing a bug."""

    @property
    def initial_values(self):
        """Give packagename a default value, if applicable."""
        if not IDistributionSourcePackage.providedBy(self.context):
            return {}

        return {'packagename': self.context.name}

    def getProductOrDistroFromContext(self):
        """Return the IProduct or IDistribution for this context."""
        context = self.context

        if IDistribution.providedBy(context) or IProduct.providedBy(context):
            return context
        else:
            assert IDistributionSourcePackage.providedBy(context), (
                "Expected a bug filing context that provides one of "
                "IDistribution, IProduct, or IDistributionSourcePackage. "
                "Got: %r" % context)

            return context.distribution

    def getPackageNameFieldCSSClass(self):
        """Return the CSS class for the packagename field."""
        if self.widget_errors.get("packagename"):
            return 'error'
        else:
            return ''

    def validate(self, data):
        """Make sure the package name, if provided, exists in the distro."""
        # We have to poke at the packagename value directly in the
        # request, because if validation failed while getting the
        # widget's data, it won't appear in the data dict.
        form = self.request.form
        if form.get("packagename_option") == "choose":
            packagename = form.get("field.packagename")
            if packagename:
                if IDistribution.providedBy(self.context):
                    distribution = self.context
                elif 'distribution' in data:
                    distribution = data['distribution']
                else:
                    assert IDistributionSourcePackage.providedBy(self.context)
                    distribution = self.context.distribution

                try:
                    distribution.guessPackageNames(packagename)
                except NotFoundError:
                    if distribution.releases:
                        # If a distribution doesn't have any releases,
                        # it won't have any source packages published at
                        # all, so we set the error only if there are
                        # releases.
                        packagename_error = (
                            '"%s" does not exist in %s. Please choose a '
                            "different package. If you're unsure, please "
                            'select "I don\'t know"' % (
                                packagename, distribution.displayname))
                        self.setFieldError("packagename", packagename_error)
            else:
                self.setFieldError("packagename", "Please enter a package name")

    def setUpWidgets(self):
        """Customize the onKeyPress event of the package name chooser."""
        LaunchpadFormView.setUpWidgets(self)

        if "packagename" in self.field_names:
            self.widgets["packagename"].onKeyPress = (
                "selectWidget('choose', event)")

    def contextUsesMalone(self):
        """Does the context use Malone as its official bugtracker?"""
        return self.getProductOrDistroFromContext().official_malone

    def shouldSelectPackageName(self):
        """Should the radio button to select a package be selected?"""
        return (
            self.request.form.get("field.packagename") or
            self.initial_values.get("packagename"))

    def handleSubmitBugFailure(self, action, data, errors):
        return self.showFileBugForm()

    @action("Submit Bug Report", name="submit_bug",
            failure=handleSubmitBugFailure)
    def submit_bug_action(self, action, data):
        """Add a bug to this IBugTarget."""
        title = data.get("title")
        comment = data.get("comment")
        packagename = data.get("packagename")
        security_related = data.get("security_related", False)
        distribution = data.get(
            "distribution", getUtility(ILaunchBag).distribution)
        product = getUtility(ILaunchBag).product

        context = self.context
        if distribution is not None:
            # We're being called from the generic bug filing form, so
            # manually set the chosen distribution as the context.
            context = distribution

        # Ensure that no package information is used, if the user
        # enters a package name but then selects "I don't know".
        if self.request.form.get("packagename_option") == "none":
            packagename = None

        # Security bugs are always private when filed, but can be disclosed
        # after they've been reported.
        if security_related:
            private = True
        else:
            private = False

        notification = "Thank you for your bug report."
        if IDistribution.providedBy(context) and packagename:
            # We don't know if the package name we got was a source or binary
            # package name, so let the Soyuz API figure it out for us.
            packagename = str(packagename)
            try:
                sourcepackagename, binarypackagename = (
                    context.guessPackageNames(packagename))
            except NotFoundError:
                # guessPackageNames may raise NotFoundError. It would be
                # nicer to allow people to indicate a package even if
                # never published, but the quick fix for now is to note
                # the issue and move on.
                notification += (
                    "<br /><br />The package %s is not published in %s; the "
                    "bug was targeted only to the distribution."
                    % (packagename, context.displayname))
                comment += ("\r\n\r\nNote: the original reporter indicated "
                            "the bug was in package %r; however, that package "
                            "was not published in %s."
                            % (packagename, context.displayname))
                params = CreateBugParams(
                    title=title, comment=comment, owner=self.user,
                    security_related=security_related, private=private)
            else:
                context = context.getSourcePackage(sourcepackagename.name)
                params = CreateBugParams(
                    title=title, comment=comment, owner=self.user,
                    security_related=security_related, private=private,
                    binarypackagename=binarypackagename)
        else:
            params = CreateBugParams(
                title=title, comment=comment, owner=self.user,
                security_related=security_related, private=private)

        bug = context.createBug(params)
        notify(SQLObjectCreatedEvent(bug))

        # Give the user some feedback on the bug just opened.
        self.request.response.addNotification(notification)
        if bug.private:
            self.request.response.addNotification(
                'Security-related bugs are by default <span title="Private '
                'bugs are visible only to their direct subscribers.">private'
                '</span>. You may choose to <a href="+secrecy">publically '
                'disclose</a> this bug.')

        self.request.response.redirect(canonical_url(bug.bugtasks[0]))

    def showFileBugForm(self):
        """Override this method in base classes to show the filebug form."""
        raise NotImplementedError


class FileBugAdvancedView(FileBugViewBase):
    """Browser view for filing a bug.

    This view skips searching for duplicates.
    """
    schema = IBugAddForm
    # XXX, Brad Bollenbach, 2006-10-04: This assignment to actions is a
    # hack to make the action decorator Just Work across
    # inheritance. Technically, this isn't needed for this class,
    # because it defines no further actions, but I've added it just to
    # preclude mysterious bugs if/when another action is defined in this
    # class!
    actions = FileBugViewBase.actions
    custom_widget('title', TextWidget, displayWidth=40)
    template = ViewPageTemplateFile(
        "../templates/bugtarget-filebug-advanced.pt")

    @property
    def field_names(self):
        """Return the list of field names to display."""
        context = self.context
        if IProduct.providedBy(context):
            return ['title', 'comment', 'security_related']
        else:
            assert (
                IDistribution.providedBy(context) or
                IDistributionSourcePackage.providedBy(context))

            return ['title', 'comment', 'security_related', 'packagename']

    def showFileBugForm(self):
        return self.template()


class FileBugGuidedView(FileBugViewBase):
    schema = IBugAddForm
    # XXX, Brad Bollenbach, 2006-10-04: This assignment to actions is a
    # hack to make the action decorator Just Work across inheritance.
    actions = FileBugViewBase.actions
    custom_widget('title', TextWidget, displayWidth=40)

    _MATCHING_BUGS_LIMIT = 10
    _SEARCH_FOR_DUPES = ViewPageTemplateFile(
        "../templates/bugtarget-filebug-search.pt")
    _FILEBUG_FORM = ViewPageTemplateFile(
        "../templates/bugtarget-filebug-submit-bug.pt")

    template = _SEARCH_FOR_DUPES

    focused_element_id = 'field.title'

    @property
    def field_names(self):
        """Return the list of field names to display."""
        context = self.context
        if IProduct.providedBy(context):
            return ['title', 'comment']
        else:
            assert (
                IDistribution.providedBy(context) or
                IDistributionSourcePackage.providedBy(context))

            return ['title', 'comment', 'packagename']

    @action("Continue", name="search", validator="validate_search")
    def search_action(self, action, data):
        """Search for similar bug reports."""
        return self.showFileBugForm()

    @cachedproperty
    def similar_bugs(self):
        """Return the similar bugs based on the user search."""
        matching_bugs = []
        title = self.getSearchText()
        if not title:
            return []
        search_context = self.getProductOrDistroFromContext()
        if IProduct.providedBy(search_context):
            context_params = {'product': search_context}
        else:
            assert IDistribution.providedBy(search_context), (
                'Unknown search context: %r' % search_context)
            context_params = {'distribution': search_context}
            if IDistributionSourcePackage.providedBy(self.context):
                context_params['sourcepackagename'] = (
                    self.context.sourcepackagename)
        matching_bugtasks = getUtility(IBugTaskSet).findSimilar(
            self.user, title, **context_params)
        # Remove all the prejoins, since we won't use them and they slow
        # down the query significantly.
        matching_bugtasks = matching_bugtasks.prejoin(None)

        # XXX: We might end up returning less than :limit: bugs, but in
        #      most cases we won't, and '4*limit' is here to prevent
        #      this page from timing out in production. Later I'll fix
        #      this properly by selecting distinct Bugs directly
        #      If matching_bugtasks isn't sliced, it will take a long time
        #      to iterate over it, even over only 10, because
        #      Transaction.iterSelect() listifies the result. Bug 75764.
        #      -- Bjorn Tillenius, 2006-12-13
        # We select more than :self._MATCHING_BUGS_LIMIT: since if a bug
        # affects more than one source package, it will be returned more
        # than one time. 4 is an arbitrary number that should be large
        # enough.
        for bugtask in matching_bugtasks[:4*self._MATCHING_BUGS_LIMIT]:
            if not bugtask.bug in matching_bugs:
                matching_bugs.append(bugtask.bug)
                if len(matching_bugs) >= self._MATCHING_BUGS_LIMIT:
                    break

        return matching_bugs

    @cachedproperty
    def most_common_bugs(self):
        """Return a list of the most duplicated bugs."""
        return self.context.getMostCommonBugs(
            self.user, limit=self._MATCHING_BUGS_LIMIT)

    @property
    def found_possible_duplicates(self):
        return self.similar_bugs or self.most_common_bugs


    def getSearchText(self):
        """Return the search string entered by the user."""
        try:
            return self.widgets['title'].getInputValue()
        except InputErrors:
            return None

    def validate_search(self, action, data):
        """Make sure some keywords are provided."""
        try:
            data['title'] = self.widgets['title'].getInputValue()
        except InputErrors, error:
            self.setFieldError("title", "A summary is required.")
            return [error]

        # Return an empty list of errors to satisfy the validation API,
        # and say "we've handled the validation and found no errors."
        return ()

    def validate_no_dupe_found(self, action, data):
        return ()

    @action("Continue", name="continue",
            validator="validate_no_dupe_found")
    def continue_action(self, action, data):
        """The same action as no-dupe-found, with a different label."""
        return self.showFileBugForm()

    def showFileBugForm(self):
        return self._FILEBUG_FORM()


class FileBugInPackageView(FileBugViewBase):
    """Browser view class for the top-level filebug-in-package page."""
    schema = IBugAddForm
    # XXX, Brad Bollenbach, 2006-10-04: This assignment to actions is a
    # hack to make the action decorator Just Work across
    # inheritance. Technically, this isn't needed for this class,
    # because it defines no further actions, but I've added it just to
    # preclude mysterious bugs if/when another action is defined in this
    # class!
    actions = FileBugViewBase.actions
    template = ViewPageTemplateFile(
        "../templates/bugtarget-filebug-simple.pt")
    custom_widget('title', TextWidget, displayWidth=40)

    @property
    def initial_values(self):
        return {"distribution": getUtility(ILaunchpadCelebrities).ubuntu}

    @property
    def field_names(self):
        return ['title', 'comment', 'distribution', 'packagename']

    def showFileBugForm(self):
        return self.template()

    def shouldShowSteps(self):
        return False

    def contextUsesMalone(self):
        """Say context uses Malone so that the filebug form is shown!"""
        return True


class BugTargetBugListingView:
    """Helper methods for rendering bug listings."""

    @property
    def release_buglistings(self):
        """Return a buglisting for each release.

        The list is sorted newest release to oldest.

        The count only considers bugs that the user would actually be
        able to see in a listing.
        """
        distribution_context = IDistribution(self.context, None)
        distrorelease_context = IDistroRelease(self.context, None)

        if distrorelease_context:
            distribution = distrorelease_context.distribution
        elif distribution_context:
            distribution = distribution_context
        else:
            raise AssertionError, ("release_bug_counts called with "
                                   "illegal context")

        releases = getUtility(IDistroReleaseSet).search(
            distribution=distribution, orderBy="-datereleased")

        release_buglistings = []
        for release in releases:
            release_buglistings.append(
                dict(
                    title=release.displayname,
                    url=canonical_url(release) + "/+bugs",
                    count=release.open_bugtasks.count()))

        return release_buglistings


class BugTargetBugTagsView(LaunchpadView):
    """Helper methods for rendering the bug tags portlet."""

    def _getSearchURL(self, tag):
        """Return the search URL for the tag."""
        return "%s?field.tag=%s" % (
            self.request.getURL(), urllib.quote(tag))

    def getUsedBugTagsWithURLs(self):
        """Return the bug tags and their search URLs."""
        bug_tag_counts = self.context.getUsedBugTagsWithOpenCounts(self.user)
        return [
            {'tag': tag, 'count': count, 'url': self._getSearchURL(tag)}
            for tag, count in bug_tag_counts]
