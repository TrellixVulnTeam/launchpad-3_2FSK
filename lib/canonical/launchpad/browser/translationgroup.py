# Copyright 2005 Canonical Ltd.  All rights reserved.

"""Browser code for translation groups."""

__metaclass__ = type
__all__ = ['TranslationGroupNavigation',
           'TranslationGroupSetNavigation',
           'TranslationGroupView',
           'TranslationGroupSetContextMenu',
           'TranslationGroupContextMenu',
           'TranslationGroupAddTranslatorView',
           'TranslationGroupEditView',
           'TranslationGroupAddView']

import operator

from zope.event import notify
from zope.app.event.objectevent import ObjectCreatedEvent
from zope.component import getUtility

from canonical.launchpad.browser.launchpad import RosettaContextMenu
from canonical.launchpad.interfaces import (
    ITranslationGroup, ITranslationGroupSet, ITranslator, ITranslatorSet,
    NotFoundError)
from canonical.launchpad.webapp import (
    action, canonical_url, GetitemNavigation, LaunchpadFormView,
    LaunchpadEditFormView)


class TranslationGroupNavigation(GetitemNavigation):

    usedfor = ITranslationGroup


class TranslationGroupSetNavigation(GetitemNavigation):

    usedfor = ITranslationGroupSet


class TranslationGroupSetContextMenu(RosettaContextMenu):
    usedfor = ITranslationGroupSet


class TranslationGroupContextMenu(RosettaContextMenu):
    usedfor = ITranslationGroup


class TranslationGroupView:

    def __init__(self, context, request):
        self.context = context
        self.request = request
        self.translation_groups = getUtility(ITranslationGroupSet)

    @property
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

    @property
    def next_url(self):
        return canonical_url(self.context)


class TranslationGroupEditView(LaunchpadEditFormView):
    """View class to edit ITranslationGroup details."""

    schema = ITranslationGroup
    field_names = ['name', 'title', 'summary']

    @action("Change")
    def change_action(self, action, data):
        """Edit ITranslationGroup details."""
        self.updateContextFromData(data)

    def validate(self, data):
        """Do not allow an appointment to overwrite an existing translator.

        We don't allow a translator to be appointed for a language that
        already has a translator within that group.  If we did, it would be
        too easy accidentally to replace a translator, e.g. by picking the
        wrong language in this form.
        """
        new_name = data.get('name')
        translation_group = getUtility(ITranslationGroupSet)
        if (self.context.name != new_name):
            try:
                translation_group[new_name]
            except NotFoundError:
                # The new name doesn't exist so it's valid.
                return
            self.setFieldError('name',
                "There is already a translation group with such name")

    @property
    def next_url(self):
        return canonical_url(self.context)


class TranslationGroupAddView(LaunchpadFormView):
    schema = ITranslationGroup
    field_names = ['name', 'title', 'summary']

    @action("Add", name="add")
    def add_action(self, action, data):
        """Add a new translation group to Launchpad."""
        name = data.get('name')
        title = data.get('title')
        summary = data.get('summary')
        self.new_group = getUtility(ITranslationGroupSet).new(
            name=name, title=title, summary=summary, owner=self.user)
        notify(ObjectCreatedEvent(self.new_group))

    def validate(self, data):
        """Do not allow new groups with duplicated names."""
        name = data.get('name')
        try:
            self.context[name]
        except NotFoundError:
            # The given name doesn't exist so it's valid.
            return
        self.setFieldError('name',
            "There is already a translation group with such name")

    @property
    def next_url(self):
        return canonical_url(self.new_group)
