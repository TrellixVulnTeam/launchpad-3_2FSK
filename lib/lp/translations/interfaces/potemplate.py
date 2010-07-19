# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0211,E0213

from zope.interface import Attribute, Interface
from zope.schema import (
    Bool, Bytes, Choice, Datetime, Int, Object, Text, TextLine)
from lazr.enum import DBEnumeratedType, DBItem
from lazr.restful.fields import CollectionField, Reference
from lazr.restful.declarations import (
    exported, export_as_webservice_entry, export_read_operation,
    operation_returns_collection_of)

from canonical.launchpad.fields import ParticipatingPersonChoice
from canonical.launchpad.interfaces.launchpad import NotFoundError
from canonical.launchpad.interfaces.librarian import ILibraryFileAlias
from lp.registry.interfaces.distribution import IDistribution
from lp.translations.interfaces.rosettastats import IRosettaStats
from lp.registry.interfaces.sourcepackagename import (
    ISourcePackageName)
from lp.translations.interfaces.translationfileformat import (
    TranslationFileFormat)
from canonical.launchpad import _


__metaclass__ = type

__all__ = [
    'IHasTranslationTemplates',
    'IPOTemplate',
    'IPOTemplateSet',
    'IPOTemplateSharingSubset',
    'IPOTemplateSubset',
    'IPOTemplateWithContent',
    'LanguageNotFound',
    'TranslationPriority',
    ]


class LanguageNotFound(NotFoundError):
    """Raised when a a language does not exist in the database."""


class TranslationPriority(DBEnumeratedType):
    """Translation Priority

    Translations in Rosetta can be assigned a priority. This is used in a
    number of places. The priority stored on the translation itself is set
    by the upstream project maintainers, and used to identify the
    translations they care most about. For example, if Apache were nearing a
    big release milestone they would set the priority on those POTemplates
    to 'high'. The priority is also used by TranslationEfforts to indicate
    how important that POTemplate is to the effort. And lastly, an
    individual translator can set the priority on his personal subscription
    to a project, to determine where it shows up on his list.  """

    HIGH = DBItem(1, """
        High

        This translation should be shown on any summary list of translations
        in the relevant context. For example, 'high' priority projects show
        up on the home page of a TranslationEffort or Project in Rosetta.
        """)

    MEDIUM = DBItem(2, """
        Medium

        A medium priority POTemplate should be shown on longer lists and
        dropdowns lists of POTemplates in the relevant context.  """)

    LOW = DBItem(3, """
        Low

        A low priority POTemplate should only show up if a comprehensive
        search or complete listing is requested by the user.  """)


class IPOTemplate(IRosettaStats):
    """A translation template."""

    export_as_webservice_entry(
        singular_name='translation_template',
        plural_name='translation_templates')

    id = exported(Int(
        title=u"The translation template id.",
        required=True, readonly=True))

    name = exported(TextLine(
        title=_("Template name"),
        description=_("The name of this PO template, for example "
            "'evolution-2.2'. Each translation template has a "
            "unique name in its package. It's important to get this "
            "correct, because Launchpad will recommend alternative "
            "translations based on the name."),
        required=True))

    translation_domain = exported(TextLine(
        title=_("Translation domain"),
        description=_("The translation domain for a translation template. "
            "Used with PO file format when generating MO files for inclusion "
            "in language pack or MO tarball exports."),
        required=True))

    description = exported(Text(
        title=_("Description"),
        description=_("Please provide a brief description of the content "
            "of this translation template, for example, telling translators "
            "if this template contains strings for end-users or other "
            "developers."),
        required=False))

    header = Text(
        title=_('Header'),
        description=_("The standard template header in its native format."),
        required=True)

    iscurrent = exported(Bool(
        title=_("Accept translations?"),
        description=_(
            "If unchecked, people can no longer change the template's "
            "translations."),
        required=True,
        default=True), exported_as='active')

    owner = exported(ParticipatingPersonChoice(
        title=_("Owner"),
        required=True,
        description=_(
            "The owner of the template in Launchpad can edit the template "
            "and change it's status, and can also upload new versions "
            "of the template when a new release is made or when the "
            "translation strings have been changed during development."),
        vocabulary="ValidOwner"))

    productseries = Choice(
        title=_("Series"),
        required=False,
        vocabulary="ProductSeries")

    distroseries = Choice(
        title=_("Series"),
        required=False,
        vocabulary="DistroSeries")

    sourcepackagename = Choice(
        title=_("Source Package Name"),
        description=_(
            "The source package that uses this template."),
        required=False,
        vocabulary="SourcePackageName")

    from_sourcepackagename = Choice(
        title=_("From Source Package Name"),
        description=_(
            "The source package this template comes from (set it only if it's"
            " different from the previous 'Source Package Name'."),
        required=False,
        vocabulary="SourcePackageName")

    sourcepackageversion = TextLine(
        title=_("Source Package Version"),
        required=False)

    binarypackagename = Choice(
        title=_("Binary Package"),
        description=_(
            "The package in which this template's translations are "
            "installed."),
        required=False,
        vocabulary="BinaryPackageName")

    languagepack = exported(Bool(
        title=_("Include translations for this template in language packs?"),
        description=_(
            "Check this box if this template is part of a language pack so "
            "its translations should be exported that way."),
        required=True,
        default=False), exported_as='exported_in_languagepacks')

    path = exported(TextLine(
        title=_(
            "Path of the template in the source tree, including filename."),
        required=False))

    source_file = Object(
        title=_('Source file for this translation template'),
        readonly=True, schema=ILibraryFileAlias)

    source_file_format = exported(Choice(
        title=_("File format for the source file"),
        required=False,
        vocabulary=TranslationFileFormat), exported_as='format')

    priority = exported(Int(
        title=_('Priority'),
        required=True,
        default=0,
        description=_(
            'A number that describes how important this template is. Often '
            'there are multiple templates, and you can use this as a way '
            'of indicating which are more important and should be '
            'translated first. Pick any number - higher priority '
            'templates will generally be listed first.')))

    datecreated = Datetime(
        title=_('When this translation template was created.'), required=True,
        readonly=True)

    translationgroups = Attribute(
        _('''
            The `ITranslationGroup` objects that handle translations for this
            template.
            There can be several because they can be inherited from project to
            product, for example.
            '''))

    translationpermission = Choice(
        title=_('Translation permission'),
        required=True,
        readonly=True,
        description=_('''
            The permission system which is used for this translation template.
            This is inherited from the product, project and/or distro in which
            the translation template is found.
            '''),
        vocabulary='TranslationPermission')

    pofiles = exported(
        CollectionField(
            title=_("All translation files that exist for this template."),
            # Really IPOFile, see _schema_circular_imports.py.
            value_type=Reference(schema=Interface)),
        exported_as='translation_files')

    relatives_by_name = Attribute(
        _('All `IPOTemplate` objects that have the same name asa this one.'))

    relatives_by_source = Attribute(
        _('''All `IPOTemplate` objects that have the same source.
            For example those that came from the same productseries or the
            same source package.
            '''))

    displayname = TextLine(
        title=_('The translation template brief name.'), required=True,
        readonly=True)

    title = TextLine(
        title=_('The translation template title.'), required=True,
        readonly=True)

    product = Object(
        title=_('The `IProduct` to which this translation template belongs.'),
        required=False, readonly=True,
        # Really IProduct, see _schema_circular_imports.py.
        schema=Interface)

    distribution = Object(
        title=_(
            'The `IDistribution` to which this translation template '
            'belongs.'),
        readonly=True, schema=IDistribution)

    messagecount = exported(Int(
        title=_('The number of translation messages for this template.'),
        required=True, readonly=True),
        exported_as='message_count')

    language_count = exported(Int(
        title=_('The number of languages for which we have translations.'),
        required=True, readonly=True))

    translationtarget = Attribute(
        _('''
            The direct object in which this template is attached.
            This will either be an `ISourcePackage` or an `IProductSeries`.
            '''))

    date_last_updated = exported(Datetime(
        title=_('Date for last update'),
        required=True))

    uses_english_msgids = Bool(
        title=_("Uses English strings as msgids"), readonly=True,
        description=_("""
            Some formats, such as Mozilla's XPI, use symbolic msgids where
            gettext uses the original English strings to identify messages.
            """))

    def __iter__():
        """Return an iterator over current `IPOTMsgSet` in this template."""

    def clearPOFileCache():
        """Clear `POFile`-related cached data.

        As you work with a `POTemplate`, some data about its `POFile`s
        gets cached.  But if you're iterating over the template's
        translations one `POFile` at a time, you can drop any cached
        data about a `POFile` as soon as you're done with it.  Use this
        method to do that.
        """

    def getHeader():
        """Return an `ITranslationHeaderData` representing its header."""

    def getPOTMsgSetByMsgIDText(singular_text, plural_text=None,
                                only_current=False, context=None):
        """Return `IPOTMsgSet` indexed by `singular_text` from this template.

        If the key is a string or a unicode object, returns the
        `IPOTMsgSet` in this template that has a primary message ID
        with the given text.

        If `only_current` is True, then get only current message sets.

        If `context` is not None, look for a message set with that context
        value.

        If `plural_text` is not None, also filter by that plural text.

        If no `IPOTMsgSet` is found, return None.
        """

    def getPOTMsgSetBySequence(sequence):
        """Return the `IPOTMsgSet` with the given sequence or None.

        :arg sequence: The sequence number when the `IPOTMsgSet` appears.

        The sequence number must be > 0.
        """

    def getPOTMsgSets(current=True, prefetch=True):
        """Return an iterator over `IPOTMsgSet` objects in this template.

        :param current: Whether to limit the search to current
            POTMsgSets.
        :param prefetch: Whether to prefetch the `POMsgID`s attached to
            the POTMsgSets.  This is for optimization only.
        :return: All current POTMsgSets for the template if `current` is
            True, or all POTMsgSets for the template otherwise.
        """

    def getTranslationCredits():
        """Return an iterator over translation credits.

        Return all `IPOTMsgSet` objects in this template that are translation
        credits.
        """

    def getPOTMsgSetsCount(current=True):
        """Return the number of POTMsgSet objects related to this object.

        The current argument is used to select only current POTMsgSets or all
        of them.
        """

    def __getitem__(key):
        """Same as getPOTMsgSetByMsgIDText(), with only_current=True
        """

    def getPOTMsgSetByID(id):
        """Return the POTMsgSet object related to this POTemplate with the id.

        If there is no POTMsgSet with that id and for that POTemplate, return
        None.
        """

    def languages():
        """This Return the set of languages for which we have POFiles for
        this POTemplate.

        NOTE that variants are simply ignored, if we have three variants for
        en_GB we will simply return the one with variant=NULL.
        """

    def getPOFileByPath(path):
        """Get the PO file of the given path.

        Return None if there is no such `IPOFile`.
        """

    def getPOFileByLang(language_code, variant=None):
        """Get the PO file of the given language and (potentially)
        variant. If no variant is specified then the translation
        without a variant is given.

        Return None if there is no such POFile.
        """

    def hasPluralMessage():
        """Test whether this template has any message sets which are plural
        message sets."""

    def export():
        """Return a serialized version as a string using its native format."""

    def exportWithTranslations():
        """Return an ExportedTranslationFile using its native format.

        It include all translations available.
        """

    def expireAllMessages():
        """Mark all of our message sets as not current (sequence=0)"""

    def newPOFile(language_code, variant=None, create_sharing=True):
        """Return a new `IPOFile` for the given language.

        Raise LanguageNotFound if the language does not exist in the
        database.

        We should not have already an `IPOFile` for the given language_code
        and variant.

        :param language_code: The code of the language for which to create
            the IPOFile.
        :param variant: Optional language variant.
        :param requester: The requester person. If given and will have edit
            permissions on the IPOFile, it becomes the owner. Otherwise
            rosetta_experts own the file.
        :param create_sharing: Whether the IPOFile should be created in all
            sharing templates, too. Should only be set to False to avoid
            loops when creating a new IPOTemplate.
        """

    def getDummyPOFile(language_code, variant=None, requester=None):
        """Return a DummyPOFile if there isn't already a persistent `IPOFile`

        Raise `LanguageNotFound` if the language does not exist in the
        database.

        This method is designed to be used by read only actions. This way you
        only create a POFile when you actually need to store data.

        We should not have already a POFile for the given language_code and
        variant.
        """

    def createPOTMsgSetFromMsgIDs(msgid_singular, msgid_plural=None,
                                  context=None, sequence=0):
        """Creates a new template message in the database.

        :param msgid_singular: A reference to a singular msgid.
        :param msgid_plural: A reference to a plural msgid.  Can be None
            if the message is not a plural message.
        :param context: A context for the template message differentiating
            it from other template messages with exactly the same `msgid`.
        :param sequence: The sequence number of this POTMsgSet within this
            POTemplate. If 0, it is considered obsolete.
        :return: The newly created message set.
        """

    def createMessageSetFromText(singular_text, plural_text,
                                 context=None, sequence=0):
        """Creates a new template message in the database using strings.

        Similar to createMessageSetFromMessageID, but takes text objects
        (unicode or string) along with textual context, rather than a
        message IDs.

        :param singular_text: The string for the singular msgid.
        :param msgid_plural: The string for the plural msgid.  Must be None
            if the message is not a plural message.
        :param context: A context for the template message differentiating
            it from other template messages with exactly the same `msgid`.
        :param sequence: The sequence number of this POTMsgSet within this
            POTemplate. If 0, it is considered obsolete.
        :return: The newly created message set.
        """

    def getOrCreateSharedPOTMsgSet(singular_text, plural_text, context=None):
        """Finds an existing shared POTMsgSet to use or creates a new one.

        :param singular_text: string containing singular form.
        :param plural_text: string containing plural form.
        :param context: context to differentiate between two messages with
        same singular_text and plural_text.
        :return: existing or new shared POTMsgSet with a sequence of 0
        in this POTemplate.
        """

    def importFromQueue(entry_to_import, logger=None, txn=None):
        """Import given queue entry.

        :param entry_to_import: `TranslationImportQueueEntry` specifying an
            approved import for this `POTemplate`
        :param logger: optional logger to report problems to.
        :param txn: optional transaction manager for intermediate
            commits.  Used to prevent long-running transactions that can
            lead to deadlocks.

        :return: a tuple of the subject line and body for a notification email
            to be sent to the uploader.
        """

    def getTranslationRows():
        """Return the `IVPOTexport` objects for this template."""


class IPOTemplateSubset(Interface):
    """A subset of POTemplate."""

    sourcepackagename = Object(
        title=_(
            'The `ISourcePackageName` associated with this subset.'),
        schema=ISourcePackageName)

    distroseries = Object(
        title=_(
            'The `IDistroSeries` associated with this subset.'),
        # Really IDistroSeries, see _schema_circular_imports.py.
        schema=Interface)

    productseries = Object(
        title=_(
            'The `IProductSeries` associated with this subset.'),
        # Really IProductSeries, see _schema_circular_imports.py.
        schema=Interface)

    iscurrent = Bool(
        title=_("Filter for iscurrent flag."),
        description=_(
            "The filter for the iscurrent flag that this subset should "
            "apply. The filter is disabled if it is None"),
        required=False)

    title = TextLine(
        title=_('The translation file title.'), required=True, readonly=True)

    def __iter__():
        """Return an iterator over all POTemplate for this subset."""

    def __len__():
        """Return the number of `IPOTemplate` objects in this subset."""

    def __getitem__(name):
        """Get a POTemplate by its name."""

    def new(name, translation_domain, path, owner):
        """Create a new template for the context of this Subset."""

    def getPOTemplateByName(name):
        """Return the `IPOTemplate` with the given name or None.

        The `IPOTemplate` is restricted to this concrete `IPOTemplateSubset`.
        """

    def getPOTemplateByTranslationDomain(translation_domain):
        """Return the `IPOTemplate` with the given translation_domain.

        The `IPOTemplate` is restricted to this concrete
        `IPOTemplateSubset`.  If multiple templates in the subset match,
        a warning is logged.

        :return: The single template in this `IPOTemplateSubset` with
            the given translation_domain, if there is exactly one match.
            None otherwise.
        """

    def getPOTemplateByPath(path):
        """Return the `IPOTemplate` from this subset that has the given path.

        Return None if there is no such `IPOTemplate`.
        """

    def getAllOrderByDateLastUpdated():
        """Return an iterator over all POTemplate for this subset.

        The iterator will give entries sorted by modification.
        """

    def getClosestPOTemplate(path):
        """Return a `IPOTemplate` with a path closer to given path, or None.

        If there is no `IPOTemplate` with a common path with the given,
        argument or if there are more than one `IPOTemplate` with the same
        common path, and both are the closer ones, returns None.
        """

    def findUniquePathlessMatch(filename):
        """Find the one `POTemplate` with given filename, if there is one.

        Directory paths are ignored in the search.  Only the filename
        itself is matched.

        :param filename: A filename, without any directory component.
        :return: The one `POTemplate` in the subset whose filename
            matches `filename`, if there is exactly one.  Otherwise,
            None.
        """


class IPOTemplateSet(Interface):
    """A set of PO templates."""

    def __iter__():
        """Return an iterator over all PO templates."""

    def getByIDs(ids):
        """Return all PO templates with the given IDs."""

    def getAllByName(name):
        """Return a list with all PO templates with the given name."""

    def getAllOrderByDateLastUpdated():
        """Return an iterator over all POTemplate sorted by modification."""

    def getSubset(distroseries=None, sourcepackagename=None,
                  productseries=None, iscurrent=None,
                  ordered_by_names=False):
        """Return a POTemplateSubset object depending on the given arguments.
        """

    def getSharingSubset(distribution=None, sourcepackagename=None,
                         products=None):
        """Return a POTemplateSharingSubset object depending on the given
        arguments.
        """

    def getSubsetFromImporterSourcePackageName(
        distroseries, sourcepackagename, iscurrent=None):
        """Return a POTemplateSubset based on the origin sourcepackagename.
        """

    def getPOTemplateByPathAndOrigin(path, productseries=None,
        distroseries=None, sourcepackagename=None):
        """Return an `IPOTemplate` that is stored at 'path' in source code and
           came from the given arguments.

        Return None if there is no such `IPOTemplate`.
        """

    def compareSharingPrecedence(left, right):
        """Sort comparison: order sharing templates by precedence.

        Sort using this function to order sharing templates from most
        representative to least representative, as per the message-sharing
        migration spec.
        """


class IPOTemplateSharingSubset(Interface):
    """A subset of sharing PO templates."""

    distribution = Object(
        title=_(
            'The `IDistribution` associated with this subset.'),
        schema=IDistribution)

    product = Object(
        title=_(
            'The `IProduct` associated with this subset.'),
        # Really IProduct, see _schema_circular_imports.py.
        schema=Interface)

    sourcepackagename = Object(
        title=_(
            'The `ISourcePackageName` associated with this subset.'),
        schema=ISourcePackageName,
        required=False)

    def getSharingPOTemplates(potemplate_name):
        """Find all sharing templates of the given name.

        For distributions this method requires that sourcepackagename is set.

        :param potemplate_name: The name of the template for which to find
            sharing equivalents.
        :return: A list of all potemplates of the same name from all series.
        """

    def groupEquivalentPOTemplates(name_pattern=None):
        """Within given IProduct or IDistribution, find equivalent templates.

        Partitions all templates in the given context into equivalence
        classes. This means that is groups all templates together for which
        the tuple (template.name, sourcepackagename.name) is identical. This
        tuple is called the equivalence class. When working with a product,
        sourcepackagename.name is always None, so effectively the name of
        the template is the class.

        :param name_pattern: an optional regex pattern indicating which
            template names are to be merged. If you're operating on
            a distribution, you may want to pass a this to avoid doing too
            much in one go.
        :return: a dict mapping each equivalence class to a list of
            `POTemplate`s in that class, each sorted from most to least
            representative.
        """


class IPOTemplateWithContent(IPOTemplate):
    """Interface for an `IPOTemplate` used to create the new POTemplate form.
    """

    content = Bytes(
        title=_("PO Template File to Import"),
        required=True)


class IHasTranslationTemplates(Interface):
    """An entity that has translation templates attached.

    Examples include `ISourcePackage`, `IDistroSeries`, and `IProductSeries`.
    """

    has_translation_templates = Bool(
        title=_("Does this object have any translation templates?"),
        readonly=True)

    has_current_translation_templates = Bool(
        title=_("Does this object have current translation templates?"),
        readonly=True)

    def getTemplatesCollection():
        """Return templates as a `TranslationTemplatesCollection`.

        The collection selects all `POTemplate`s attached to the
        translation target that implements this interface.
        """

    def getCurrentTemplatesCollection():
        """Return `TranslationTemplatesCollection` of current templates.

        A translation template is considered active when both
        `IPOTemplate`.iscurrent and the `official_rosetta` flag for its
        containing `Product` or `Distribution` are set to True.
        """
        # XXX JeroenVermeulen 2010-07-16 bug=605924: Move the
        # official_rosetta distinction into browser code.

    def getCurrentTranslationTemplates(just_ids=False):
        """Return an iterator over all active translation templates.

        :param just_ids: If True, return only the `POTemplate.id` rather
            than the full `POTemplate`.  Used to save time on retrieving
            and deserializing the objects from the database.

        A translation template is considered active when both
        `IPOTemplate`.iscurrent and the `official_rosetta` flag for its
        containing `Product` or `Distribution` are set to True.
        """
        # XXX JeroenVermeulen 2010-07-16 bug=605924: Move the
        # official_rosetta distinction into browser code.

    def getCurrentTranslationFiles(just_ids=False):
        """Return an iterator over all active translation files.

        A translation file is active if it's attached to an
        active translation template.
        """

    def getObsoleteTranslationTemplates():
        """Return an iterator over its not active translation templates.

        A translation template is considered not active when any of
        `IPOTemplate`.iscurrent or `IDistribution`.official_rosetta flags
        are set to False.
        """

    @export_read_operation()
    @operation_returns_collection_of(IPOTemplate)
    def getTranslationTemplates():
        """Return an iterator over all its translation templates.

        The returned templates are either obsolete or current.
        """

    def getTranslationTemplateFormats():
        """A list of native formats for all current translation templates.
        """

    def getTemplatesAndLanguageCounts():
        """List tuples of `POTemplate` and its language count.

        A template's language count is the number of `POFile`s that
        exist for it.
        """

class ITranslationTemplatesCollection(Interface):
    """A `Collection` of `POTemplate`s."""

    def joinOuterPOFile(language=None):
        """Outer-join `POFile` into the collection.

        :return: A `TranslationTemplatesCollection` with an added outer
            join to `POFile`.
        """

    def select():
        """Blah."""


# Monkey patch for circular import avoidance done in
# _schema_circular_imports.py
