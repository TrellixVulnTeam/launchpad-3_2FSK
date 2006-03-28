# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Interfaces for efficient PO file exports."""

__metaclass__ = type

__all__ = ('IVPOExportSet', 'IVPOExport')

from zope.interface import Interface, Attribute

class IVPOExportSet(Interface):
    """A collection of IVPOExport-providing rows."""

    def get_pofile_rows(potemplate, language, variant=None,
        included_obsolete=True):
        """Return all rows which belong to a particular PO file."""

    def get_potemplate_rows(potemplate, include_translations=True):
        """Return all rows which belong to a particular PO template.

        :arg include_translations: Whether the exported rows should include
            translations.
        """

    def get_distrorelease_pofiles(release, date=None, component=None,
        languagepack=None):
        """Get a list of PO files which would be contained in an export of a
        distribtuion release.

        The filtering is done based on the 'release', last modified 'date',
        archive 'component' and if it belongs to a 'languagepack'
        """

    def get_distrorelease_pofiles_count(release, date=None, component=None,
        languagepack=None):
        """Return the number of PO files which would be contained in an export
        of a distribution release.

        The filtering is done based on the 'release', last modified 'date',
        archive 'component' and if it belongs to a 'languagepack'
        """

    def get_distrorelease_potemplates(release, component=None,
        languagepack=None):
        """Get a list of PO files which would be contained in an export of a
        distribtuion release.

        The filtering is done based on the 'release', last modified 'date',
        archive 'component' and if it belongs to a 'languagepack'
        """

    def get_distrorelease_rows(release, date=None):
        """Return all rows which belong to a particular distribution
        release.
        """


class IVPOExport(Interface):
    """Database view for efficient PO exports."""

    name = Attribute("See IPOTemplateName.name")
    translationdomain = Attribute("See IPOTemplateName.translationdomain")

    potemplate = Attribute("See IPOTemplate")
    distrorelease = Attribute("See IPOTemplate.distrorelease")
    sourcepackagename = Attribute("See IPOTemplate.sourcepackagename")
    productrelease = Attribute("See IPOTemplate.productrelease")
    potheader = Attribute("See IPOTemplate.header")
    languagepack = Attribute("See IPOTemplate.languagepack")

    pofile = Attribute("See IPOFile")
    language = Attribute("See IPOFile.language")
    variant = Attribute("See IPOFile.variant")
    potopcomment = Attribute("See IPOFile.topcomment")
    poheader = Attribute("See IPOFile.header")
    pofuzzyheader = Attribute("See IPOFile.fuzzyheader")
    popluralforms = Attribute("See IPOFile.pluralforms")

    potmsgset = Attribute("See IPOTMsgSet.id")
    potsequence = Attribute("See IPOTMsgSet.sequence")
    potcommenttext = Attribute("See IPOTMsgSet.commenttext")
    sourcecomment = Attribute("See IPOTMsgSet.sourcecomment")
    flagscomment = Attribute("See IPOTMsgSet.flagscomment")
    filereferences = Attribute("See IPOTMsgSet.filereferences")

    pomsgset = Attribute("See IPOMsgSet.id")
    posequence = Attribute("See IPOMsgSet.sequence")
    iscomplete = Attribute("See IPOMsgSet.iscomplete")
    obsolete = Attribute("See IPOMsgSet.obsolete")
    isfuzzy = Attribute("See IPOMsgSet.isfuzzy")
    pocommenttext = Attribute("See IPOMsgSet.commenttext")

    msgidpluralform = Attribute("See IPOMsgIDSighting.pluralform")

    translationpluralform = Attribute("See IPOSelection.pluralform")
    activesubmission = Attribute("See IPOSelection.activesubmission")

    msgid = Attribute("See IPOMsgID.pomsgid")

    translation = Attribute("See IPOTranslation.translation")


