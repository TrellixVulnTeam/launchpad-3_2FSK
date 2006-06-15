# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Ticket views."""

__metaclass__ = type

__all__ = [
    'TicketSetNavigation',
    'TicketView',
    'TicketAddView',
    'TicketContextMenu',
    'TicketEditView',
    'TicketMakeBugView',
    'TicketSetContextMenu'
    ]

from zope.component import getUtility
from zope.event import notify

from canonical.launchpad.interfaces import ILaunchBag, ITicket, ITicketSet
from canonical.launchpad.browser.editview import SQLObjectEditView
from canonical.launchpad.browser.addview import SQLObjectAddView
from canonical.launchpad.webapp import (
    ContextMenu, Link, canonical_url, enabled_with_permission, Navigation,
    LaunchpadView)
from canonical.launchpad.event import SQLObjectModifiedEvent
from canonical.launchpad.webapp.snapshot import Snapshot


class TicketSetNavigation(Navigation):

    usedfor = ITicketSet


class TicketView(LaunchpadView):

    __used_for__ = ITicket

    def initialize(self):
        self.notices = []
        self.is_owner = self.user == self.context.owner

        if not self.user or self.request.method != "POST":
            # No post, nothing to do
            return

        # XXX: all this crap should be moved to a method; having it here
        # means that any template using TicketView (including
        # -listing-detailed, which many other pages do) have to go
        # through millions of queries.
        #   -- kiko, 2006-03-17

        ticket_unmodified = Snapshot(self.context, providing=ITicket)
        modified_fields = set()

        form = self.request.form
        # establish if a subscription form was posted
        newsub = form.get('subscribe', None)
        if newsub is not None:
            if newsub == 'Subscribe':
                self.context.subscribe(self.user)
                self.notices.append("You have subscribed to this request.")
                modified_fields.add('subscribers')
            elif newsub == 'Unsubscribe':
                self.context.unsubscribe(self.user)
                self.notices.append("You have unsubscribed from this request.")
                modified_fields.add('subscribers')

        # establish if the user is trying to reject the ticket
        reject = form.get('reject', None)
        if reject is not None:
            if self.context.reject(self.user):
                self.notices.append("You have rejected this request.")
                modified_fields.add('status')

        # establish if the user is trying to reopen the ticket
        reopen = form.get('reopen', None)
        if reopen is not None:
            if self.context.reopen(self.user):
                self.notices.append("You have reopened this request.")
                modified_fields.add('status')

        if len(modified_fields) > 0:
            notify(SQLObjectModifiedEvent(
                self.context, ticket_unmodified, list(modified_fields)))

    @property
    def subscription(self):
        """establish if this user has a subscription"""
        if self.user is None:
            return False
        return self.context.isSubscribed(self.user)


class TicketAddView(SQLObjectAddView):

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self._nextURL = '.'
        SQLObjectAddView.__init__(self, context, request)

    def create(self, title=None, description=None, owner=None):
        """Create a new Ticket."""
        ticket = self.context.newTicket(owner, title, description)
        self._nextURL = canonical_url(ticket)
        return ticket

    def nextURL(self):
        return self._nextURL


class TicketEditView(SQLObjectEditView):

    def changed(self):
        self.request.response.redirect(canonical_url(self.context))


class TicketMakeBugView(LaunchpadView):
    """Browser class for adding a bug from a ticket."""

    def process(self):
        form = self.request.form
        ticket = ITicket(self.context)

        if not self.request.method == 'POST':
            return

        if form.get('create'):
            if ticket.bugs:
                # we can't make a bug when we have linked bugs
                self.request.response.addNotification(
                    'You cannot create a bug report from a support request that '
                    'already has bugs linked to it.')
            else:
                unmodifed_ticket = Snapshot(ticket, providing=ITicket)
                bug = ticket.target.createBug(
                    self.user, ticket.title, ticket.description)
                ticket.linkBug(bug)
                bug.subscribe(ticket.owner)
                bug_added_event = SQLObjectModifiedEvent(
                    ticket, unmodifed_ticket, ['bugs'])
                notify(bug_added_event)
                self.request.response.addNotification(
                    'Thank you! Bug #%d created.' % bug.id)

        self.request.response.redirect(canonical_url(ticket))


class TicketContextMenu(ContextMenu):

    usedfor = ITicket
    links = [
        'edit',
        'editsourcepackage',
        'reject',
        'reopen',
        'history',
        'subscription',
        'linkbug',
        'unlinkbug',
        'makebug',
        'administer',
        ]

    def initialize(self):
        self.is_not_resolved = not self.context.is_resolved
        self.has_bugs = bool(self.context.bugs)

    def edit(self):
        text = 'Edit Request'
        return Link('+edit', text, icon='edit', enabled=self.is_not_resolved)

    def editsourcepackage(self):
        enabled = (
            self.is_not_resolved and self.context.distribution is not None)
        text = 'Change Source Package'
        return Link('+sourcepackage', text, icon='edit', enabled=enabled)

    def reject(self):
        text = 'Reject Request'
        return Link('+reject', text, icon='edit',
                    enabled=self.context.can_be_rejected)

    def reopen(self):
        text = 'Reopen Request'
        enabled = (
            self.context.can_be_reopened and self.user == self.context.owner)
        return Link('+reopen', text, icon='edit', enabled=enabled)

    def history(self):
        text = 'History'
        return Link('+history', text, icon='list',
                    enabled=bool(self.context.reopenings))

    def subscription(self):
        if self.user is not None and self.context.isSubscribed(self.user):
            text = 'Unsubscribe'
            enabled = True
            icon = 'edit'
        else:
            text = 'Subscribe'
            enabled = self.is_not_resolved
            icon = 'mail'
        return Link('+subscribe', text, icon=icon, enabled=enabled)

    def linkbug(self):
        text = 'Link Existing Bug'
        return Link('+linkbug', text, icon='add', enabled=self.is_not_resolved)

    def unlinkbug(self):
        enabled = self.is_not_resolved and self.has_bugs
        text = 'Remove Bug Link'
        return Link('+unlinkbug', text, icon='edit', enabled=enabled)

    def makebug(self):
        enabled = self.is_not_resolved and not self.has_bugs
        text = 'Create Bug Report'
        summary = 'Create a bug report from this support request.'
        return Link('+makebug', text, summary, icon='add', enabled=enabled)

    @enabled_with_permission('launchpad.Admin')
    def administer(self):
        text = 'Administer'
        return Link('+admin', text, icon='edit')


class TicketSetContextMenu(ContextMenu):

    usedfor = ITicketSet
    links = ['findproduct', 'finddistro']

    def findproduct(self):
        text = 'Find Upstream Product'
        return Link('/products', text, icon='search')

    def finddistro(self):
        text = 'Find Distribution'
        return Link('/distros', text, icon='search')

