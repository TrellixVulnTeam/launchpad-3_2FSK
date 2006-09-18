# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Language interfaces."""

__metaclass__ = type

__all__ = [
    'ILanguage',
    'ILanguageSet',
    ]

from zope.interface import Interface, Attribute

class ILanguage(Interface):
    """A Language."""

    id = Attribute("""XXX""")

    code = Attribute("""The ISO 639 code for this language.""")

    englishname = Attribute("The English name of this language.")

    nativename = Attribute("The name of this language in the language itself.")

    pluralforms = Attribute("The number of plural forms this language has.")

    pluralexpression = Attribute("""The expression that relates a number of
        items to the appropriate plural form.""")

    translators = Attribute("""A list of Persons that are interested on 
        translate into this language.""")

    countries = Attribute("""A list of Countries where this language is spoken
        in.""")

    visible = Attribute(
        """Whether this language should ususally be visible or not.""")

    direction = Attribute("""The direction of text in this language.""")

    displayname = Attribute(
        "The displayname of the language (a constructed value)")

    alt_suggestion_language = Attribute("A language which can reasonably "
        "be expected to have good suggestions for translations in this "
        "language.")

    dashedcode = Attribute("""The language code in a form suitable for use
        in HTML and XML files.""")

    abbreviated_text_dir = Attribute("""The abbreviated form of the text
        direction, suitable for use in HTML files.""")

class ILanguageSet(Interface):
    """The collection of languages."""

    common_languages = Attribute("An iterator over languages that are "
        "not hidden.")

    def __iter__():
        """Returns an iterator over all languages."""

    def __getitem__(code):
        """Get a language by its code."""

    def keys():
        """Return an iterator over the language codes."""

    def canonicalise_language_code(code):
        """Convert a language code to standard xx_YY form."""

    def codes_to_languages(codes):
        """Convert a list of ISO language codes to language objects.

        Unrecognised language codes are ignored.
        """

    def getLanguageAndVariantFromString(language_string):
        """Return the ILanguage and variant that language_string represents.

        If language_string doesn't represent a know language, return None.
        """
