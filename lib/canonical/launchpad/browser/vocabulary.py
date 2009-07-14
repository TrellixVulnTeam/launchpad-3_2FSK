# Copyright 2009 Canonical Ltd.  All rights reserved.

"""Views which export vocabularies as JSON for widgets."""

__metaclass__ = type

__all__ = [
    'HugeVocabularyJSONView',
    'IPickerEntry',
    'person_to_vocabularyjson',
    'default_vocabularyjson_adapter',
    ]

import simplejson

from zope.app import zapi
from zope.app.schema.vocabulary import IVocabularyFactory
from zope.interface import implementer
from zope.component import adapter
from zope.component.interfaces import ComponentLookupError
from zope.interface import Attribute, implements, Interface
from zope.app.form.interfaces import MissingInputError

from lazr.restful.interfaces import IWebServiceClientRequest

from lp.registry.interfaces.person import IPerson

from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.publisher import canonical_url
from canonical.launchpad.webapp.tales import ObjectImageDisplayAPI
from canonical.launchpad.webapp.vocabulary import IHugeVocabulary

MAX_DESCRIPTION_LENGTH = 80


class IPickerEntry(Interface):
    """Additional fields that the vocabulary doesn't provide.

    These fields are needed by the Picker Ajax widget."""
    description = Attribute('Description')
    image = Attribute('Image URL')
    css = Attribute('CSS Class')


class PickerEntry:
    """See `IPickerEntry`."""
    implements(IPickerEntry)

    def __init__(self, description=None, image=None, css=None, api_uri=None):
        self.description = description
        self.image = image
        self.css = css

@implementer(IPickerEntry)
@adapter(Interface)
def default_pickerentry_adapter(obj):
    """Adapts Interface to IPickerEntry."""
    extra = PickerEntry()
    if hasattr(obj, 'summary'):
        extra.description = obj.summary
    display_api = ObjectImageDisplayAPI(obj)
    extra.css = display_api.sprite_css()
    return extra

@implementer(IPickerEntry)
@adapter(IPerson)
def person_to_pickerentry(person):
    """Adapts IPerson to IPickerEntry."""
    extra = default_pickerentry_adapter(person)
    if person.preferredemail is not None:
        extra.description = person.preferredemail.email
    return extra


class HugeVocabularyJSONView:
    """Export vocabularies as JSON.

    This was needed by the Picker widget, but could be
    useful for other AJAX widgets.
    """
    DEFAULT_BATCH_SIZE = 10

    def __init__(self, context, request):
        self.context = context
        self.request = request

    def __call__(self):
        name = self.request.form.get('name')
        if name is None:
            raise MissingInputError('name', '')

        search_text = self.request.form.get('search_text')
        if search_text is None:
            raise MissingInputError('search_text', '')

        try:
            factory = zapi.getUtility(IVocabularyFactory, name)
        except ComponentLookupError:
            raise UnexpectedFormData(
                'Unknown vocabulary %s' % vocabulary_name)

        vocabulary = factory(self.context)

        if not IHugeVocabulary.providedBy(vocabulary):
            raise UnexpectedFormData(
                'Non-huge vocabulary %s' % vocabulary_name)

        matches = vocabulary.searchForTerms(search_text)
        batch_navigator = BatchNavigator(matches, self.request)
        total_size = matches.count()

        result = []
        for term in batch_navigator.currentBatch():
            entry = dict(value=term.token, title=term.title)
            # The canonical_url without just the path (no hostname) can
            # be passed directly into the REST PATCH call.
            api_request = IWebServiceClientRequest(self.request)
            entry['api_uri'] = canonical_url(
                term.value, request=api_request, path_only_if_possible=True)
            picker_entry = IPickerEntry(term.value)
            if picker_entry.description is not None:
                if len(picker_entry.description) > MAX_DESCRIPTION_LENGTH:
                    entry['description'] = (
                        picker_entry.description[:MAX_DESCRIPTION_LENGTH-3]
                        + '...')
                else:
                    entry['description'] = picker_entry.description
            if picker_entry.image is not None:
                entry['image'] = picker_entry.image
            if picker_entry.css is not None:
                entry['css'] = picker_entry.css
            result.append(entry)

        self.request.response.setHeader('Content-type', 'application/json')
        return simplejson.dumps(dict(total_size=total_size, entries=result))
