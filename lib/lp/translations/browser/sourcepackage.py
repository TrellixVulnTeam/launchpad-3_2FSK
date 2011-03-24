# Copyright 2011 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser views for translation pages for sourcepackages."""

__metaclass__ = type

__all__ = [
    'SourcePackageTranslationsExportView',
    'SourcePackageTranslationsView',
    'SourcePackageTranslationSharingStatus',
    ]

import cgi

from zope.publisher.interfaces import NotFound

from canonical.launchpad.webapp import (
    canonical_url,
    enabled_with_permission,
    Link,
    NavigationMenu,
    )
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.menu import structured
from canonical.launchpad.webapp.publisher import LaunchpadView
from lp.app.enums import ServiceUsage
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.services.features import getFeatureFlag
from lp.translations.browser.poexportrequest import BaseExportView
from lp.translations.browser.translations import TranslationsMixin
from lp.translations.browser.translationsharing import (
    TranslationSharingDetailsMixin,
    )
from lp.translations.interfaces.translations import (
    TranslationsBranchImportMode,
    )
from lp.translations.model.translationpackagingjob import TranslationMergeJob
from lp.translations.utilities.translationsharinginfo import (
    has_upstream_template,
    get_upstream_sharing_info,
    )


class SharingDetailsPermissionsMixin:

    def can_edit_sharing_details(self):
        return check_permission('launchpad.Edit', self.context.distroseries)


class SourcePackageTranslationsView(TranslationsMixin,
                                    SharingDetailsPermissionsMixin,
                                    TranslationSharingDetailsMixin):

    @property
    def potemplates(self):
        return list(self.context.getCurrentTranslationTemplates())

    @property
    def label(self):
        return "Translations for %s" % self.context.displayname

    def is_sharing(self):
        return has_upstream_template(self.context)

    @property
    def sharing_productseries(self):
        infos = get_upstream_sharing_info(self.context)
        if len(infos) == 0:
            return None

        productseries, template = infos[0]
        return productseries

    def getTranslationTarget(self):
        """See `TranslationSharingDetailsMixin`."""
        return self.context


class SourcePackageTranslationsMenu(NavigationMenu):
    usedfor = ISourcePackage
    facet = 'translations'
    links = ('overview', 'download', 'imports')

    def imports(self):
        text = 'Import queue'
        return Link('+imports', text, site='translations')

    @enabled_with_permission('launchpad.ExpensiveRequest')
    def download(self):
        text = 'Download'
        enabled = bool(self.context.getCurrentTranslationTemplates().any())
        return Link('+export', text, icon='download', enabled=enabled,
                    site='translations')

    def overview(self):
        return Link('', 'Overview', icon='info', site='translations')


class SourcePackageTranslationsExportView(BaseExportView):
    """Request tarball export of all translations for a source package."""

    page_title = "Download"

    @property
    def download_description(self):
        """Current context description used inline in paragraphs."""
        return "%s package in %s %s" % (
            self.context.sourcepackagename.name,
            self.context.distroseries.distribution.displayname,
            self.context.distroseries.displayname)

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    @property
    def label(self):
        return "Download translations for %s" % self.download_description


class SourcePackageTranslationSharingDetailsView(
                                            LaunchpadView,
                                            SharingDetailsPermissionsMixin):
    """Details about translation sharing."""

    page_title = "Sharing details"

    def initialize(self):
        if not getFeatureFlag('translations.sharing_information.enabled'):
            raise NotFound(self.context, '+sharing-details')
        super(SourcePackageTranslationSharingDetailsView, self).initialize()
        has_no_upstream_templates = (
            self.is_configuration_complete and
            not has_upstream_template(self.context))
        if has_no_upstream_templates:
            self.request.response.addInfoNotification(
                structured(
                'No upstream templates have been found yet. Please follow '
                'the import process by going to the '
                '<a href="%s">Translation Import Queue</a> of the '
                'upstream project series.' %(
                canonical_url(
                    self.context.productseries, rootsite='translations',
                    view_name="+imports"))))
        if self.is_merge_job_running:
            self.request.response.addInfoNotification(
                'Translations are currently being linked by a background '
                'job. When that job has finished, translations will be '
                'shared with the upstream project.')

    @property
    def branch_link(self):
        if self.has_upstream_branch:
            # Normally should use BranchFormatterAPI(branch).link(None), but
            # on this page, that information is redundant.
            title = cgi.escape(self.upstream_branch.unique_name)
            url = canonical_url(self.upstream_branch)
        else:
            title = ''
            url = '#'
        return '<a class="sprite branch link" href="%s">%s</a>' % (url, title)

    def makeConfigCompleteCSS(self, complete, disable, lowlight):
        if complete:
            classes = ['sprite', 'yes']
        else:
            classes = ['sprite', 'no']
        if disable:
            classes.append('unseen')
        if lowlight:
            classes.append("lowlight")
        return ' '.join(classes)

    @property
    def configuration_complete_class(self):
        if self.is_configuration_complete:
            return ""
        return "unseen"

    @property
    def configuration_incomplete_class(self):
        if not self.is_configuration_complete:
            return ""
        return "unseen"

    @property
    def packaging_incomplete_class(self):
        return self.makeConfigCompleteCSS(
            False, self.is_packaging_configured, False)
        classes = ['sprite', 'no']
        if self.is_packaging_configured:
            classes.append('unseen')
        return ' '.join(classes)

    @property
    def packaging_complete_class(self):
        return self.makeConfigCompleteCSS(
            True, not self.is_packaging_configured, False)

    @property
    def branch_incomplete_class(self):
        return self.makeConfigCompleteCSS(
            False, self.has_upstream_branch, not self.is_packaging_configured)

    @property
    def branch_complete_class(self):
        return self.makeConfigCompleteCSS(
            True, not self.has_upstream_branch,
            not self.is_packaging_configured)

    @property
    def translations_disabled_class(self):
        return self.makeConfigCompleteCSS(
            False, self.is_upstream_translations_enabled,
            not self.is_packaging_configured)

    @property
    def translations_enabled_class(self):
        return self.makeConfigCompleteCSS(
            True, not self.is_upstream_translations_enabled,
            not self.is_packaging_configured)

    @property
    def upstream_sync_disabled_class(self):
        return self.makeConfigCompleteCSS(
            False, self.is_upstream_synchronization_enabled,
            not self.is_packaging_configured)

    @property
    def upstream_sync_enabled_class(self):
        return self.makeConfigCompleteCSS(
            True, not self.is_upstream_synchronization_enabled,
            not self.is_packaging_configured)

    @property
    def is_packaging_configured(self):
        """Is a packaging link defined for this branch?"""
        return self.context.direct_packaging is not None

    @property
    def no_item_class(self):
        """CSS class for 'no' items."""
        css_class = "sprite no"
        if self.is_packaging_configured:
            return css_class
        else:
            return css_class + " lowlight"

    @property
    def upstream_branch(self):
        if not self.is_packaging_configured:
            return None
        return self.context.direct_packaging.productseries.branch

    @property
    def has_upstream_branch(self):
        """Does the upstream series have a source code branch?"""
        return self.upstream_branch is not None

    @property
    def is_upstream_translations_enabled(self):
        """Are Launchpad translations enabled for the upstream series?"""
        if not self.is_packaging_configured:
            return False
        product = self.context.direct_packaging.productseries.product
        return product.translations_usage in (
            ServiceUsage.LAUNCHPAD, ServiceUsage.EXTERNAL)

    @property
    def is_upstream_synchronization_enabled(self):
        """Is automatic synchronization of upstream translations enabled?"""
        if not self.is_packaging_configured:
            return False
        series = self.context.direct_packaging.productseries
        return (
            series.translations_autoimport_mode ==
            TranslationsBranchImportMode.IMPORT_TRANSLATIONS)

    @property
    def is_configuration_complete(self):
        """Is anything missing in the set up for translation sharing?"""
        # A check if the required packaging link exists is implicitly
        # done in the implementation of the other properties.
        return (
            self.has_upstream_branch and
            self.is_upstream_translations_enabled and
            self.is_upstream_synchronization_enabled)

    @property
    def is_merge_job_running(self):
        """Is a merge job running for this source package?"""
        if not self.is_packaging_configured:
            return False
        return TranslationMergeJob.getNextJobStatus(
            self.context.direct_packaging) is not None

    def template_info(self):
        """Details about translation templates.

        :return: A list of dictionaries containing details about each
            template. Each dictionary contains:
                'name': The name of the template
                'package_template': The package template (may be None)
                'upstream_template': The corresponding upstream template
                    (may be None)
                'status': one of the string 'linking', 'shared',
                    'only in Ubuntu', 'only in upstream'
        """
        info = {}
        templates_on_this_side = self.context.getCurrentTranslationTemplates()
        for template in templates_on_this_side:
            info[template.name] = {
                'name': template.name,
                'package_template': template,
                'upstream_template': None,
                'status': 'only in Ubuntu',
                }
        if self.is_packaging_configured:
            upstream_templates = (
                self.context.productseries.getCurrentTranslationTemplates())
            for template in upstream_templates:
                if template.name in info:
                    info[template.name]['upstream_template'] = template
                    if self.is_merge_job_running:
                        info[template.name]['status'] = 'linking'
                    else:
                        info[template.name]['status'] = 'shared'
                else:
                    info[template.name] = {
                        'name': template.name,
                        'package_template': None,
                        'upstream_template': template,
                        'status': 'only in upstream',
                        }
        info = info.values()
        return sorted(info, key=lambda template: template['name'])
