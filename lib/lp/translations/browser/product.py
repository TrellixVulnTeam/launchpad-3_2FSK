# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Translations browser views for products."""

__metaclass__ = type

__all__ = [
    'ProductSettingsView',
    'ProductTranslationsMenu',
    'ProductView',
    ]

from canonical.launchpad.webapp import (
    canonical_url,
    enabled_with_permission,
    LaunchpadView,
    Link,
    )
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.menu import NavigationMenu
from lp.registry.browser.product import ProductEditView
from lp.registry.interfaces.product import IProduct
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.series import SeriesStatus
from lp.services.propertycache import cachedproperty
from lp.translations.browser.translations import TranslationsMixin


class ProductTranslationsMenu(NavigationMenu):

    usedfor = IProduct
    facet = 'translations'
    links = (
        'overview',
        'settings',
        'translationdownload',
        'imports',
        )

    def imports(self):
        text = 'Import queue'
        return Link('+imports', text, site='translations')

    @enabled_with_permission('launchpad.TranslationsAdmin')
    def settings(self):
        text = 'Change permissions'
        return Link('+settings', text, icon='edit', site='translations')

    @enabled_with_permission('launchpad.AnyPerson')
    def translationdownload(self):
        text = 'Download'
        preferred_series = self.context.primary_translatable
        enabled = (self.context.official_rosetta and
            preferred_series is not None)
        link = ''
        if enabled:
            link = canonical_url(
                preferred_series, rootsite='translations', view_name='+export')
            text = 'Download "%s"' % preferred_series.name

        return Link(link, text, icon='download', enabled=enabled)

    def overview(self):
        text = 'Overview'
        link = canonical_url(self.context, rootsite='translations')
        return Link(link, text, icon='translation')


class ProductSettingsView(TranslationsMixin, ProductEditView):
    label = "Set permissions and policies"
    page_title = "Permissions and policies"
    field_names = [
            "translationgroup",
            "translationpermission",
            "translation_focus",
            ]

    @property
    def cancel_url(self):
        return canonical_url(self.context, rootsite="translations")

    next_url = cancel_url


class ProductView(LaunchpadView):

    label = "Translation overview"

    @cachedproperty
    def uses_translations(self):
        """Whether this product has translatable templates."""
        return (self.context.official_rosetta and
                self.primary_translatable is not None)

    @cachedproperty
    def no_translations_available(self):
        """Has no translation templates but does support translations."""
        return (self.context.official_rosetta and
                self.primary_translatable is None)

    @cachedproperty
    def show_page_content(self):
        """Whether the main content of the page should be shown."""
        return (self.context.official_rosetta or
                check_permission("launchpad.TranslationsAdmin", self.context))

    @cachedproperty
    def primary_translatable(self):
        """Return the context's primary translatable if it's a product series.
        """
        translatable = self.context.primary_translatable

        if not IProductSeries.providedBy(translatable):
            return None

        return translatable

    @cachedproperty
    def untranslatable_series(self):
        """Return series which are not yet set up for translations.

        The list is sorted in alphabetically order and obsolete series
        are excluded.
        """

        translatable = self.context.translatable_series
        return [series for series in self.context.series if (
            series.status != SeriesStatus.OBSOLETE and
            series not in translatable)]
