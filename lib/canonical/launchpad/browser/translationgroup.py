# Copyright 2005 Canonical Ltd.  All rights reserved.

"""Browser code for translation groups."""

__metaclass__ = type
__all__ = ['TranslationGroupNavigation',
           'TranslationGroupSetNavigation',
           'TranslationGroupView',
           'TranslationGroupSetContextMenu',
           'TranslationGroupContextMenu',
           'TranslationGroupAddTranslatorView',
           'TranslationGroupReassignmentView',
           'TranslationGroupSetAddView']

import operator

from zope.event import notify
from zope.app.event.objectevent import ObjectCreatedEvent
from zope.app.form.browser.add import AddView
from zope.component import getUtility

from canonical.launchpad.browser.launchpad import RosettaContextMenu
from canonical.launchpad.interfaces import (
    ITranslationGroup, ITranslationGroupSet, ITranslator, ITranslatorSet,
    ILanguageSet, IPersonSet, ILaunchBag, NotFoundError
    )
from canonical.launchpad.browser.person import ObjectReassignmentView
from canonical.launchpad.webapp import (
    action, canonical_url, enabled_with_permission, GetitemNavigation,
    LaunchpadFormView, Link
    )


class TranslationGroupNavigation(GetitemNavigation):

    usedfor = ITranslationGroup


class TranslationGroupSetNavigation(GetitemNavigation):

    usedfor = ITranslationGroupSet


class TranslationGroupSetContextMenu(RosettaContextMenu):
    usedfor = ITranslationGroupSet


class TranslationGroupContextMenu(RosettaContextMenu):
    usedfor = ITranslationGroup
    links = RosettaContextMenu.links + ['appoint', 'reassign']

    @enabled_with_permission('launchpad.Edit')
    def appoint(self):
        return Link('+appoint', "Appoint translator")

    @enabled_with_permission('launchpad.Edit')
    def reassign(self):
        return Link('+reassign', "Change owner")



class TranslationGroupView:

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.notices = []

        self.parseUrlNotices()

    def parseUrlNotices(self):
        """Parse any notice message as an argument to the page."""

        # Check if we have the 'removed' key as an argument. This argument is
        # used by the +rm form to tell us 'who' was removed from 'where'.
        form_removed = self.request.form.get('removed', '')
        if '-' in form_removed:
            # The key exists and follows the format we expect:
            # languagecode-personame
            code, name = form_removed.split('-', 1)

            try:
                language = getUtility(ILanguageSet)[code]
            except NotFoundError:
                # We got a non valid language code.
                language = None

            translator = getUtility(IPersonSet).getByName(name)

            if language is not None and translator is not None:
                # The language and the person got as arguments are valid in
                # our system, so we should show the message:
                self.notices.append(
                    '%s removed as translator for %s.' % (
                        translator.browsername, language.displayname))

    def removals(self):
        """Remove a translator/team for a concrete language."""
        if 'remove' in self.request.form:
            code = self.request.form['remove']
            try:
                translator = self.context[code]
            except NotFoundError:
                translator = None

            new_url = '.'
            if translator is not None:
                new_url = '%s?removed=%s-%s' % (
                            new_url, translator.language.code,
                            translator.translator.name)

                self.context.remove_translator(translator)

            self.request.response.redirect(new_url)

    def translator_list(self):
        result = []
        for item in self.context.translators:
            result.append({'lang': item.language.englishname,
                           'person': item.translator,
                           'code': item.language.code,
                           'datecreated': item.datecreated})
        result.sort(key=operator.itemgetter('lang'))
        return result


class TranslationGroupAddTranslatorView(LaunchpadFormView):
    """View class for the "appoint a translator" page"""

    schema = ITranslator
    field_names = ['language', 'translator']

    @action("Add", name="add")
    def add_action(self, action, data):
        """Appoint a translator to do translations for given language.

        Create a translator who, within this group, will be responsible for
        the selected language.  Within a translation group, a language can
        have at most one translator.  Of course the translator may be either a
        person or a group, however.
        """
        language = data.get('language')
        translator = data.get('translator')
        getUtility(ITranslatorSet).new(self.context, language, translator)

        self.next_url = canonical_url(self.context)

    def validate(self, data):
        """Do not allow an appointment to overwrite an existing translator.

        We don't allow a translator to be appointed for a language that
        already has a translator within that group.  If we did, it would be
        too easy accidentally to replace a translator, e.g. by picking the
        wrong language in this form.
        """
        language = data.get('language')
        if self.context.query_translator(language):
            self.setFieldError('language',
                "There is already a translator for this language")


class TranslationGroupReassignmentView(ObjectReassignmentView):
    """View class for changing translation group owner."""

    @property
    def contextName(self):
        return self.context.title or self.context.name

    @property
    def next_url(self):
        return canonical_url(self.context)


class TranslationGroupSetAddView(AddView):

    __used_for__ = ITranslationGroupSet

    def __init__(self, context, request):
        self.request = request
        self.context = context
        self._nextURL = '.'
        AddView.__init__(self, context, request)

    def createAndAdd(self, data):
        # Add the owner information for the new translation group.
        owner = getUtility(ILaunchBag).user
        if not owner:
            raise AssertionError(
                "User must be authenticated to create a translation group")

        group = getUtility(ITranslationGroupSet).new(
            name=data['name'],
            title=data['title'],
            summary=data['summary'],
            owner=owner)
        notify(ObjectCreatedEvent(group))
        self._nextURL = group.name
        return group

    def nextURL(self):
        return self._nextURL

