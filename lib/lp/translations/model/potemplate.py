# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

"""`SQLObject` implementation of `IPOTemplate` interface."""

__metaclass__ = type
__all__ = [
    'get_pofiles_for',
    'HasTranslationTemplatesMixin',
    'POTemplate',
    'POTemplateSet',
    'POTemplateSubset',
    'POTemplateToTranslationFileDataAdapter',
    ]

import datetime
import logging
import os
import re

from psycopg2.extensions import TransactionRollbackError
from sqlobject import (
    BoolCol, ForeignKey, IntCol, SQLMultipleJoin, SQLObjectNotFound,
    StringCol)
from storm.expr import Alias, And, SQL
from storm.store import Store
from zope.component import getAdapter, getUtility
from zope.interface import implements
from zope.security.proxy import removeSecurityProxy

from canonical.cachedproperty import cachedproperty
from canonical.database.constants import DEFAULT
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import (
    SQLBase, quote, flush_database_updates, sqlvalues)
from canonical.launchpad import helpers
from lp.translations.utilities.rosettastats import RosettaStats
from lp.services.worlddata.model.language import Language
from lp.registry.interfaces.person import validate_public_person
from lp.translations.model.pofile import POFile, DummyPOFile
from lp.translations.model.pomsgid import POMsgID
from lp.translations.model.potmsgset import POTMsgSet
from lp.translations.model.translationimportqueue import (
    collect_import_info)
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.webapp.interfaces import NotFoundError
from lp.translations.interfaces.pofile import IPOFileSet
from lp.translations.interfaces.potemplate import (
    IHasTranslationTemplates,
    IPOTemplate,
    IPOTemplateSet,
    IPOTemplateSharingSubset,
    IPOTemplateSubset,
    LanguageNotFound)
from lp.translations.interfaces.translationcommonformat import (
    ITranslationFileData)
from lp.translations.interfaces.translationexporter import (
    ITranslationExporter)
from lp.translations.interfaces.translationfileformat import (
    TranslationFileFormat)
from lp.translations.interfaces.translationimporter import (
    ITranslationImporter,
    TranslationFormatInvalidInputError,
    TranslationFormatSyntaxError)
from lp.translations.interfaces.translationimportqueue import (
    RosettaImportStatus)
from lp.translations.interfaces.vpotexport import IVPOTExportSet
from lp.translations.interfaces.potmsgset import BrokenTextError
from lp.translations.utilities.translation_common_format import (
    TranslationMessageData)


log = logging.getLogger(__name__)


standardPOFileTopComment = ''' %(languagename)s translation for %(origin)s
 Copyright %(copyright)s %(year)s
 This file is distributed under the same license as the %(origin)s package.
 FIRST AUTHOR <EMAIL@ADDRESS>, %(year)s.

'''

standardTemplateHeader = (
"Project-Id-Version: %(origin)s\n"
"Report-Msgid-Bugs-To: FULL NAME <EMAIL@ADDRESS>\n"
"POT-Creation-Date: %(templatedate)s\n"
"PO-Revision-Date: YEAR-MO-DA HO:MI+ZONE\n"
"Last-Translator: FULL NAME <EMAIL@ADDRESS>\n"
"Language-Team: %(languagename)s <%(languagecode)s@li.org>\n"
"MIME-Version: 1.0\n"
"Content-Type: text/plain; charset=UTF-8\n"
"Content-Transfer-Encoding: 8bit\n"
)


standardPOFileHeader = (standardTemplateHeader +
    "Plural-Forms: nplurals=%(nplurals)d; plural=%(pluralexpr)s\n")


def get_pofiles_for(potemplates, language, variant=None):
    """Return list of `IPOFile`s for given templates in given language.

    :param potemplates: a list or sequence of `POTemplate`s.
    :param language: the language that the `IPOFile`s should be for.
    :return: a list of exactly one `IPOFile` for each `POTemplate`
        in `potemplates`.  They will be `POFile`s where available,
        and `DummyPOFile`s where not.
    """
    potemplates = list(potemplates)
    if len(potemplates) == 0:
        return []

    template_ids = [template.id for template in potemplates]

    pofiles = Store.of(potemplates[0]).find(POFile, And(
        POFile.potemplateID.is_in(template_ids),
        POFile.language == language,
        POFile.variant == variant))

    mapping = dict((pofile.potemplate.id, pofile) for pofile in pofiles)
    result = [mapping.get(id) for id in template_ids]
    for entry, pofile in enumerate(result):
        assert pofile == result[entry], "This enumerate confuses me."
        if pofile is None:
            result[entry] = DummyPOFile(potemplates[entry], language, variant)

    return result


class POTemplate(SQLBase, RosettaStats):
    implements(IPOTemplate)

    _table = 'POTemplate'

    productseries = ForeignKey(foreignKey='ProductSeries',
        dbName='productseries', notNull=False, default=None)
    priority = IntCol(dbName='priority', notNull=True, default=DEFAULT)
    name = StringCol(dbName='name', notNull=True)
    translation_domain = StringCol(dbName='translation_domain', notNull=True)
    description = StringCol(dbName='description', notNull=False, default=None)
    copyright = StringCol(dbName='copyright', notNull=False, default=None)
    datecreated = UtcDateTimeCol(dbName='datecreated', default=DEFAULT)
    path = StringCol(dbName='path', notNull=False, default=None)
    source_file = ForeignKey(foreignKey='LibraryFileAlias',
        dbName='source_file', notNull=False, default=None)
    source_file_format = EnumCol(dbName='source_file_format',
        schema=TranslationFileFormat, default=TranslationFileFormat.PO,
        notNull=True)
    iscurrent = BoolCol(dbName='iscurrent', notNull=True, default=True)
    messagecount = IntCol(dbName='messagecount', notNull=True, default=0)
    owner = ForeignKey(
        dbName='owner', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)
    sourcepackagename = ForeignKey(foreignKey='SourcePackageName',
        dbName='sourcepackagename', notNull=False, default=None)
    from_sourcepackagename = ForeignKey(foreignKey='SourcePackageName',
        dbName='from_sourcepackagename', notNull=False, default=None)
    sourcepackageversion = StringCol(dbName='sourcepackageversion',
        notNull=False, default=None)
    distroseries = ForeignKey(foreignKey='DistroSeries',
        dbName='distroseries', notNull=False, default=None)
    header = StringCol(dbName='header', notNull=True)
    binarypackagename = ForeignKey(foreignKey='BinaryPackageName',
        dbName='binarypackagename', notNull=False, default=None)
    languagepack = BoolCol(dbName='languagepack', notNull=True, default=False)
    date_last_updated = UtcDateTimeCol(dbName='date_last_updated',
        default=DEFAULT)

    # joins
    pofiles = SQLMultipleJoin('POFile', joinColumn='potemplate')

    # In-memory cache: maps (language code, variant) to list of POFiles
    # translating this template to that language (variant).
    _cached_pofiles_by_language = None

    _uses_english_msgids = None

    def __storm_invalidated__(self):
        self._cached_pofiles_by_language = None
        self._uses_english_msgids = None

    @property
    def uses_english_msgids(self):
        """See `IPOTemplate`."""
        if self._uses_english_msgids is not None:
            return self._uses_english_msgids

        translation_importer = getUtility(ITranslationImporter)
        format = translation_importer.getTranslationFormatImporter(
            self.source_file_format)
        self._uses_english_msgids = not format.uses_source_string_msgids
        return self._uses_english_msgids

    def __iter__(self):
        """See `IPOTemplate`."""
        for potmsgset in self.getPOTMsgSets():
            yield potmsgset

    def __getitem__(self, key):
        """See `IPOTemplate`."""
        potmsgset = self.getPOTMsgSetByMsgIDText(key, only_current=True)
        if potmsgset is None:
            raise NotFoundError(key)
        else:
            return potmsgset

    @property
    def displayname(self):
        """See `IPOTemplate`."""
        if self.productseries:
            dn = '%s in %s %s' % (
                self.name,
                self.productseries.product.displayname,
                self.productseries.displayname)
        if self.distroseries:
            dn = '%s in %s %s package "%s"' % (
                self.name,
                self.distroseries.distribution.displayname,
                self.distroseries.displayname,
                self.sourcepackagename.name)
        return dn

    @property
    def title(self):
        """See `IPOTemplate`."""
        if self.productseries:
            title = 'Template "%s" in %s %s' % (
                self.name,
                self.productseries.product.displayname,
                self.productseries.displayname)
        if self.distroseries:
            title = 'Template "%s" in %s %s package "%s"' % (
                self.name,
                self.distroseries.distribution.displayname,
                self.distroseries.displayname,
                self.sourcepackagename.name)
        return title

    @property
    def distribution(self):
        """See `IPOTemplate`."""
        if self.distroseries is not None:
            return self.distroseries.distribution
        else:
            return None

    @property
    def product(self):
        """See `IPOTemplate`."""
        if self.productseries is not None:
            return self.productseries.product
        else:
            return None

    @property
    def translationgroups(self):
        """See `IPOTemplate`."""
        ret = []
        if self.distroseries:
            tg = self.distroseries.distribution.translationgroup
            if tg is not None:
                ret.append(tg)
        elif self.productseries:
            product_tg = self.productseries.product.translationgroup
            if product_tg is not None:
                ret.append(product_tg)
            project = self.productseries.product.project
            if project is not None:
                if project.translationgroup is not None:
                    ret.append(project.translationgroup)
        else:
            raise NotImplementedError('Cannot find translation groups.')
        return ret

    @property
    def translationpermission(self):
        """See `IPOTemplate`."""
        if self.distroseries:
            # in the case of a distro template, use the distro translation
            # permission settings
            return self.distroseries.distribution.translationpermission
        elif self.productseries:
            # for products, use the "most restrictive permission" between
            # project and product.
            return self.productseries.product.aggregatetranslationpermission

    @property
    def relatives_by_name(self):
        """See `IPOTemplate`."""
        return POTemplate.select(
            'id <> %s AND name = %s AND iscurrent' % sqlvalues(
                self, self.name), orderBy=['datecreated'])

    @property
    def relatives_by_source(self):
        """See `IPOTemplate`."""
        if self.productseries is not None:
            return POTemplate.select(
                'id <> %s AND productseries = %s AND iscurrent' % sqlvalues(
                    self, self.productseries), orderBy=['name'])
        elif (self.distroseries is not None and
              self.sourcepackagename is not None):
            return POTemplate.select('''
                id <> %s AND
                distroseries = %s AND
                sourcepackagename = %s AND
                iscurrent
                ''' % sqlvalues(
                    self, self.distroseries, self.sourcepackagename),
                orderBy=['name'])
        else:
            raise AssertionError('Unknown POTemplate source.')

    @property
    def language_count(self):
        return Language.select('''
            POFile.language = Language.id AND
            POFile.currentcount + POFile.rosettacount > 0 AND
            POFile.potemplate = %s
            ''' % sqlvalues(self.id),
            clauseTables=['POFile'],
            distinct=True).count()

    @property
    def translationtarget(self):
        if self.productseries is not None:
            return self.productseries
        elif self.distroseries is not None:
            from lp.registry.model.sourcepackage import \
                SourcePackage
            return SourcePackage(distroseries=self.distroseries,
                sourcepackagename=self.sourcepackagename)
        raise AssertionError('Unknown POTemplate translation target')

    def getHeader(self):
        """See `IPOTemplate`."""
        translation_importer = getUtility(ITranslationImporter)
        format_importer = translation_importer.getTranslationFormatImporter(
            self.source_file_format)
        header = format_importer.getHeaderFromString(self.header)
        header.has_plural_forms = self.hasPluralMessage()
        return header

    def _getPOTMsgSetSelectionClauses(self):
        """Return SQL clauses for finding POTMsgSets which belong
        to this POTemplate."""
        clauses = [
            'TranslationTemplateItem.potemplate = %s' % sqlvalues(self),
            'TranslationTemplateItem.potmsgset = POTMsgSet.id',
            ]
        return clauses

    def getPOTMsgSetByMsgIDText(self, singular_text, plural_text=None,
                                only_current=False, context=None):
        """See `IPOTemplate`."""
        clauses = self._getPOTMsgSetSelectionClauses()
        if only_current:
            clauses.append('TranslationTemplateItem.sequence > 0')
        if context is not None:
            clauses.append('context = %s' % sqlvalues(context))
        else:
            clauses.append('context IS NULL')

        # Find a message ID with the given text.
        try:
            singular_msgid = POMsgID.byMsgid(singular_text)
        except SQLObjectNotFound:
            return None
        clauses.append('msgid_singular = %s' % sqlvalues(singular_msgid))

        # Find a message ID for the plural string.
        if plural_text is not None:
            try:
                plural_msgid = POMsgID.byMsgid(plural_text)
                clauses.append('msgid_plural = %s' % sqlvalues(plural_msgid))
            except SQLObjectNotFound:
                return None
        else:
            # You have to be explicit now.
            clauses.append('msgid_plural IS NULL')

        # Find a message set with the given message ID.
        return POTMsgSet.selectOne(' AND '.join(clauses),
                                   clauseTables=['TranslationTemplateItem'])

    def getPOTMsgSetBySequence(self, sequence):
        """See `IPOTemplate`."""
        assert sequence > 0, ('%r is out of range')

        clauses = self._getPOTMsgSetSelectionClauses()
        clauses.append(
            'TranslationTemplateItem.sequence = %s' % sqlvalues(sequence))

        return POTMsgSet.selectOne(' AND '.join(clauses),
                                   clauseTables=['TranslationTemplateItem'])

    def getPOTMsgSets(self, current=True):
        """See `IPOTemplate`."""
        clauses = self._getPOTMsgSetSelectionClauses()

        if current:
            # Only count the number of POTMsgSet that are current.
            clauses.append('TranslationTemplateItem.sequence > 0')

        query = POTMsgSet.select(" AND ".join(clauses),
                                 clauseTables=['TranslationTemplateItem'],
                                 orderBy=['TranslationTemplateItem.sequence'])
        return query.prejoin(['msgid_singular', 'msgid_plural'])

    def getPOTMsgSetsCount(self, current=True):
        """See `IPOTemplate`."""
        results = self.getPOTMsgSets(current)
        return results.count()

    def getPOTMsgSetByID(self, id):
        """See `IPOTemplate`."""
        clauses = self._getPOTMsgSetSelectionClauses()
        clauses.append('POTMsgSet.id = %s' % sqlvalues(id))

        return POTMsgSet.selectOne(' AND '.join(clauses),
                                   clauseTables=['TranslationTemplateItem'])

    def languages(self):
        """See `IPOTemplate`."""
        return Language.select("POFile.language = Language.id AND "
                               "Language.code <> 'en' AND "
                               "POFile.potemplate = %d AND "
                               "POFile.variant IS NULL" % self.id,
                               clauseTables=['POFile', 'Language'],
                               distinct=True
                               )

    def getPOFileByPath(self, path):
        """See `IPOTemplate`."""
        return POFile.selectOneBy(potemplate=self, path=path)

    def getPOFileByLang(self, language_code, variant=None):
        """See `IPOTemplate`."""
        # Consult cache first.
        language_spec = (language_code, variant)
        if self._cached_pofiles_by_language is None:
            self._cached_pofiles_by_language = {}
        elif language_spec in self._cached_pofiles_by_language:
            # Cache contains a remembered POFile for this language.  Don't do
            # the usual get() followed by "is None"; the dict may contain None
            # values to indicate we looked for a POFile and found none.
            return self._cached_pofiles_by_language[language_spec]

        if variant is None:
            variantspec = 'IS NULL'
        elif isinstance(variant, unicode):
            variantspec = (u'= %s' % quote(variant))
        else:
            raise TypeError('Variant must be None or unicode.')

        self._cached_pofiles_by_language[language_spec] = POFile.selectOne("""
            POFile.potemplate = %d AND
            POFile.language = Language.id AND
            POFile.variant %s AND
            Language.code = %s
            """ % (self.id,
                   variantspec,
                   quote(language_code)),
            clauseTables=['Language'])

        return self._cached_pofiles_by_language[language_spec]

    def messageCount(self):
        """See `IRosettaStats`."""
        return self.messagecount

    def currentCount(self, language=None):
        """See `IRosettaStats`."""
        if language is None:
            return 0
        pofile = self.getPOFileByLang(language)
        if pofile is None:
            return 0
        else:
            return pofile.currentCount()

    def updatesCount(self, language=None):
        """See `IRosettaStats`."""
        if language is None:
            return 0
        pofile = self.getPOFileByLang(language)
        if pofile is None:
            return 0
        else:
            pofile.updatesCount()

    def rosettaCount(self, language=None):
        """See `IRosettaStats`."""
        if language is None:
            return 0
        pofile = self.getPOFileByLang(language)
        if pofile is None:
            return 0
        else:
            pofile.rosettaCount()

    def unreviewedCount(self, language=None):
        """See `IRosettaStats`."""
        if language is None:
            return 0
        pofile = self.getPOFileByLang(language)
        if pofile is None:
            return 0
        else:
            pofile.unreviewedCount()

    def _null_quote(self, value):
        if value is None:
            return " IS NULL "
        else:
            return " = %s" % sqlvalues(value)

    def _getPOTMsgSetBy(self, msgid_singular, msgid_plural=None, context=None,
                        sharing_templates=False):
        """Look for a POTMsgSet by msgid_singular, msgid_plural, context.

        If `sharing_templates` is True, and the current template has no such
        POTMsgSet, look through sharing templates as well.
        """
        clauses = [
            'TranslationTemplateItem.potmsgset = POTMsgSet.id',
            ]
        clause_tables = ['TranslationTemplateItem']
        if sharing_templates:
            clauses.extend([
                'TranslationTemplateItem.potemplate = POTemplate.id',
                'TranslationTemplateItem.potmsgset = POTMsgSet.id',
                'POTemplate.name = %s' % sqlvalues(self.name),
                ])
            product = None
            distribution = None
            clause_tables.append('POTemplate')
            if self.productseries is not None:
                product = self.productseries.product
                clauses.extend([
                    'POTemplate.productseries=ProductSeries.id',
                    'ProductSeries.product %s' % self._null_quote(product)
                    ])
                clause_tables.append('ProductSeries')
            elif self.distroseries is not None:
                distribution = self.distroseries.distribution
                clauses.extend([
                    'POTemplate.distroseries=DistroSeries.id',
                    'DistroSeries.distribution %s' % (
                        self._null_quote(distribution)),
                    'POTemplate.sourcepackagename %s' % self._null_quote(
                        self.sourcepackagename),
                    ])
                clause_tables.append('DistroSeries')
        else:
            clauses.append(
                'TranslationTemplateItem.potemplate = %s' % sqlvalues(self))

        clauses.append(
            'POTMsgSet.msgid_singular %s' % self._null_quote(msgid_singular))
        clauses.append(
            'POTMsgSet.msgid_plural %s' % self._null_quote(msgid_plural))
        clauses.append(
            'POTMsgSet.context %s' % self._null_quote(context))

        result = POTMsgSet.select(
            ' AND '.join(clauses),
            clauseTables=clause_tables,
            # If there are multiple messages, make the one from the
            # current POTemplate be returned first.
            orderBy=['(TranslationTemplateItem.POTemplate<>%s)' % (
                sqlvalues(self))])[:2]
        if result and len(list(result)) > 0:
            return result[0]
        else:
            return None

    def hasMessageID(self, msgid_singular, msgid_plural, context=None):
        """See `IPOTemplate`."""
        return bool(
            self._getPOTMsgSetBy(msgid_singular, msgid_plural, context))

    def hasPluralMessage(self):
        """See `IPOTemplate`."""
        clauses = self._getPOTMsgSetSelectionClauses()
        clauses.append(
            'POTMsgSet.msgid_plural IS NOT NULL')
        return bool(POTMsgSet.select(
                ' AND '.join(clauses),
                clauseTables=['TranslationTemplateItem']))

    def export(self):
        """See `IPOTemplate`."""
        translation_exporter = getUtility(ITranslationExporter)
        translation_format_exporter = (
            translation_exporter.getExporterProducingTargetFileFormat(
                self.source_file_format))

        template_file = getAdapter(
            self, ITranslationFileData, 'all_messages')
        exported_file = translation_format_exporter.exportTranslationFiles(
            [template_file])

        try:
            file_content = exported_file.read()
        finally:
            exported_file.close()

        return file_content

    def _generateTranslationFileDatas(self):
        """Yield `ITranslationFileData` objects for translations and self.

        This lets us construct the in-memory representations of the template
        and its translations one by one before exporting them, rather than
        building them all beforehand and keeping them in memory at the same
        time.
        """
        for pofile in self.pofiles:
            yield getAdapter(pofile, ITranslationFileData, 'all_messages')

        yield getAdapter(self, ITranslationFileData, 'all_messages')

    def exportWithTranslations(self):
        """See `IPOTemplate`."""
        translation_exporter = getUtility(ITranslationExporter)
        translation_format_exporter = (
            translation_exporter.getExporterProducingTargetFileFormat(
                self.source_file_format))

        return translation_format_exporter.exportTranslationFiles(
            self._generateTranslationFileDatas())

    def expireAllMessages(self):
        """See `IPOTemplate`."""
        for potmsgset in self.getPOTMsgSets():
            potmsgset.setSequence(self, 0)

    def _lookupLanguage(self, language_code):
        """Look up named `Language` object, or raise `LanguageNotFound`."""
        try:
            return Language.byCode(language_code)
        except SQLObjectNotFound:
            raise LanguageNotFound(language_code)

    def isPOFilePathAvailable(self, path):
        """Can we assign given path to a new `POFile` without clashes?

        Tests for uniqueness within the context of all templates for either
        self's product release series, or the combination of self's distro
        release series and source package (whichever applies).
        """
        pofileset = getUtility(IPOFileSet)
        existing_pofiles = pofileset.getPOFileByPathAndOrigin(
            path, self.productseries, self.distroseries,
            self.sourcepackagename)
        # Convert query to Boolean to turn it into an existence check.
        return not bool(existing_pofiles)

    def _composePOFilePath(self, language, variant=None):
        """Make up a good name for a new `POFile` for given language.

        The name should be unique in this `ProductSeries` or this combination
        of `DistroSeries` and source package.  It is not guaranteed that the
        returned name will be unique, however, to avoid hiding obvious
        naming mistakes.
        """
        potemplate_dir = os.path.dirname(self.path)
        path = '%s-%s.po' % (
            self.translation_domain, language.getFullCode(variant))

        return os.path.join(potemplate_dir, path)

    def _createPOFilesInSharingPOTemplates(self, pofile):
        """Create copies of the given pofile in all sharing potemplates."""
        subset = getUtility(IPOTemplateSet).getSharingSubset(
            distribution=self.distribution,
            sourcepackagename=self.sourcepackagename,
            product=self.product)
        for template in subset.getSharingPOTemplates(self.name):
            template = removeSecurityProxy(template)
            if template is self:
                continue
            language_code = pofile.language.code
            variant = pofile.variant
            existingpo = template.getPOFileByLang(language_code, variant)
            if existingpo is not None:
                continue
            newpopath = template._composePOFilePath(pofile.language, variant)
            pofile = POFile(
                potemplate=template,
                language=pofile.language,
                topcomment=pofile.topcomment,
                header=pofile.header,
                fuzzyheader=pofile.fuzzyheader,
                owner=pofile.owner,
                variant=pofile.variant,
                path=newpopath)

            # Update cache to reflect the change.
            template._cached_pofiles_by_language[language_code,
                                                 variant] = pofile

    def newPOFile(self, language_code, variant=None, requester=None,
                  create_sharing=True):
        """See `IPOTemplate`."""
        # Make sure we don't already have a PO file for this language.
        existingpo = self.getPOFileByLang(language_code, variant)
        assert existingpo is None, (
            'There is already a valid IPOFile (%s)' % existingpo.title)

        # Since we have no PO file for this language yet, create one.
        language = self._lookupLanguage(language_code)

        now = datetime.datetime.now()
        data = {
            'year': now.year,
            'languagename': language.englishname,
            'languagecode': language_code,
            'date': now.isoformat(' '),
            'templatedate': self.datecreated,
            'copyright': '(c) %d Rosetta Contributors and Canonical Ltd'
                         % now.year,
            'nplurals': language.pluralforms or 1,
            'pluralexpr': language.pluralexpression or '0',
            }

        if self.productseries is not None:
            data['origin'] = self.productseries.product.name
        else:
            data['origin'] = self.sourcepackagename.name

        # The default POFile owner is the Rosetta Experts team unless the
        # requester has rights to write into that file.
        dummy_pofile = self.getDummyPOFile(language.code, variant)
        if dummy_pofile.canEditTranslations(requester):
            owner = requester
        else:
            owner = getUtility(ILaunchpadCelebrities).rosetta_experts

        path = self._composePOFilePath(language, variant)

        pofile = POFile(
            potemplate=self,
            language=language,
            topcomment=standardPOFileTopComment % data,
            header=standardPOFileHeader % data,
            fuzzyheader=True,
            owner=owner,
            variant=variant,
            path=path)

        # Update cache to reflect the change.
        self._cached_pofiles_by_language[language_code, variant] = pofile

        if create_sharing:
            self._createPOFilesInSharingPOTemplates(pofile)
        # Store the changes.
        flush_database_updates()

        return pofile

    def getDummyPOFile(self, language_code, variant=None, requester=None):
        """See `IPOTemplate`."""
        # see if a valid one exists.
        existingpo = self.getPOFileByLang(language_code, variant)
        assert existingpo is None, (
            'There is already a valid IPOFile (%s)' % existingpo.title)

        language = self._lookupLanguage(language_code)
        return DummyPOFile(self, language, variant=variant, owner=requester)

    def createPOTMsgSetFromMsgIDs(self, msgid_singular, msgid_plural=None,
                                  context=None):
        """See `IPOTemplate`."""
        return POTMsgSet(
            context=context,
            msgid_singular=msgid_singular,
            msgid_plural=msgid_plural,
            sequence=0,
            potemplate=None,
            commenttext=None,
            filereferences=None,
            sourcecomment=None,
            flagscomment=None)

    def getOrCreatePOMsgID(self, text):
        """Creates or returns existing POMsgID for given `text`."""
        try:
            msgid = POMsgID.byMsgid(text)
        except SQLObjectNotFound:
            # If there are no existing message ids, create a new one.
            # We do not need to check whether there is already a message set
            # with the given text in this template.
            msgid = POMsgID(msgid=text)
        return msgid

    def createMessageSetFromText(self, singular_text, plural_text,
                                 context=None):
        """See `IPOTemplate`."""

        msgid_singular = self.getOrCreatePOMsgID(singular_text)
        if plural_text is None:
            msgid_plural = None
        else:
            msgid_plural = self.getOrCreatePOMsgID(plural_text)
        assert not self.hasMessageID(msgid_singular, msgid_plural, context), (
            "There is already a message set for this template, file and"
            " primary msgid and context '%r'" % context)

        return self.createPOTMsgSetFromMsgIDs(msgid_singular, msgid_plural,
                                              context)

    def getOrCreateSharedPOTMsgSet(self, singular_text, plural_text,
                                   context=None):
        """See `IPOTemplate`."""
        msgid_singular = self.getOrCreatePOMsgID(singular_text)
        if plural_text is None:
            msgid_plural = None
        else:
            msgid_plural = self.getOrCreatePOMsgID(plural_text)
        potmsgset = self._getPOTMsgSetBy(msgid_singular, msgid_plural,
                                         context, sharing_templates=True)
        if potmsgset is None:
            potmsgset = self.createMessageSetFromText(
                singular_text, plural_text, context)
            potmsgset.setSequence(self, 0)
        return potmsgset

    def importFromQueue(self, entry_to_import, logger=None, txn=None):
        """See `IPOTemplate`."""
        assert entry_to_import is not None, "Attempt to import None entry."
        assert entry_to_import.import_into.id == self.id, (
            "Attempt to import entry to POTemplate it doesn't belong to.")
        assert entry_to_import.status == RosettaImportStatus.APPROVED, (
            "Attempt to import non-approved entry.")

        # XXX: JeroenVermeulen 2007-11-29: This method is called from the
        # import script, which can provide the right object but can only
        # obtain it in security-proxied form.  We need full, unguarded access
        # to complete the import.
        entry_to_import = removeSecurityProxy(entry_to_import)

        translation_importer = getUtility(ITranslationImporter)

        subject = 'Translation template import - %s' % self.displayname
        template_mail = 'poimport-template-confirmation.txt'
        errors, warnings = None, None
        try:
            errors, warnings = translation_importer.importFile(
                entry_to_import, logger)
        except (BrokenTextError, TranslationFormatSyntaxError,
                TranslationFormatInvalidInputError, UnicodeDecodeError), (
                exception):
            if logger:
                logger.info(
                    'We got an error importing %s', self.title, exc_info=1)
            subject = 'Import problem - %s' % self.displayname
            if isinstance(exception, UnicodeDecodeError):
                template_mail = 'poimport-bad-encoding.txt'
            else:
                template_mail = 'poimport-syntax-error.txt'
            entry_to_import.setStatus(RosettaImportStatus.FAILED)
            error_text = str(exception)
            entry_to_import.setErrorOutput(error_text)
        else:
            error_text = None
            entry_to_import.setErrorOutput(None)

        replacements = collect_import_info(entry_to_import, self, warnings)
        replacements.update({
            'import_title': 'translation templates for %s' % self.displayname,
            })

        if error_text is not None:
            replacements['error'] = error_text

        entry_to_import.addWarningOutput(replacements['warnings'])

        if entry_to_import.status != RosettaImportStatus.FAILED:
            entry_to_import.setStatus(RosettaImportStatus.IMPORTED)

            # Assign karma to the importer if this is not an automatic import
            # (all automatic imports come from the rosetta expert team).
            celebs = getUtility(ILaunchpadCelebrities)
            rosetta_experts = celebs.rosetta_experts
            if entry_to_import.importer.id != rosetta_experts.id:
                entry_to_import.importer.assignKarma(
                    'translationtemplateimport',
                    product=self.product,
                    distribution=self.distribution,
                    sourcepackagename=self.sourcepackagename)

            # Synchronize changes to database so we can calculate fresh
            # statistics on the server side.
            flush_database_updates()

            # Update cached number of msgsets.
            self.messagecount = self.getPOTMsgSetsCount()

            # The upload affects the statistics for all translations of this
            # template.  Recalculate those as well.  This takes time and
            # covers a lot of data, so if appropriate, break this up
            # into smaller transactions.
            if txn is not None:
                txn.commit()
                txn.begin()

            for pofile in self.pofiles:
                try:
                    pofile.updateStatistics()
                    if txn is not None:
                        txn.commit()
                        txn.begin()
                except TransactionRollbackError, error:
                    if txn is not None:
                        txn.abort()
                        txn.begin()
                    if logger:
                        logger.warn(
                            "Statistics update failed: %s" % unicode(error))

        template = helpers.get_email_template(template_mail, 'translations')
        message = template % replacements
        return (subject, message)


class POTemplateSubset:
    implements(IPOTemplateSubset)

    def __init__(self, sourcepackagename=None, from_sourcepackagename=None,
                 distroseries=None, productseries=None, iscurrent=None):
        """Create a new `POTemplateSubset` object.

        The set of POTemplate depends on the arguments you pass to this
        constructor. The sourcepackagename, from_sourcepackagename,
        distroseries and productseries are just filters for that set.
        In addition, iscurrent sets the filter for the iscurrent flag.
        """
        self.sourcepackagename = sourcepackagename
        self.distroseries = distroseries
        self.productseries = productseries
        self.iscurrent = iscurrent
        self.clausetables = []
        self.orderby = ['id']

        assert productseries is None or distroseries is None, (
            'A product series must not be used with a distro series.')

        assert productseries is not None or distroseries is not None, (
            'Either productseries or distroseries must be not None.')

        if productseries is not None:
            self.query = ('POTemplate.productseries = %s' %
                sqlvalues(productseries.id))
        elif distroseries is not None and from_sourcepackagename is not None:
            self.query = ('POTemplate.from_sourcepackagename = %s AND'
                          ' POTemplate.distroseries = %s ' %
                            sqlvalues(from_sourcepackagename.id,
                                      distroseries.id))
            self.sourcepackagename = from_sourcepackagename
        elif distroseries is not None and sourcepackagename is not None:
            self.query = ('POTemplate.sourcepackagename = %s AND'
                          ' POTemplate.distroseries = %s ' %
                            sqlvalues(sourcepackagename.id, distroseries.id))
        else:
            self.query = (
                'POTemplate.distroseries = DistroSeries.id AND'
                ' DistroSeries.id = %s' % sqlvalues(distroseries.id))
            self.orderby.append('DistroSeries.name')
            self.clausetables.append('DistroSeries')

        # Add the filter for the iscurrent flag if requested.
        if iscurrent is not None:
            self.query += " AND POTemplate.iscurrent=%s" % (
                            sqlvalues(iscurrent))

        # Finally, we sort the query by its path in all cases.
        self.orderby.append('POTemplate.path')

    def __iter__(self):
        """See `IPOTemplateSubset`."""
        res = POTemplate.select(self.query, clauseTables=self.clausetables,
                                orderBy=self.orderby)

        for potemplate in res:
            yield potemplate

    def __len__(self):
        """See `IPOTemplateSubset`."""
        res = POTemplate.select(self.query, clauseTables=self.clausetables)
        return res.count()

    def __getitem__(self, name):
        """See `IPOTemplateSubset`."""
        potemplate = self.getPOTemplateByName(name)
        if potemplate is None:
            raise NotFoundError(name)
        else:
            return potemplate

    @property
    def title(self):
        """See `IPOTemplateSubset`."""
        titlestr = ''
        if self.distroseries:
            titlestr += ' ' + self.distroseries.displayname
        if self.sourcepackagename:
            titlestr += ' ' + self.sourcepackagename.name
        if self.productseries:
            titlestr += ' '
            titlestr += self.productseries.displayname
        return titlestr

    def _copyPOFilesFromSharingTemplates(self, template):
        subset = getUtility(IPOTemplateSet).getSharingSubset(
            distribution=template.distribution,
            sourcepackagename=template.sourcepackagename,
            product=template.product)
        for shared_template in subset.getSharingPOTemplates(template.name):
            shared_template = removeSecurityProxy(shared_template)
            if shared_template is template:
                continue
            for pofile in shared_template.pofiles:
                template.newPOFile(pofile.language.code,
                                   pofile.variant, pofile.owner, False)
            # Do not continue, else it would trigger an existingpo assertion.
            return

    def new(self, name, translation_domain, path, owner):
        """See `IPOTemplateSubset`."""
        header_params = {
            'origin': 'PACKAGE VERSION',
            'templatedate': datetime.datetime.now(),
            'languagename': 'LANGUAGE',
            'languagecode': 'LL',
            }
        template = POTemplate(name=name,
                          translation_domain=translation_domain,
                          sourcepackagename=self.sourcepackagename,
                          distroseries=self.distroseries,
                          productseries=self.productseries,
                          path=path,
                          owner=owner,
                          header=standardTemplateHeader % header_params)
        self._copyPOFilesFromSharingTemplates(template)
        return template

    def getPOTemplateByName(self, name):
        """See `IPOTemplateSubset`."""
        queries = [self.query]
        clausetables = list(self.clausetables)
        queries.append('POTemplate.name = %s' % sqlvalues(name))

        return POTemplate.selectOne(' AND '.join(queries),
            clauseTables=clausetables)

    def getPOTemplateByTranslationDomain(self, translation_domain):
        """See `IPOTemplateSubset`."""
        queries = [self.query]
        clausetables = list(self.clausetables)

        queries.append('POTemplate.translation_domain = %s' % sqlvalues(
            translation_domain))

        # Fetch up to 2 templates, to check for duplicates.
        matches = POTemplate.select(
            ' AND '.join(queries), clauseTables=clausetables, limit=2)

        result = [match for match in matches]
        if len(result) == 0:
            return None
        elif len(result) == 1:
            return result[0]
        else:
            log.warn(
                "Found multiple templates with translation domain '%s'.  "
                "There should be only one."
                % translation_domain)
            return None

    def getPOTemplateByPath(self, path):
        """See `IPOTemplateSubset`."""
        query = '%s AND POTemplate.path = %s' % (self.query, quote(path))

        return POTemplate.selectOne(query, clauseTables=self.clausetables)

    def getAllOrderByDateLastUpdated(self):
        """See `IPOTemplateSet`."""
        query = []
        if self.productseries is not None:
            query.append('productseries = %s' % sqlvalues(self.productseries))
        if self.distroseries is not None:
            query.append('distroseries = %s' % sqlvalues(self.distroseries))
        if self.sourcepackagename is not None:
            query.append('sourcepackagename = %s' % sqlvalues(
                self.sourcepackagename))

        return POTemplate.select(
            ' AND '.join(query), orderBy=['-date_last_updated'])

    def getClosestPOTemplate(self, path):
        """See `IPOTemplateSubset`."""
        if path is None:
            return None

        closest_template = None
        closest_template_path_length = 0
        repeated = False
        for template in self:
            template_path_length = len(
                os.path.commonprefix([template.path, path]))
            if template_path_length > closest_template_path_length:
                # This template is more near than the one we got previously
                closest_template = template
                closest_template_path_length = template_path_length
                repeated = False
            elif template_path_length == closest_template_path_length:
                # We found two templates with the same length, we note that
                # fact, if we don't get a better template, we ignore them and
                # leave it to the admins.
                repeated = True
        if repeated:
            return None
        else:
            return closest_template


class POTemplateSet:
    implements(IPOTemplateSet)

    def __iter__(self):
        """See `IPOTemplateSet`."""
        res = POTemplate.select()
        for potemplate in res:
            yield potemplate

    def getByIDs(self, ids):
        """See `IPOTemplateSet`."""
        values = ",".join(sqlvalues(*ids))
        return POTemplate.select("POTemplate.id in (%s)" % values,
            prejoins=["productseries", "distroseries", "sourcepackagename"],
            orderBy=["POTemplate.id"])

    def getAllByName(self, name):
        """See `IPOTemplateSet`."""
        return POTemplate.selectBy(name=name, orderBy=['name', 'id'])

    def getAllOrderByDateLastUpdated(self):
        """See `IPOTemplateSet`."""
        return POTemplate.select(orderBy=['-date_last_updated'])

    def getSubset(self, distroseries=None, sourcepackagename=None,
                  productseries=None, iscurrent=None):
        """See `IPOTemplateSet`."""
        return POTemplateSubset(
            distroseries=distroseries,
            sourcepackagename=sourcepackagename,
            productseries=productseries,
            iscurrent=iscurrent)

    def getSubsetFromImporterSourcePackageName(self, distroseries,
        sourcepackagename, iscurrent=None):
        """See `IPOTemplateSet`."""
        if distroseries is None or sourcepackagename is None:
            raise AssertionError(
                'distroseries and sourcepackage must be not None.')

        return POTemplateSubset(
            distroseries=distroseries,
            sourcepackagename=sourcepackagename,
            iscurrent=iscurrent)

    def getSharingSubset(self, distribution=None, sourcepackagename=None,
                         product=None):
        """See `IPOTemplateSet`."""
        return POTemplateSharingSubset(self, distribution=distribution,
                                       sourcepackagename=sourcepackagename,
                                       product=product)

    def getPOTemplateByPathAndOrigin(self, path, productseries=None,
        distroseries=None, sourcepackagename=None):
        """See `IPOTemplateSet`."""
        if productseries is not None:
            return POTemplate.selectOne('''
                    POTemplate.iscurrent IS TRUE AND
                    POTemplate.productseries = %s AND
                    POTemplate.path = %s''' % sqlvalues(
                        productseries.id,
                        path)
                    )
        elif sourcepackagename is not None:
            # The POTemplate belongs to a distribution and it could come from
            # another package that the one it's linked at the moment so we
            # first check to find it at IPOTemplate.from_sourcepackagename
            potemplate = POTemplate.selectOne('''
                    POTemplate.iscurrent IS TRUE AND
                    POTemplate.distroseries = %s AND
                    POTemplate.from_sourcepackagename = %s AND
                    POTemplate.path = %s''' % sqlvalues(
                        distroseries.id,
                        sourcepackagename.id,
                        path)
                    )
            if potemplate is not None:
                # There is no potemplate in that 'path' and
                # 'from_sourcepackagename' so we do a search using the usual
                # sourcepackagename.
                return potemplate

            return POTemplate.selectOne('''
                    POTemplate.iscurrent IS TRUE AND
                    POTemplate.distroseries = %s AND
                    POTemplate.sourcepackagename = %s AND
                    POTemplate.path = %s''' % sqlvalues(
                        distroseries.id,
                        sourcepackagename.id,
                        path)
                    )
        else:
            raise AssertionError(
                'Either productseries or sourcepackagename arguments must be'
                ' not None.')

    @staticmethod
    def compareSharingPrecedence(left, right):
        """See IPOTemplateSet."""
        if left == right:
            return 0

        # Current templates always have precedence over non-current ones.
        if left.iscurrent != right.iscurrent:
            if left.iscurrent:
                return -1
            else:
                return 1

        if left.productseries:
            left_series = left.productseries
            right_series = right.productseries
            assert left_series.product == right_series.product
            focus = left_series.product.primary_translatable
        else:
            left_series = left.distroseries
            right_series = right.distroseries
            assert left_series.distribution == right_series.distribution
            focus = left_series.distribution.translation_focus

        # Translation focus has precedence.  In case of a tie, newest
        # template wins.
        if left_series == focus:
            return -1
        elif right_series == focus:
            return 1
        elif left.id > right.id:
            return -1
        else:
            assert left.id < right.id, "Got unordered ids."
            return 1


class POTemplateSharingSubset(object):
    implements(IPOTemplateSharingSubset)

    distribution = None
    sourcepackagename = None
    product = None

    def __init__(self, potemplateset,
                 distribution=None, sourcepackagename=None,
                 product=None):
        assert product or distribution, "Pick a product or distribution!"
        assert not (product and distribution), (
            "Pick a product or distribution, not both!")
        assert distribution or not sourcepackagename, (
            "Picking a source package only makes sense with a distribution.")
        self.potemplateset = potemplateset
        self.distribution = distribution
        self.sourcepackagename = sourcepackagename
        self.product = product


    def _get_potemplate_equivalence_class(self, template):
        """Return whatever we group `POTemplate`s by for sharing purposes."""
        if template.sourcepackagename is None:
            package = None
        else:
            package = template.sourcepackagename.name
        return (template.name, package)

    def _iterate_potemplates(self, name_pattern=None):
        """Yield all templates matching the provided argument.

        This is much like a `IPOTemplateSubset`, except it operates on
        `Product`s and `Distribution`s rather than `ProductSeries` and
        `DistroSeries`.
        """
        if self.product:
            subsets = [
                self.potemplateset.getSubset(productseries=series)
                for series in self.product.serieses
                ]
        else:
            subsets = [
                self.potemplateset.getSubset(
                    distroseries=series,
                    sourcepackagename=self.sourcepackagename)
                for series in self.distribution.serieses
                ]
        for subset in subsets:
            for template in subset:
                if name_pattern is None or re.match(name_pattern,
                                                    template.name):
                    yield template

    def getSharingPOTemplates(self, potemplate_name):
        """See IPOTemplateSharingSubset."""
        if self.distribution is not None:
            assert self.sourcepackagename is not None, (
                   "Need sourcepackagename to select from distribution.")

        escaped_potemplate_name = re.escape(potemplate_name)
        return self._iterate_potemplates("^%s$" % escaped_potemplate_name)

    def groupEquivalentPOTemplates(self, name_pattern=None):
        """See IPOTemplateSharingSubset."""
        equivalents = {}

        for template in self._iterate_potemplates(name_pattern):
            key = self._get_potemplate_equivalence_class(template)
            if key not in equivalents:
                equivalents[key] = []
            equivalents[key].append(template)

        for equivalence_list in equivalents.itervalues():
            # Sort potemplates from "most representative" to "least
            # representative."
            equivalence_list.sort(cmp=POTemplateSet.compareSharingPrecedence)

        return equivalents


class POTemplateToTranslationFileDataAdapter:
    """Adapter from `IPOTemplate` to `ITranslationFileData`."""
    implements(ITranslationFileData)

    def __init__(self, potemplate):
        self._potemplate = potemplate
        self.messages = self._getMessages()

    @cachedproperty
    def path(self):
        """See `ITranslationFileData`."""
        return self._potemplate.path

    @cachedproperty
    def translation_domain(self):
        """See `ITranslationFileData`."""
        return self._potemplate.translation_domain

    @property
    def is_template(self):
        """See `ITranslationFileData`."""
        return True

    @property
    def language_code(self):
        """See `ITraslationFile`."""
        return None

    @cachedproperty
    def header(self):
        """See `ITranslationFileData`."""
        return self._potemplate.getHeader()

    def _getMessages(self):
        """Return a list of `ITranslationMessageData`."""
        potemplate = self._potemplate
        # Get all rows related to this file. We do this to speed the export
        # process so we have a single DB query to fetch all needed
        # information.
        rows = getUtility(IVPOTExportSet).get_potemplate_rows(potemplate)

        messages = []

        for row in rows:
            assert row.potemplate.id == potemplate.id, (
                'Got a row for a different IPOTemplate.')

            # Skip messages which aren't anymore in the PO template.
            if row.sequence == 0:
                continue

            # Create new message set
            msgset = TranslationMessageData()
            msgset.sequence = row.sequence
            msgset.obsolete = False
            msgset.msgid_singular = row.msgid_singular
            msgset.singular_text = row.potmsgset.singular_text
            msgset.msgid_plural = row.msgid_plural
            msgset.plural_text = row.potmsgset.plural_text
            msgset.context = row.context
            msgset.comment = row.comment
            msgset.source_comment = row.source_comment
            msgset.file_references = row.file_references

            if row.flags_comment:
                msgset.flags = set([
                    flag.strip()
                    for flag in row.flags_comment.split(',')
                    if flag
                    ])

            # Store sequences so we can detect later whether we changed the
            # message.
            sequence = row.sequence

            # Store the message.
            messages.append(msgset)

        return messages


class HasTranslationTemplatesMixin:
    """Helper class for implementing `IHasTranslationTemplates`."""
    implements(IHasTranslationTemplates)

    def getCurrentTranslationTemplates(self, just_ids=False):
        """See `IHasTranslationTemplates`."""
        raise NotImplementedError('This must be provided when subclassing.')

    @property
    def has_current_translation_templates(self):
        """Does self have current translation templates?"""
        templates = self.getCurrentTranslationTemplates()
        return bool(templates.any())

    def getCurrentTranslationFiles(self, just_ids=False):
        """See `IHasTranslationTemplates`."""
        # XXX 2009-06-30 Danilo: until Storm can do find() on
        # ResultSets (bug #338255), we need to manually get a select
        # and extend it with another condition.
        current_templates = (
            self.getCurrentTranslationTemplates()._get_select())
        for column in current_templates.columns:
            if column.name == 'id':
                columns = [column]
                break
        assert len(columns) == 1, (
            'There is no ID column in getCurrentTranslationTemplates '
            'select query.')
        current_templates.columns = columns
        templates = Alias(current_templates, 'potemplates')

        if just_ids:
            looking_for = POFile.id
        else:
            looking_for = POFile
        store = Store.of(self)
        if store is None:
            # If self is a non-DB object like SourcePackage,
            # it keeps current store in self._store.
            store = self._store
        return store.using(POFile, templates).find(
            looking_for, POFile.potemplate==SQL('potemplates.id'))

    def getObsoleteTranslationTemplates(self):
        """See `IHasTranslationTemplates`."""
        raise NotImplementedError('This must be provided when subclassing.')

    def getTranslationTemplates(self):
        """See `IHasTranslationTemplates`."""
        raise NotImplementedError('This must be provided when subclassing.')

    def getTranslationTemplateFormats(self):
        """See `IHasTranslationTemplates`."""
        formats_query = self.getCurrentTranslationTemplates().order_by(
            'source_file_format').config(distinct=True)
        formats = helpers.shortlist(
            formats_query.values(POTemplate.source_file_format),
            10)
        return formats
