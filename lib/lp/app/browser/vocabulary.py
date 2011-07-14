# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Views which export vocabularies as JSON for widgets."""

__metaclass__ = type

__all__ = [
    'HugeVocabularyJSONView',
    'IPickerEntry',
    'get_person_picker_entry_meta',
    ]

import simplejson

from lazr.restful.interfaces import IWebServiceClientRequest
from zope.app.form.interfaces import MissingInputError
from zope.app.schema.vocabulary import IVocabularyFactory
from zope.component import (
    adapter,
    getUtility,
    )
from zope.component.interfaces import ComponentLookupError
from zope.interface import (
    Attribute,
    implements,
    Interface,
    )
from zope.security.interfaces import Unauthorized

from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.interfaces import NoCanonicalUrl
from canonical.launchpad.webapp.publisher import canonical_url
from lp.app.browser.tales import (
    IRCNicknameFormatterAPI,
    ObjectImageDisplayAPI,
    )
from canonical.launchpad.webapp.vocabulary import IHugeVocabulary
from lp.app.errors import UnexpectedFormData
from lp.code.interfaces.branch import IBranch
from lp.registry.interfaces.person import IPerson
from lp.registry.interfaces.sourcepackagename import ISourcePackageName
from lp.registry.model.pillaraffiliation import IHasAffiliation
from lp.registry.model.sourcepackagename import getSourcePackageDescriptions
from lp.services.features import getFeatureFlag
from lp.soyuz.interfaces.archive import IArchive

# XXX: EdwinGrubbs 2009-07-27 bug=405476
# This limits the output to one line of text, since the sprite class
# cannot clip the background image effectively for vocabulary items
# with more than single line description below the title.
MAX_DESCRIPTION_LENGTH = 120


class IPickerEntry(Interface):
    """Additional fields that the vocabulary doesn't provide.

    These fields are needed by the Picker Ajax widget."""
    description = Attribute('Description')
    image = Attribute('Image URL')
    css = Attribute('CSS Class')
    alt_title = Attribute('Alternative title')
    title_link = Attribute('URL used for anchor on title')
    alt_title_link = Attribute('URL used for anchor on alt title')
    link_css = Attribute('CSS Class for links')
    badges = Attribute('List of badge img attributes')
    meta = Attribute('Meta info about the entry')


class PickerEntry:
    """See `IPickerEntry`."""
    implements(IPickerEntry)

    def __init__(self, description=None, image=None, css=None, alt_title=None,
                 title_link=None, alt_title_link=None, link_css='js-action',
                 badges=None, meta=None):
        self.description = description
        self.image = image
        self.css = css
        self.alt_title = alt_title
        self.title_link = title_link
        self.alt_title_link = alt_title_link
        self.link_css = link_css
        self.badges = badges
        self.meta = meta


@adapter(Interface)
class DefaultPickerEntryAdapter(object):
    """Adapts Interface to IPickerEntry."""

    implements(IPickerEntry)

    def __init__(self, context):
        self.context = context

    def getPickerEntry(self, associated_object, **kwarg):
        """ Construct a PickerEntry for the context of this adapter.

        The associated_object represents the context for which the picker is
        being rendered. eg a picker used to select a bug task assignee will
        have associated_object set to the bug task.
        """
        extra = PickerEntry()
        if hasattr(self.context, 'summary'):
            extra.description = self.context.summary
        display_api = ObjectImageDisplayAPI(self.context)
        extra.css = display_api.sprite_css()
        if extra.css is None:
            extra.css = 'sprite bullet'
        return extra


def get_person_picker_entry_meta(picker_entry):
    """Return the picker entry meta for a given result value."""
    if picker_entry and IPerson.providedBy(picker_entry):
        return "team" if picker_entry.is_team else "person"
    return None


@adapter(IPerson)
class PersonPickerEntryAdapter(DefaultPickerEntryAdapter):
    """Adapts IPerson to IPickerEntry."""

    def getPickerEntry(self, associated_object, **kwarg):
        person = self.context
        extra = super(PersonPickerEntryAdapter, self).getPickerEntry(
            associated_object)

        enhanced_picker_enabled = kwarg.get('enhanced_picker_enabled', False)
        if enhanced_picker_enabled:
            # If the person is affiliated with the associated_object then we
            # can display a badge.
            badge_info = IHasAffiliation(
                associated_object).getAffiliationBadge(person)
            if badge_info:
                extra.badges = [
                    dict(url=badge_info.url, alt=badge_info.alt_text)]

        if person.preferredemail is not None:
            if person.hide_email_addresses:
                extra.description = '<email address hidden>'
            else:
                try:
                    extra.description = person.preferredemail.email
                except Unauthorized:
                    extra.description = '<email address hidden>'

        extra.meta = get_person_picker_entry_meta(person)
        if enhanced_picker_enabled:
            # We will display the person's name (launchpad id) after their
            # displayname.
            extra.alt_title = person.name
            # We will linkify the person's name so it can be clicked to open
            # the page for that person.
            extra.alt_title_link = canonical_url(person, rootsite='mainsite')
            # We will display the person's irc nick(s) after their email
            # address in the description text.
            irc_nicks = None
            if person.ircnicknames:
                irc_nicks = ", ".join(
                    [IRCNicknameFormatterAPI(ircid).displayname()
                    for ircid in person.ircnicknames])
            if irc_nicks:
                if extra.description:
                    extra.description = ("%s (%s)" %
                        (extra.description, irc_nicks))
                else:
                    extra.description = "%s" % irc_nicks

        return extra


@adapter(IBranch)
class BranchPickerEntryAdapter(DefaultPickerEntryAdapter):
    """Adapts IBranch to IPickerEntry."""

    def getPickerEntry(self, associated_object, **kwarg):
        branch = self.context
        extra = super(BranchPickerEntryAdapter, self).getPickerEntry(
            associated_object)
        extra.description = branch.bzr_identity
        return extra


@adapter(ISourcePackageName)
class SourcePackageNamePickerEntryAdapter(DefaultPickerEntryAdapter):
    """Adapts ISourcePackageName to IPickerEntry."""

    def getPickerEntry(self, associated_object, **kwarg):
        sourcepackagename = self.context
        extra = super(
            SourcePackageNamePickerEntryAdapter, self).getPickerEntry(
                associated_object)
        descriptions = getSourcePackageDescriptions([sourcepackagename])
        extra.description = descriptions.get(
            sourcepackagename.name, "Not yet built")
        return extra


@adapter(IArchive)
class ArchivePickerEntryAdapter(DefaultPickerEntryAdapter):
    """Adapts IArchive to IPickerEntry."""

    def getPickerEntry(self, associated_object, **kwarg):
        archive = self.context
        extra = super(ArchivePickerEntryAdapter, self).getPickerEntry(
            associated_object)
        extra.description = '%s/%s' % (archive.owner.name, archive.name)
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
        self.enhanced_picker_enabled = bool(
            getFeatureFlag('disclosure.picker_enhancements.enabled'))

    def __call__(self):
        name = self.request.form.get('name')
        if name is None:
            raise MissingInputError('name', '')

        search_text = self.request.form.get('search_text')
        if search_text is None:
            raise MissingInputError('search_text', '')

        try:
            factory = getUtility(IVocabularyFactory, name)
        except ComponentLookupError:
            raise UnexpectedFormData(
                'Unknown vocabulary %r' % name)

        vocabulary = factory(self.context)

        if IHugeVocabulary.providedBy(vocabulary):
            matches = vocabulary.searchForTerms(search_text)
            total_size = matches.count()
        else:
            matches = list(vocabulary)
            total_size = len(matches)

        batch_navigator = BatchNavigator(matches, self.request)

        result = []
        for term in batch_navigator.currentBatch():
            entry = dict(value=term.token, title=term.title)
            # The canonical_url without just the path (no hostname) can
            # be passed directly into the REST PATCH call.
            api_request = IWebServiceClientRequest(self.request)
            try:
                entry['api_uri'] = canonical_url(
                    term.value, request=api_request,
                    path_only_if_possible=True)
            except NoCanonicalUrl:
                # The exception is caught, because the api_url is only
                # needed for inplace editing via a REST call. The
                # form picker doesn't need the api_url.
                entry['api_uri'] = 'Could not find canonical url.'
            picker_entry = IPickerEntry(term.value).getPickerEntry(
                self.context,
                enhanced_picker_enabled=self.enhanced_picker_enabled)
            if picker_entry.description is not None:
                if len(picker_entry.description) > MAX_DESCRIPTION_LENGTH:
                    entry['description'] = (
                        picker_entry.description[:MAX_DESCRIPTION_LENGTH - 3]
                        + '...')
                else:
                    entry['description'] = picker_entry.description
            if picker_entry.image is not None:
                entry['image'] = picker_entry.image
            if picker_entry.css is not None:
                entry['css'] = picker_entry.css
            if picker_entry.alt_title is not None:
                entry['alt_title'] = picker_entry.alt_title
            if picker_entry.title_link is not None:
                entry['title_link'] = picker_entry.title_link
            if picker_entry.alt_title_link is not None:
                entry['alt_title_link'] = picker_entry.alt_title_link
            if picker_entry.link_css is not None:
                entry['link_css'] = picker_entry.link_css
            if picker_entry.badges is not None:
                entry['badges'] = picker_entry.badges
            if picker_entry.meta is not None:
                entry['meta'] = picker_entry.meta
            result.append(entry)

        self.request.response.setHeader('Content-type', 'application/json')
        return simplejson.dumps(dict(total_size=total_size, entries=result))
