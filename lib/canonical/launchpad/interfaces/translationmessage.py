# Copyright 2005-2007 Canonical Ltd.  All rights reserved.

from zope.interface import Interface, Attribute
from zope.schema import Bool, Choice, Datetime, Int, List, Object, Text

from canonical.launchpad import _
from canonical.launchpad.interfaces.person import IPerson
from canonical.launchpad.interfaces.pofile import IPOFile
from canonical.launchpad.interfaces.potmsgset import IPOTMsgSet
from canonical.launchpad.interfaces.potranslation import IPOTranslation
from canonical.lazr import DBEnumeratedType, DBItem

__metaclass__ = type
__all__ = [
    'ITranslationMessage',
    'ITranslationMessageSuggestions',
    'RosettaTranslationOrigin',
    'TranslationConflict',
    'TranslationValidationStatus',
    ]


class TranslationConflict(Exception):
    """Someone updated the translation we are trying to update."""


class RosettaTranslationOrigin(DBEnumeratedType):
    """Rosetta Translation Origin

    Translation sightings in Rosetta can come from a variety
    of sources. We might see a translation for the first time
    in CVS, or we might get it through the web, for example.
    This schema documents those options.
    """

    SCM = DBItem(1, """
        Source Control Management Source

        This translation sighting came from a PO File we
        analysed in a source control managements sytem first.
        """)

    ROSETTAWEB = DBItem(2, """
        Rosetta Web Source

        This translation was presented to Rosetta via
        the community web site.
        """)


class TranslationValidationStatus(DBEnumeratedType):
    """Translation Validation Status

    Every time a translation is added to Rosetta we should checked that
    follows all rules to be a valid translation inside a .po file.
    This schema documents the status of that validation.
    """

    UNKNOWN = DBItem(0, """
        Unknown

        This translation has not been validated yet.
        """)

    OK = DBItem(1, """
        Ok

        This translation has been validated and no errors were discovered.
        """)

    UNKNOWNERROR = DBItem(2, """
        Unknown Error

        This translation has an unknown error.
        """)


class ITranslationMessage(Interface):
    """A translation message in a translation file."""

    id = Int(
        title=_("The ID for this translation message"),
        readonly=True, required=True)

    pofile = Object(
        title=_("The translation file from where this translation comes"),
        readonly=True, required=True, schema=IPOFile)

    potmsgset = Object(
        title=_("The template message that this translation is for"),
        readonly=True, required=True, schema=IPOTMsgSet)

    date_created = Datetime(
        title=_("The date we saw this translation first"),
        readonly=True, required=True)

    submitter = Object(
        title=_("The submitter of this translation"),
        readonly=True, required=True, schema=IPerson)

    date_reviewed = Datetime(
        title=_("The date when this message was reviewed for last time"),
        readonly=False, required=False)

    reviewer = Object(
        title=_(
            "The person who did the review and accepted current translations"
            ), readonly=False, required=False, schema=IPerson)

    msgstr0 = Object(
        title=_("Translation for plural form 0 (if any)"),
        required=False, schema=IPOTranslation)

    msgstr1 = Object(
        title=_("Translation for plural form 1 (if any)"),
        required=False, schema=IPOTranslation)

    msgstr2 = Object(
        title=_("Translation for plural form 2 (if any)"),
        required=False, schema=IPOTranslation)

    msgstr3 = Object(
        title=_("Translation for plural form 3 (if any)"),
        required=False, schema=IPOTranslation)

    translations = List(
        title=_("Translations for this message"),
        description=_("""
            All translations for this message, its number will depend on the
            number of plural forms available for its language.
            """), readonly=True, required=True)

    comment_text = Text(
        title=_("Text of translator comment from the translation file"),
        readonly=False, required=False)

    origin = Choice(
        title=_("Where the submission originally came from"),
        values=RosettaTranslationOrigin,
        readonly=True, required=True)

    validation_status = Choice(
        title=_("The status of the validation of the translation"),
        values=TranslationValidationStatus,
        readonly=False, required=True)

    is_current = Bool(
        title=_("Whether this translation is being used in Launchpad"),
        readonly=False, default=False, required=True)

    is_complete = Bool(
        title=_("Whether the translation has all needed plural forms or not"),
        readonly=True, required=True)

    is_fuzzy = Bool(
        title=_("Whether this translation must be checked before use it"),
        readonly=False, default=False, required=True)

    is_imported = Bool(
        title=_(
            "Whether this translation is being used in latest imported file"),
        readonly=False, default=False, required=True)

    was_obsolete_in_last_import = Bool(
        title=_(
            "Whether this translation was obsolete in last imported file"),
        readonly=False, default=False, required=True)

    was_fuzzy_in_last_import = Bool(
        title=_(
            "Whether this imported translation must be checked before use it"
            ), readonly=False, default=False, required=True)

    is_empty = Bool(
        title=_("Whether this message has any translation"),
        readonly=True, required=True)

    messages = Choice(
        title=_("Suggestions"),
        readonly=False, required=True,
        vocabulary="TranslationMessage")

    countries = Choice(
        title=_("Countries"),
        readonly=False, required=False,
        vocabulary="CountryName")

    def destroySelf():
        """Remove this object.

        It must not be referenced by any other object.
        """

    # XXX CarlosPerelloMarin 20071022: We should move this into browser code.
    def makeHTMLID(description, for_potmsgset=None):
        """Unique identifier for self, suitable for use in HTML element ids.

        Constructs an identifier for use in HTML.  This identifier matches the
        format parsed by `BaseTranslationView`.

        :param description: a keyword to be embedded in the id string, e.g.
            "suggestion" or "translation."  Must be suitable for use in an
            HTML element id.
        :param for_potmsgset: the `POTMsgSet` that this is a suggestion or
            translation for.  In the case of a suggestion, that will be a
            different one than this submission's `POMsgSet` is attached to.
            For a translation, on the other hand, it *will* be that
            `POTMsgSet`.  If no value is given, the latter is assumed.
        """


# XXX CarlosPerelloMarin 20071024: We will need to migrate this once we start
# touching view classes.
class ITranslationMessageSuggestions(Interface):
    """Suggested `ITranslationMessage`s for a `POTMsgSet`.

    When displaying `POTMsgSet`s in `POMsgSetView` we display different types
    of suggestions: non-reviewer translations, translations that occur in
    other contexts, and translations in alternate languages. See
    `POMsgSetView._buildSuggestions` for details.
    """
    title = Attribute("The name displayed next to the suggestion, "
                      "indicating where it came from.")
    submissions = Attribute("An iterable of POSubmission objects")
    user_is_official_translator = Bool(
        title=(u'Whether the user is an official translator.'),
        required=True)
