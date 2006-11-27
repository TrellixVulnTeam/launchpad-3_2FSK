# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Ticket views."""

__metaclass__ = type

__all__ = [
    'TicketAddView',
    'TicketChangeStatusView',
    'TicketConfirmAnswerView',
    'TicketContextMenu',
    'TicketEditView',
    'TicketMakeBugView',
    'TicketMessageDisplayView',
    'TicketSetContextMenu',
    'TicketSetNavigation',
    'TicketRejectView',
    'TicketSubscriptionView',
    'TicketWorkflowView',
    ]

from zope.app.form.browser import TextAreaWidget, TextWidget
from zope.app.pagetemplate import ViewPageTemplateFile
from zope.component import getUtility
from zope.event import notify
from zope.formlib import form
from zope.interface import alsoProvides, implements, providedBy
from zope.schema import Choice
from zope.schema.interfaces import IContextSourceBinder
from zope.schema.vocabulary import SimpleVocabulary, SimpleTerm
import zope.security

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.helpers import request_languages
from canonical.launchpad import _
from canonical.launchpad.event import (
    SQLObjectCreatedEvent, SQLObjectModifiedEvent)
from canonical.launchpad.interfaces import (
    CreateBugParams, ILanguageSet, ITicket, ITicketAddMessageForm,
    ITicketChangeStatusForm, ITicketSet, ITicketTarget, UnexpectedFormData)
from canonical.launchpad.webapp import (
    ContextMenu, Link, canonical_url, enabled_with_permission, Navigation,
    GeneralFormView, LaunchpadView, action, LaunchpadFormView,
    LaunchpadEditFormView, custom_widget)
from canonical.launchpad.webapp.interfaces import IAlwaysSubmittedWidget
from canonical.launchpad.webapp.snapshot import Snapshot
from canonical.lp.dbschema import TicketAction, TicketStatus

class TicketSetNavigation(Navigation):

    usedfor = ITicketSet


class TicketSubscriptionView(LaunchpadView):
    """View for subscribing and unsubscribing from a ticket."""

    def initialize(self):
        if not self.user or self.request.method != "POST":
            # No post, nothing to do
            return

        ticket_unmodified = Snapshot(
            self.context, providing=providedBy(self.context))
        modified_fields = set()

        form = self.request.form
        response = self.request.response
        # establish if a subscription form was posted
        newsub = form.get('subscribe', None)
        if newsub is not None:
            if newsub == 'Subscribe':
                self.context.subscribe(self.user)
                response.addNotification(
                    _("You have subscribed to this request."))
                modified_fields.add('subscribers')
            elif newsub == 'Unsubscribe':
                self.context.unsubscribe(self.user)
                response.addNotification(
                    _("You have unsubscribed from this request."))
                modified_fields.add('subscribers')
            response.redirect(canonical_url(self.context))
        notify(SQLObjectModifiedEvent(
            self.context, ticket_unmodified, list(modified_fields)))

    @property
    def subscription(self):
        """establish if this user has a subscription"""
        if self.user is None:
            return False
        return self.context.isSubscribed(self.user)


class TicketLanguageVocabularyFactory:
    """Factory for a vocabulary containing a subset of the possible languages.

    The vocabulary will contain only the languages "interesting" for the user.
    That's English plus the users preferred languages. These will be guessed
    from the request when the preferred languages weren't configured.

    It also always include the ticket's current language and excludes all
    English variants.
    """

    implements(IContextSourceBinder)

    def __init__(self, request):
        """Create a TicketLanguageVocabularyFactory.

        :param request: The request in which the vocabulary will be used. This
        will be used to determine the user languages.
        """
        self.request = request

    def __call__(self, context):
        languages = set()
        for lang in request_languages(self.request):
            # Ignore English and all its variants.
            if not lang.code.startswith('en'):
                languages.add(lang)
        if (context is not None and ITicket.providedBy(context) and
            context.language.code != 'en'):
            languages.add(context.language)
        languages = list(languages)

        # Insert English as the first element, to make it the default one.
        languages.insert(0, getUtility(ILanguageSet)['en'])

        terms = [SimpleTerm(lang, lang.code, lang.displayname)
                 for lang in languages]
        return SimpleVocabulary(terms)


class TicketSupportLanguageMixin:
    """Helper mixin for views manipulating the ticket language.

    It provides a method to check if the selected language is supported
    and another to create the form field to select the ticket language.

    This mixin adapts its context to ITicketTarget, so it will work if
    the context either provides ITicketTarget directly or if an adapter
    exists.
    """

    supported_languages_macros = ViewPageTemplateFile(
        '../templates/ticket-supported-languages-macros.pt')

    @property
    def chosen_language(self):
        """Return the language chosen by the user."""
        if self.widgets['language'].hasInput():
            return self.widgets['language'].getInputValue()
        else:
            return self.context.language

    @property
    def unsupported_languages_warning(self):
        """Macro displaying a warning in case of unsupported languages."""
        macros = self.supported_languages_macros.macros
        return macros['unsupported_languages_warning']

    @property
    def ticket_target(self):
        """Return the ITicketTarget related to the context."""
        return ITicketTarget(self.context)

    def createLanguageField(self):
        """Create a field to edit a ticket language using a special vocabulary.

        :param the_form: The form that will use this field.
        :return: A form.Fields instance containing the language field.
        """
        return form.Fields(
                Choice(
                    __name__='language',
                    source=TicketLanguageVocabularyFactory(self.request),
                    title=_('Language'),
                    description=_(
                        'The language in which this request is written.')),
                render_context=self.render_context)

    def shouldWarnAboutUnsupportedLanguage(self):
        """Test if the warning about unsupported language should be displayed.

        A warning will be displayed if the request's language is not listed
        as a spoken language for any of the support contacts. The warning
        will only be displayed one time, except if the user changes the
        request language to another unsupported value.
        """
        if self.chosen_language in self.ticket_target.getSupportedLanguages():
            return False

        old_chosen_language = self.request.form.get('chosen_language')
        return self.chosen_language.code != old_chosen_language


class TicketAddView(TicketSupportLanguageMixin, LaunchpadFormView):
    """Multi-page add view.

    The user enters first his ticket summary and then he is shown a list
    of similar results before adding the ticket.
    """
    label = _('Make a support request')

    schema = ITicket

    field_names = ['title', 'description']

    custom_widget('title', TextWidget, displayWidth=40)

    search_template = ViewPageTemplateFile('../templates/ticket-add-search.pt')

    add_template = ViewPageTemplateFile('../templates/ticket-add.pt')

    template = search_template

    _MAX_SIMILAR_TICKETS = 10

    # Do not autofocus the title widget
    initial_focus_widget = None

    def setUpFields(self):
        # Add our language field with a vocabulary specialized for
        # display purpose.
        LaunchpadFormView.setUpFields(self)
        self.form_fields = self.createLanguageField() + self.form_fields

    def setUpWidgets(self):
        # Only setup the widgets that needs validation
        if not self.add_action.submitted():
            fields = self.form_fields.select('language', 'title')
        else:
            fields = self.form_fields
        self.widgets = form.setUpWidgets(
            fields, self.prefix, self.context, self.request,
            data=self.initial_values, ignore_request=False)

    def validate(self, data):
        """Validate hook.

        This validation method sets the chosen_language attribute.
        """
        if 'title' not in data:
            self.setFieldError(
                'title',_('You must enter a summary of your problem.'))
        if self.widgets.get('description'):
            if 'description' not in data:
                self.setFieldError(
                    'description',
                    _('You must provide details about your problem.'))

    @action(_('Continue'))
    def continue_action(self, action, data):
        """Search for tickets similar to the entered summary."""
        # If the description widget wasn't setup, add it here
        if self.widgets.get('description') is None:
            self.widgets += form.setUpWidgets(
                self.form_fields.select('description'), self.prefix,
                 self.context, self.request, data=self.initial_values,
                 ignore_request=False)

        tickets = self.context.findSimilarTickets(data['title'])
        self.searchResults = tickets[:self._MAX_SIMILAR_TICKETS]

        return self.add_template()

    def handleAddError(self, action, data, errors):
        """Handle errors on new ticket creation submission. Either redirect
        to the search template when the summary is missing or delegate to
        the continue action handler to do the search.
        """
        if 'title' not in data:
            # Remove the description widget
            widgets = [(True, self.widgets[name])
                       for name in ('language', 'title')]
            self.widgets = form.Widgets(widgets, len(self.prefix)+1)
            return self.search_template()
        return self.continue_action.success(data)

    # XXX flacoste 2006/07/26 We use the method here instead of
    # using the method name 'handleAddError' because of Zope issue 573
    # which is fixed in 3.3.0b1 and 3.2.1
    @action(_('Add'), failure=handleAddError)
    def add_action(self, action, data):
        if self.shouldWarnAboutUnsupportedLanguage():
            # Warn the user that the language is not supported.
            self.searchResults = []
            return self.add_template()

        ticket = self.context.newTicket(
            self.user, data['title'], data['description'], data['language'])

        # XXX flacoste 2006/07/25 This should be moved to newTicket().
        notify(SQLObjectCreatedEvent(ticket))

        self.request.response.redirect(canonical_url(ticket))
        return ''


class TicketChangeStatusView(LaunchpadFormView):
    """View for changing a ticket status."""
    schema = ITicketChangeStatusForm

    def validate(self, data):
        if data.get('status') == self.context.status:
            self.setFieldError(
                'status', _("You didn't change the status."))
        if not data.get('message'):
            self.setFieldError(
                'message', _('You must provide an explanation message.'))

    @property
    def initial_values(self):
        return {'status': self.context.status}

    @action(_('Change Status'), name='change-status')
    def change_status_action(self, action, data):
        self.context.setStatus(self.user, data['status'], data['message'])
        self.request.response.addNotification(
            _('Request status updated.'))
        self.request.response.redirect(canonical_url(self.context))


class TicketEditView(TicketSupportLanguageMixin, LaunchpadEditFormView):

    schema = ITicket
    label = 'Edit request'
    field_names = ["title", "description", "sourcepackagename",
                   "priority", "assignee", "whiteboard"]

    custom_widget('title', TextWidget, displayWidth=40)
    custom_widget('whiteboard', TextAreaWidget, height=5)

    def setUpFields(self):
        """Select the subset of fields to display.

        - Exclude the sourcepackagename field when ticket doesn't have a
        distribution.
        - Exclude fields that the user doesn't have permission to modify.
        """
        LaunchpadEditFormView.setUpFields(self)

        if self.context.distribution is None:
            self.form_fields = self.form_fields.omit("sourcepackagename")

        # Add the language field with a vocabulary specialized for display
        # purpose.
        self.form_fields = self.createLanguageField() + self.form_fields

        editable_fields = []
        for field in self.form_fields:
            if zope.security.canWrite(self.context, field.__name__):
                editable_fields.append(field.__name__)
        self.form_fields = self.form_fields.select(*editable_fields)

    @action(u"Continue", name="change")
    def change_action(self, action, data):
        if self.shouldWarnAboutUnsupportedLanguage():
            return self.template()
        self.updateContextFromData(data)
        self.request.response.redirect(canonical_url(self.context))


class TicketMakeBugView(GeneralFormView):
    """Browser class for adding a bug from a ticket."""

    def initialize(self):
        ticket = self.context
        if ticket.bugs:
            # we can't make a bug when we have linked bugs
            self.request.response.addErrorNotification(
                _('You cannot create a bug report from a support request'
                  'that already has bugs linked to it.'))
            self.request.response.redirect(canonical_url(ticket))
            return

    @property
    def initial_values(self):
        ticket = self.context
        return {'title': '',
                'description': ticket.description}

    def process_form(self):
        # Override GeneralFormView.process_form because we don't
        # want form validation when the cancel button is clicked
        ticket = self.context
        if self.request.method == 'GET':
            self.process_status = ''
            return ''
        if 'cancel' in self.request.form:
            self.request.response.redirect(canonical_url(ticket))
            return ''
        return GeneralFormView.process_form(self)

    def process(self, title, description):
        ticket = self.context

        unmodifed_ticket = Snapshot(ticket, providing=providedBy(ticket))
        params = CreateBugParams(
            owner=self.user, title=title, comment=description)
        bug = ticket.target.createBug(params)
        ticket.linkBug(bug)
        bug.subscribe(ticket.owner)
        bug_added_event = SQLObjectModifiedEvent(
            ticket, unmodifed_ticket, ['bugs'])
        notify(bug_added_event)
        self.request.response.addNotification(
            _('Thank you! Bug #$bugid created.', mapping={'bugid': bug.id}))
        self._nextURL = canonical_url(bug)

    def submitted(self):
        return 'create' in self.request


class TicketRejectView(LaunchpadFormView):
    """View for rejecting a ticket."""
    schema = ITicketChangeStatusForm
    field_names = ['message']

    def validate(self, data):
        if 'message' not in data:
            self.setFieldError(
                'message', _('You must provide an explanation message.'))

    @action(_('Reject'))
    def reject_action(self, action, data):
        self.context.reject(self.user, data['message'])
        self.request.response.addNotification(
            _('You have rejected this request.'))
        self.request.response.redirect(canonical_url(self.context))
        return ''


class TicketWorkflowView(LaunchpadFormView):
    """View managing the ticket workflow action, i.e. action changing
    its status.
    """
    schema = ITicketAddMessageForm

    # Do not autofocus the message widget.
    initial_focus_widget = None

    def setUpWidgets(self):
        """See LaunchpadFormView."""
        LaunchpadFormView.setUpWidgets(self)
        alsoProvides(self.widgets['message'], IAlwaysSubmittedWidget)

    def validate(self, data):
        """Form validatation hook.

        When the action is confirm, find and validate the message
        that was selected. When another action is used, only make sure
        that a message was provided.
        """
        if self.confirm_action.submitted():
            self.validateConfirmAnswer(data)
        else:
            if not data.get('message'):
                self.setFieldError('message', _('Please enter a message.'))

    def hasActions(self):
        """Return True if some actions are possible for this user."""
        for action in self.actions:
            if action.available():
                return True
        return False

    def canAddComment(self, action):
        """Return whether the comment action should be displayed.

        Comments (message without a status change) can be added when the
        ticket is solved or invalid
        """
        return (self.user is not None and
                self.context.status in [
                    TicketStatus.SOLVED, TicketStatus.INVALID])

    @action(_('Add Comment'), name='comment', condition=canAddComment)
    def comment_action(self, action, data):
        """Add a comment to a resolved ticket."""
        self.context.addComment(self.user, data['message'])
        self.request.response.addNotification(_('Thanks for your comment.'))
        self.next_url = canonical_url(self.context)

    def canAddAnswer(self, action):
        """Return whether the answer action should be displayed."""
        return (self.user is not None and
                self.user != self.context.owner and
                self.context.can_give_answer)

    @action(_('Add Answer'), name='answer', condition=canAddAnswer)
    def answer_action(self, action, data):
        """Add an answer to the ticket."""
        self.context.giveAnswer(self.user, data['message'])
        self.request.response.addNotification(_('Thanks for your answer.'))
        self.next_url = canonical_url(self.context)

    def canSelfAnswer(self, action):
        """Return whether the selfanswer action should be displayed."""
        return (self.user == self.context.owner and
                self.context.can_give_answer)

    @action(_('I Solved my Problem'), name="selfanswer",
            condition=canSelfAnswer)
    def selfanswer_action(self, action, data):
        """Action called when the owner provides the solution to his problem."""
        self.context.giveAnswer(self.user, data['message'])
        self.request.response.addNotification(
            _('Thanks for sharing your solution.'))
        self.next_url = canonical_url(self.context)

    def canRequestInfo(self, action):
        """Return if the requestinfo action should be displayed."""
        return (self.user is not None and
                self.user != self.context.owner and
                self.context.can_request_info)

    @action(_('Add Information Request'), name='requestinfo',
            condition=canRequestInfo)
    def requestinfo_action(self, action, data):
        """Add a request for more information to the ticket."""
        self.context.requestInfo(self.user, data['message'])
        self.request.response.addNotification(
            _('Thanks for your information request.'))
        self.next_url = canonical_url(self.context)

    def canGiveInfo(self, action):
        """Return whether the giveinfo action should be displayed."""
        return (self.user == self.context.owner and
                self.context.can_give_info)

    @action(_("I'm Providing More Information"), name='giveinfo',
            condition=canGiveInfo)
    def giveinfo_action(self, action, data):
        """Give additional informatin on the request."""
        self.context.giveInfo(data['message'])
        self.request.response.addNotification(
            _('Thanks for adding more information to your request.'))
        self.next_url = canonical_url(self.context)

    def validateConfirmAnswer(self, data):
        """Make sure that a valid message id was provided as the confirmed
        answer."""
        # No widget is used for the answer, we are using hidden fields
        # in the template for that. So, if the answer is missing, it's
        # either a programming error or an invalid handcrafted URL
        msgid = self.request.form.get('answer_id')
        if msgid is None:
            raise UnexpectedFormData('missing answer_id')
        try:
            data['answer']= self.context.messages[int(msgid)]
        except ValueError:
            raise UnexpectedFormData('invalid answer_id: %s' % msgid)
        except IndexError:
            raise UnexpectedFormData("unknown answer: %s" % msgid)

    def canConfirm(self, action):
        """Return whether the confirm action should be displayed."""
        return (self.user == self.context.owner and
                self.context.can_confirm_answer)

    @action(_("This Solved my Problem"), name='confirm',
            condition=canConfirm)
    def confirm_action(self, action, data):
        """Confirm that an answer solved the request."""
        # The confirmation message is not given by the user when the
        # 'This Solved my Problem' button on the main ticket view.
        if not data['message']:
            data['message'] = 'User confirmed that the request is solved.'
        self.context.confirmAnswer(data['message'], answer=data['answer'])
        self.request.response.addNotification(_('Thanks for your feedback.'))
        self.next_url = canonical_url(self.context)

    def canReopen(self, action):
        """Return whether the reopen action should be displayed."""
        return (self.user == self.context.owner and
                self.context.can_reopen)

    @action(_("I'm Still Having This Problem"), name='reopen',
            condition=canReopen)
    def reopen_action(self, action, data):
        """State that the problem is still occuring and provide new
        information about it."""
        self.context.reopen(data['message'])
        self.request.response.addNotification(_('Your request was reopened.'))
        self.next_url = canonical_url(self.context)


class TicketConfirmAnswerView(TicketWorkflowView):
    """Specialized workflow view for the +confirm link sent in email
    notifications.
    """

    def initialize(self):
        # This page is only accessible when a confirmation is possible.
        if not self.context.can_confirm_answer:
            self.request.response.addErrorNotification(_(
                "The support request is not in a state where you can confirm "
                "an answer."))
            self.request.response.redirect(canonical_url(self.context))
            return

        TicketWorkflowView.initialize(self)

    def getAnswerMessage(self):
        """Return the message that should be confirmed."""
        data = {}
        self.validateConfirmAnswer(data)
        return data['answer']


class TicketMessageDisplayView(LaunchpadView):
    """View that renders a TicketMessage in the context of a Ticket."""

    def __init__(self, context, request):
        LaunchpadView.__init__(self, context, request)
        self.ticket = context.ticket

    display_confirm_button = True

    @cachedproperty
    def isBestAnswer(self):
        """Return True when this message is marked as solving the ticket."""
        return (self.context == self.ticket.answer and
                self.context.action in [
                    TicketAction.ANSWER, TicketAction.CONFIRM])

    def renderAnswerIdFormElement(self):
        """Return the hidden form element to refer to that message."""
        return '<input type="hidden" name="answer_id" value="%d" />' % list(
            self.context.ticket.messages).index(self.context)

    def getBodyCSSClass(self):
        """Return the CSS class to use for this message's body."""
        if self.isBestAnswer:
            return "boardCommentBody highlighted"
        else:
            return "boardCommentBody"

    def canConfirmAnswer(self):
        """Return True if the user can confirm this answer."""
        return (self.display_confirm_button and
                self.user == self.ticket.owner and
                self.ticket.can_confirm_answer and
                self.context.action == TicketAction.ANSWER)

    def renderWithoutConfirmButton(self):
        """Display the message without any confirm button."""
        self.display_confirm_button = False
        return self()


class TicketContextMenu(ContextMenu):

    usedfor = ITicket
    links = [
        'edit',
        'reject',
        'changestatus',
        'history',
        'subscription',
        'linkbug',
        'unlinkbug',
        'makebug',
        ]

    def initialize(self):
        self.has_bugs = bool(self.context.bugs)

    def edit(self):
        text = 'Edit Request'
        return Link('+edit', text, icon='edit')

    @enabled_with_permission('launchpad.Admin')
    def changestatus(self):
        return Link('+change-status', _('Change Status'), icon='edit')

    def reject(self):
        enabled = self.user is not None and self.context.canReject(self.user)
        text = 'Reject Request'
        return Link('+reject', text, icon='edit', enabled=enabled)

    def history(self):
        text = 'History'
        return Link('+history', text, icon='list',
                    enabled=bool(self.context.messages))

    def subscription(self):
        if self.user is not None and self.context.isSubscribed(self.user):
            text = 'Unsubscribe'
            icon = 'edit'
        else:
            text = 'Subscribe'
            icon = 'mail'
        return Link('+subscribe', text, icon=icon)

    def linkbug(self):
        text = 'Link Existing Bug'
        return Link('+linkbug', text, icon='add')

    def unlinkbug(self):
        text = 'Remove Bug Link'
        return Link('+unlinkbug', text, icon='edit', enabled=self.has_bugs)

    def makebug(self):
        text = 'Create Bug Report'
        summary = 'Create a bug report from this support request.'
        return Link('+makebug', text, summary, icon='add',
                    enabled=not self.has_bugs)


class TicketSetContextMenu(ContextMenu):

    usedfor = ITicketSet
    links = ['findproduct', 'finddistro']

    def findproduct(self):
        text = 'Find Upstream Product'
        return Link('/products', text, icon='search')

    def finddistro(self):
        text = 'Find Distribution'
        return Link('/distros', text, icon='search')

