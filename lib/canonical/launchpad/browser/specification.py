# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Specification views."""

__metaclass__ = type

__all__ = [
    'SpecificationContextMenu',
    'SpecificationNavigation',
    'SpecificationView',
    'SpecificationAddView',
    'SpecificationEditView',
    'SpecificationSupersedingView',
    'SpecificationRetargetingView',
    ]

from zope.component import getUtility

from canonical.launchpad.interfaces import (
    IProduct, IDistribution, ILaunchBag, ISpecification, ISpecificationSet,
    NameNotAvailable)

from canonical.launchpad.browser.editview import SQLObjectEditView
from canonical.launchpad.browser.addview import SQLObjectAddView

from canonical.launchpad.webapp import (
    canonical_url, ContextMenu, Link, enabled_with_permission,
    LaunchpadView, Navigation, GeneralFormView)

from canonical.lp.dbschema import (
    SpecificationStatus, SpecificationGoalStatus)


class SpecificationNavigation(Navigation):

    usedfor = ISpecification

    def traverse(self, sprintname):
        return self.context.getSprintSpecification(sprintname)


class SpecificationContextMenu(ContextMenu):

    usedfor = ISpecification
    links = ['edit', 'people', 'status', 'priority', 'setseries',
             'setrelease',
             'milestone', 'requestfeedback', 'givefeedback', 'subscription',
             'subscribeanother',
             'linkbug', 'unlinkbug', 'adddependency', 'removedependency',
             'dependencytree', 'linksprint', 'supersede',
             'retarget', 'administer']

    def edit(self):
        text = 'Edit Details'
        return Link('+edit', text, icon='edit')

    def people(self):
        text = 'Change People'
        return Link('+people', text, icon='edit')

    def status(self):
        text = 'Change Status'
        return Link('+status', text, icon='edit')

    def priority(self):
        text = 'Change Priority'
        return Link('+priority', text, icon='edit')

    def supersede(self):
        text = 'Mark Superseded'
        return Link('+supersede', text, icon='edit')

    def setseries(self):
        text = 'Set Series Goal'
        enabled = self.context.product is not None
        return Link('+setseries', text, icon='edit', enabled=enabled)

    def setrelease(self):
        text = 'Set Release Goal'
        enabled = self.context.distribution is not None
        return Link('+setrelease', text, icon='edit', enabled=enabled)

    def milestone(self):
        text = 'Set Milestone'
        return Link('+milestone', text, icon='edit')

    def requestfeedback(self):
        text = 'Request Feedback'
        return Link('+requestfeedback', text, icon='edit')

    def givefeedback(self):
        text = 'Give Feedback'
        enabled = (self.user is not None and
                   self.context.getFeedbackRequests(self.user))
        return Link('+givefeedback', text, icon='edit', enabled=enabled)

    def subscription(self):
        user = self.user
        if user is not None and has_spec_subscription(user, self.context):
            text = 'Unsubscribe Yourself'
        else:
            text = 'Subscribe Yourself'
        return Link('+subscribe', text, icon='edit')

    def subscribeanother(self):
        text = 'Subscribe Someone'
        return Link('+addsubscriber', text, icon='add')

    def linkbug(self):
        text = 'Link to Bug'
        return Link('+linkbug', text, icon='add')

    def unlinkbug(self):
        text = 'Remove Bug Link'
        enabled = bool(self.context.bugs)
        return Link('+unlinkbug', text, icon='add', enabled=enabled)

    def adddependency(self):
        text = 'Add Dependency'
        return Link('+linkdependency', text, icon='add')

    def removedependency(self):
        text = 'Remove Dependency'
        enabled = bool(self.context.dependencies)
        return Link('+removedependency', text, icon='add', enabled=enabled)

    def dependencytree(self):
        text = 'Show Dependencies'
        enabled = (
            bool(self.context.dependencies) or bool(self.context.blocked_specs)
            )
        return Link('+deptree', text, icon='info', enabled=enabled)

    def linksprint(self):
        text = 'Add to Meeting'
        return Link('+linksprint', text, icon='add')

    @enabled_with_permission('launchpad.Edit')
    def retarget(self):
        text = 'Retarget'
        return Link('+retarget', text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def administer(self):
        text = 'Administer'
        return Link('+admin', text, icon='edit')


def has_spec_subscription(person, spec):
    """Return whether the person has a subscription to the spec.

    XXX: Refactor this to a method on ISpecification.
         SteveAlexander, 2005-09-26
    """
    assert person is not None
    for subscription in spec.subscriptions:
        if subscription.person.id == person.id:
            return True
    return False


class SpecificationView(LaunchpadView):

    __used_for__ = ISpecification

    def initialize(self):
        # The review that the user requested on this spec, if any.
        self.feedbackrequests = []
        self.notices = []
        request = self.request

        # establish if a subscription form was posted
        newsub = request.form.get('subscribe', None)
        if newsub is not None and self.user and request.method == 'POST':
            if newsub == 'Subscribe':
                self.context.subscribe(self.user)
                self.notices.append("You have subscribed to this spec.")
            elif newsub == 'Unsubscribe':
                self.context.unsubscribe(self.user)
                self.notices.append("You have unsubscribed from this spec.")

        if self.user is not None:
            # establish if this user has a review queued on this spec
            self.feedbackrequests = self.context.getFeedbackRequests(self.user)
            if self.feedbackrequests:
                msg = "You have %d feedback request(s) on this specification."
                msg %= len(self.feedbackrequests)
                self.notices.append(msg)

    @property
    def subscription(self):
        """whether the current user has a subscription to the spec."""
        if self.user is None:
            return False
        return has_spec_subscription(self.user, self.context)


class SpecificationAddView(SQLObjectAddView):

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self._nextURL = '.'
        SQLObjectAddView.__init__(self, context, request)

    def create(self, name, title, specurl, summary, status,
        owner, assignee=None, drafter=None, approver=None):
        """Create a new Specification."""
        #Inject the relevant product or distribution into the kw args.
        product = None
        distribution = None
        if IProduct.providedBy(self.context):
            product = self.context.id
        elif IDistribution.providedBy(self.context):
            distribution = self.context.id
        # clean up name
        name = name.strip().lower()
        spec = getUtility(ISpecificationSet).new(name, title, specurl,
            summary, status, owner, product=product,
            distribution=distribution, assignee=assignee, drafter=drafter,
            approver=approver)
        self._nextURL = canonical_url(spec)
        # give karma where it is due
        owner.assignKarma('addspec')
        return spec

    def add(self, content):
        """Skipping 'adding' this content to a container, because
        this is a placeless system."""
        return content

    def nextURL(self):
        return self._nextURL


class SpecificationEditView(SQLObjectEditView):

    def changed(self):
        self.request.response.redirect(canonical_url(self.context))


class SpecificationRetargetingView(GeneralFormView):

    def process(self, product=None, distribution=None):
        if product and distribution:
            return 'Please choose a product OR a distribution, not both.'
        if not (product or distribution):
            return 'Please choose a product or distribution for this spec.'
        # we need to ensure that there is not already a spec with this name
        # for this new target
        if product:
            if product.getSpecification(self.context.name) is not None:
                return '%s already has a spec called %s' % (
                    product.name, self.context.name)
        elif distribution:
            if distribution.getSpecification(self.context.name) is not None:
                return '%s already has a spec called %s' % (
                    distribution.name, self.context.name)
        self.context.retarget(product=product, distribution=distribution)
        self._nextURL = canonical_url(self.context)
        return 'Done.'


class SpecificationSupersedingView(GeneralFormView):

    def process(self, superseded_by=None):
        self.context.superseded_by = superseded_by
        if superseded_by is not None:
            # set the state to superseded
            self.context.status = SpecificationStatus.SUPERSEDED
        else:
            # if the current state is SUPERSEDED and we are now removing the
            # superseded-by then we should move this spec back into the
            # drafting pipeline by resetting its status to BRAINDUMP
            if self.context.status == SpecificationStatus.SUPERSEDED:
                self.context.status = SpecificationStatus.BRAINDUMP
        self.request.response.redirect(canonical_url(self.context))
        return 'Done.'

