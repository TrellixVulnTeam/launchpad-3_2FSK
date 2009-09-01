# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).
# pylint: disable-msg=E1002

"""View classes for `IProductSeries`."""

__metaclass__ = type

__all__ = [
    'LinkTranslationsBranchView',
    'ProductSeriesTemplatesView',
    'ProductSeriesTranslationsBzrImportView',
    'ProductSeriesTranslationsExportView',
    'ProductSeriesTranslationsMenu',
    'ProductSeriesTranslationsSettingsView',
    'ProductSeriesUploadView',
    'ProductSeriesView',
    ]

import cgi
import os.path
from bzrlib.revision import NULL_REVISION

from zope.component import getUtility
from zope.publisher.browser import FileUpload

from canonical.launchpad import _
from canonical.launchpad.helpers import is_tar_filename
from canonical.launchpad.webapp import (
    action,
    canonical_url,
    custom_widget,
    enabled_with_permission,
    LaunchpadEditFormView,
    LaunchpadFormView,
    LaunchpadView,
    Link,
    NavigationMenu)
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.menu import structured
from canonical.widgets.itemswidgets import (
    LaunchpadRadioWidgetWithDescription)

from lp.translations.browser.poexportrequest import BaseExportView
from lp.translations.browser.translations import TranslationsMixin
from lp.code.interfaces.branchjob import IRosettaUploadJobSource
from lp.translations.interfaces.potemplate import IPOTemplateSet
from lp.translations.interfaces.productserieslanguage import (
    IProductSeriesLanguageSet)
from lp.translations.interfaces.translations import (
    TranslationsBranchImportMode)
from lp.translations.interfaces.translationimporter import (
    ITranslationImporter)
from lp.translations.interfaces.translationimportqueue import (
    ITranslationImportQueue)
from lp.registry.interfaces.productseries import IProductSeries


class ProductSeriesTranslationsMenuMixIn:
    """Translation menu for `IProductSeries`."""
    def overview(self):
        """Return a link to the overview page."""
        return Link('', 'Overview')

    @enabled_with_permission('launchpad.Edit')
    def templates(self):
        """Return a link to series PO templates."""
        return Link('+templates', 'Templates')

    @enabled_with_permission('launchpad.Edit')
    def settings(self):
        """Return a link to configure the translations settings."""
        return Link('+translations-settings', 'Settings')

    @enabled_with_permission('launchpad.Edit')
    def requestbzrimport(self):
        """Return a link to request a bazaar import."""
        return Link('+request-bzr-import', 'Request Bazaar import')

    @enabled_with_permission('launchpad.Edit')
    def translationupload(self):
        """Return a link to upload translations."""
        return Link('+translations-upload', 'Upload')

    def translationdownload(self):
        """Return a link to download the translations."""
        return Link('+export', 'Download')

    def imports(self):
        """Return a link to the import queue."""
        return Link('+imports', 'Import queue')


class ProductSeriesTranslationsMenu(NavigationMenu,
                                    ProductSeriesTranslationsMenuMixIn):
    """Translations navigation menus for `IProductSeries` objects."""
    usedfor = IProductSeries
    facet = 'translations'
    links = ('overview', 'templates', 'settings', 'requestbzrimport',
             'translationupload', 'translationdownload', 'imports')


class ProductSeriesTranslationsExportView(BaseExportView):
    """Request tarball export of productseries' complete translations.

    Only complete downloads are supported for now; there is no option to
    select languages, and templates are always included.
    """

    @property
    def download_description(self):
        """Current context description used inline in paragraphs."""
        return "%s %s series" % (
            self.context.product.displayname,
            self.context.name)

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    @property
    def page_title(self):
        return "Download translations for %s" % self.download_description


class ProductSeriesTranslationsMixin(object):
    """Common properties for all ProductSeriesTranslations*View classes."""

    @property
    def series_title(self):
        """The series title."""
        return self.context.title.replace(' ', '&nbsp;')

    @property
    def has_imports_enabled(self):
        """Is imports enabled for the series?"""
        return (self.context.translations_autoimport_mode !=
                TranslationsBranchImportMode.NO_IMPORT)

    @property
    def request_bzr_import_url(self):
        """URL to request a bazaar import."""
        return canonical_url(self.context,
                             view_name="+request-bzr-import")

    @property
    def link_branch_url(self):
        """URL to link the series to a branch."""
        return canonical_url(self.context, rootsite="mainsite",
                             view_name="+linkbranch")

    @property
    def translations_settings_url(self):
        """URL to change the translations for the series."""
        return canonical_url(self.context,
                             view_name="+translations-settings")

    @property
    def product_edit_url(self):
        """URL to edit the `IProduct`."""
        return canonical_url(self.context.product, rootsite="mainsite",
                             view_name="+edit")


class ProductSeriesUploadView(LaunchpadView, TranslationsMixin):
    """A view for uploading translations into productseries."""
    def initialize(self):
        """See `LaunchpadFormView`."""
        self.form = self.request.form
        self.processForm()

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    @property
    def page_title(self):
        return "Upload translations to %s %s" % (
            self.context.product.displayname,
            self.context.displayname)

    def processForm(self):
        """Process a form if it was submitted."""
        if not self.request.method == "POST":
            # The form was not posted, we don't do anything.
            return
        self.translationsUpload()

    def translationsUpload(self):
        """Upload new translatable resources related to this IProductSeries.

        Uploads may fail if there are already entries with the same path name
        and uploader (importer) in the queue and the new upload cannot be
        safely matched to any of them.  The user will be informed about the
        failure with a warning message."""
        # XXX henninge 2008-12-03 bug=192925: This code is duplicated for
        # potemplate and pofile and should be unified.

        file = self.request.form['file']
        if not isinstance(file, FileUpload):
            if file == '':
                self.request.response.addErrorNotification(
                    "Ignored your upload because you didn't select a file to"
                    " upload.")
            else:
                # XXX: Carlos Perello Marin 2004-12-30 bug=116:
                # Epiphany seems to have an unpredictable bug with upload
                # forms (or perhaps it's launchpad because I never had
                # problems with bugzilla). The fact is that some uploads don't
                # work and we get a unicode object instead of a file-like
                # object in "file". We show an error if we see that behaviour.
                self.request.response.addErrorNotification(
                    "The upload failed because there was a problem receiving"
                    " the data.")
            return

        filename = file.filename
        content = file.read()

        if len(content) == 0:
            self.request.response.addWarningNotification(
                "Ignored your upload because the uploaded file is empty.")
            return

        translation_import_queue_set = getUtility(ITranslationImportQueue)

        root, ext = os.path.splitext(filename)
        translation_importer = getUtility(ITranslationImporter)
        if ext in translation_importer.supported_file_extensions:
            # Add it to the queue.
            entry = translation_import_queue_set.addOrUpdateEntry(
                filename, content, True, self.user,
                productseries=self.context)
            if entry is None:
                self.request.response.addWarningNotification(
                    "Upload failed.  The name of the file you "
                    "uploaded matched multiple existing "
                    "uploads, for different templates.  This makes it "
                    "impossible to determine which template the new "
                    "upload was for.  Try uploading to a specific "
                    "template: visit the page for the template that you "
                    "want to upload to, and select the upload option "
                    "from there.")
            else:
                self.request.response.addInfoNotification(
                    structured(
                    'Thank you for your upload.  It will be automatically '
                    'reviewed in the next few hours.  If that is not '
                    'enough to determine whether and where your file '
                    'should be imported, it will be reviewed manually by an '
                    'administrator in the coming few days.  You can track '
                    'your upload\'s status in the '
                    '<a href="%s/+imports">Translation Import Queue</a>' %(
                        canonical_url(self.context))))

        elif is_tar_filename(filename):
            # Add the whole tarball to the import queue.
            (num, conflicts) = (
                translation_import_queue_set.addOrUpdateEntriesFromTarball(
                    content, True, self.user,
                    productseries=self.context))

            if num > 0:
                if num == 1:
                    plural_s = ''
                    itthey = 'it'
                else:
                    plural_s = 's'
                    itthey = 'they'
                self.request.response.addInfoNotification(
                    structured(
                    'Thank you for your upload. %d file%s from the tarball '
                    'will be automatically '
                    'reviewed in the next few hours.  If that is not enough '
                    'to determine whether and where your file%s should '
                    'be imported, %s will be reviewed manually by an '
                    'administrator in the coming few days.  You can track '
                    'your upload\'s status in the '
                    '<a href="%s/+imports">Translation Import Queue</a>' %(
                        num, plural_s, plural_s, itthey,
                        canonical_url(self.context))))
                if len(conflicts) > 0:
                    if len(conflicts) == 1:
                        warning = (
                            "A file could not be uploaded because its "
                            "name matched multiple existing uploads, for "
                            "different templates." )
                        ul_conflicts = (
                            "The conflicting file name was:<br /> "
                            "<ul><li>%s</li></ul>" % cgi.escape(conflicts[0]))
                    else:
                        warning = (
                            "%d files could not be uploaded because their "
                            "names matched multiple existing uploads, for "
                            "different templates." % len(conflicts))
                        ul_conflicts = (
                            "The conflicting file names were:<br /> "
                            "<ul><li>%s</li></ul>" % (
                            "</li><li>".join(map(cgi.escape, conflicts))))
                    self.request.response.addWarningNotification(
                        structured(
                        warning + "  This makes it "
                        "impossible to determine which template the new "
                        "upload was for.  Try uploading to a specific "
                        "template: visit the page for the template that you "
                        "want to upload to, and select the upload option "
                        "from there.<br />"+ ul_conflicts))
            else:
                if len(conflicts) == 0:
                    self.request.response.addWarningNotification(
                        "Upload ignored.  The tarball you uploaded did not "
                        "contain any files that the system recognized as "
                        "translation files.")
                else:
                    self.request.response.addWarningNotification(
                        "Upload failed.  One or more of the files you "
                        "uploaded had names that matched multiple existing "
                        "uploads, for different templates.  This makes it "
                        "impossible to determine which template the new "
                        "upload was for.  Try uploading to a specific "
                        "template: visit the page for the template that you "
                        "want to upload to, and select the upload option "
                        "from there.")
        else:
            self.request.response.addWarningNotification(
                "Upload failed because the file you uploaded was not"
                " recognised as a file that can be imported.")


class ProductSeriesView(LaunchpadView, TranslationsMixin):
    """A view to show a series with translations."""
    def initialize(self):
        """See `LaunchpadFormView`."""
        # Whether there is more than one PO template.
        self.has_multiple_templates = (
            self.context.getCurrentTranslationTemplates().count() > 1)

    @property
    def productserieslanguages(self):
        """Get ProductSeriesLanguage objects to display.

        Produces a list containing a ProductSeriesLanguage object for
        each language this product has been translated into, and for each
        of the user's preferred languages. Where the series has no
        ProductSeriesLanguage for that language, we use a
        DummyProductSeriesLanguage.
        """

        if self.context.potemplate_count == 0:
            return None

        # Find the existing PSLs.
        productserieslangs = list(self.context.productserieslanguages)

        # Make a set of the existing languages.
        existing_languages = set(psl.language for psl in productserieslangs)

        # Find all the preferred languages which are not in the set of
        # existing languages, and add a dummy PSL for each of them.
        if self.user is not None:
            productserieslangset = getUtility(IProductSeriesLanguageSet)
            for lang in self.user.languages:
                if lang.code != 'en' and lang not in existing_languages:
                    if self.single_potemplate:
                        pot = self.context.getCurrentTranslationTemplates()[0]
                        pofile = pot.getPOFileByLang(lang.code)
                        if pofile is None:
                            pofile = pot.getDummyPOFile(lang.code)
                        productserieslang = productserieslangset.getDummy(
                            self.context, lang, pofile=pofile)
                    else:
                        productserieslang = productserieslangset.getDummy(
                            self.context, lang)
                    productserieslangs.append(
                        productserieslang)

        return sorted(productserieslangs,
                      key=lambda a: a.language.englishname)

    @property
    def has_translation_documentation(self):
        """Are there translation instructions for this product."""
        translation_group = self.context.product.translationgroup
        return (translation_group is not None and
                translation_group.translation_guide_url is not None)

    @property
    def single_potemplate(self):
        """Does this ProductSeries have exactly one POTemplate."""
        return self.context.potemplate_count == 1


class SettingsRadioWidget(LaunchpadRadioWidgetWithDescription):
    """Remove the confusing hint under the widget."""

    def __init__(self, field, vocabulary, request):
        super(SettingsRadioWidget, self).__init__(field, vocabulary, request)
        self.hint = None


class ProductSeriesTranslationsSettingsView(LaunchpadEditFormView,
                                            ProductSeriesTranslationsMixin):
    """Edit settings for translations import and export."""

    schema = IProductSeries
    field_names = ['translations_autoimport_mode']
    settings_widget = custom_widget('translations_autoimport_mode',
                  SettingsRadioWidget)

    def __init__(self, context, request):
        super(ProductSeriesTranslationsSettingsView, self).__init__(
            context, request)
        self.cancel_url = canonical_url(self.context)

    @action(u"Save settings", name="save_settings")
    def change_settings_action(self, action, data):
        """Change the translation settings."""
        if (self.context.translations_autoimport_mode !=
            data['translations_autoimport_mode']
            ):
            self.updateContextFromData(data)
            # Request an initial upload of translation files.
            getUtility(IRosettaUploadJobSource).create(
                self.context.branch, NULL_REVISION)
        else:
            self.updateContextFromData(data)
        self.request.response.addInfoNotification(
            _("The settings have been updated."))


class ProductSeriesTranslationsBzrImportView(LaunchpadFormView,
                                             ProductSeriesTranslationsMixin):
    """Edit settings for translations import and export."""

    schema = IProductSeries
    field_names = []

    def __init__(self, context, request):
        super(ProductSeriesTranslationsBzrImportView, self).__init__(
            context, request)
        self.cancel_url = canonical_url(self.context)

    def validate(self, action):
        """See `LaunchpadFormView`."""
        if self.context.branch is None:
            self.addError(
                "Please set the official Bazaar branch first.")

    @action(u"Request one-time import", name="request_import")
    def request_import_action(self, action, data):
        """ Request an upload of translation files. """
        job = getUtility(IRosettaUploadJobSource).create(
            self.context.branch, NULL_REVISION, True)
        if job is None:
            self.addError(
                _("Your request could not be filed."))
        else:
            self.request.response.addInfoNotification(
                _("The import has been requested."))


class ProductSeriesTemplatesView(LaunchpadView):
    """Show a list of all templates for the ProductSeries."""

    is_distroseries = False

    def iter_templates(self):
        """Return an iterator of all `IPOTemplates` for the series."""
        potemplateset = getUtility(IPOTemplateSet)
        return potemplateset.getSubset(productseries=self.context)

    def can_administer(self, template):
        """Can the user administer the template?"""
        return check_permission('launchpad.Admin', template)


class LinkTranslationsBranchView(LaunchpadEditFormView):
    """View to set the series' translations export branch."""

    schema = IProductSeries
    field_names = ['translations_branch']

    label = "Set translations export branch"

    @property
    def cancel_url(self):
        return canonical_url(self.context) + '/+translations-settings'

    @property
    def next_url(self):
        return canonical_url(self.context) + '/+translations-settings'

    @property
    def page_title(self):
        return "Set translations export branch for %s" % (self.context.title)

    @action(_('Update'), name='update')
    def update_action(self, action, data):
        self.updateContextFromData(data)
        self.request.response.addInfoNotification(
            'Translations export branch updated.')
