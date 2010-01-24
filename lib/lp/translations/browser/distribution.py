# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Translations browser views for distributions."""

__metaclass__ = type

__all__ = [
    'DistributionLanguagePackAdminView',
    'DistributionSetTranslationPolicyView',
    'DistributionView',
    ]

import operator

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.webapp import (
    action, canonical_url, enabled_with_permission, LaunchpadEditFormView,
    LaunchpadView, Link)
from canonical.launchpad.webapp.menu import NavigationMenu
from lp.registry.interfaces.distribution import IDistribution
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.browser.distribution import DistributionEditView
from lp.translations.browser.translations import TranslationsMixin


class DistributionTranslationsMenu(NavigationMenu):

    usedfor = IDistribution
    facet = 'translations'
    links = ['overview', 'translation_policy', 'language_pack_admin', 'imports']

    def overview(self):
        text = 'Overview'
        link = canonical_url(self.context, rootsite='translations')
        return Link(link, text)

    @enabled_with_permission('launchpad.Edit')
    def translation_policy(self):
        text = 'Settings'
        return Link('+translation-policy', text)

    @enabled_with_permission('launchpad.TranslationsAdmin')
    def language_pack_admin(self):
        text = 'Language pack admin'
        return Link('+select-language-pack-admin', text, icon='edit')

    def imports(self):
        text = 'Import queue'
        return Link('+imports', text)


class DistributionLanguagePackAdminView(LaunchpadEditFormView):
    """Browser view to change the language pack administrator."""

    schema = IDistribution
    label = "Select the language pack administrator"
    page_title = "Set language pack administrator"
    field_names = ['language_pack_admin']

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    @property
    def next_url(self):
        return canonical_url(self.context)

    @property
    def page_title(self):
        return 'Change the %s language pack administrator' % (
            self.context.displayname)

    @action("Change", name='change')
    def change_action(self, action, data):
        self.updateContextFromData(data)


class DistributionView(LaunchpadView):
    """Default Distribution view class."""

    label = "Translations overview"

    @cachedproperty
    def translation_focus(self):
        """Return the IDistroSeries where the translators should work.

        If ther isn't a defined focus, we return latest series.
        """
        if self.context.translation_focus is None:
            return self.context.currentseries
        else:
            return self.context.translation_focus

    def secondary_translatable_series(self):
        """Return a list of IDistroSeries that aren't the translation_focus.

        It only includes the ones that are still supported.
        """
        series = [
            series
            for series in self.context.series
            if (series.status != SeriesStatus.OBSOLETE
                and (self.translation_focus is None or
                     self.translation_focus.id != series.id))
            ]

        return sorted(series, key=operator.attrgetter('version'),
                      reverse=True)


class DistributionSetTranslationPolicyView(TranslationsMixin, DistributionEditView):
    label = "Set permissions and policies"
    page_title = "Permissions and policies"
    field_names = ["translationgroup", "translationpermission"]

    @property
    def page_title(self):
        return "Set translation permissions for %s" % (
            self.context.displayname)

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    @property
    def next_url(self):
        return self.cancel_url

    @action('Change', name='change')
    def edit(self, action, data):
        self.updateContextFromData(data)
