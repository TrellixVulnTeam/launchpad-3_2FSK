# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser views for sourcepackages."""

__metaclass__ = type

__all__ = [
    'SourcePackageAssociationPortletView',
    'SourcePackageBreadcrumb',
    'SourcePackageChangeUpstreamView',
    'SourcePackageFacets',
    'SourcePackageHelpView',
    'SourcePackageNavigation',
    'SourcePackageRemoveUpstreamView',
    'SourcePackageUpstreamConnectionsView',
    'SourcePackageView',
    ]

from apt_pkg import ParseSrcDepends
from cgi import escape
from z3c.ptcompat import ViewPageTemplateFile
from zope.app.form.browser import DropdownWidget
from zope.app.form.interfaces import IInputWidget
from zope.component import getUtility, getMultiAdapter
from zope.formlib.form import Fields
from zope.interface import Interface
from zope.schema import Choice, TextLine
from zope.schema.vocabulary import (
    getVocabularyRegistry, SimpleVocabulary, SimpleTerm)

from lazr.restful.interface import copy_field

from canonical.widgets import LaunchpadRadioWidget

from canonical.launchpad import helpers
from canonical.launchpad.browser.multistep import MultiStepView, StepView
from lp.bugs.browser.bugtask import BugTargetTraversalMixin
from canonical.launchpad.browser.packagerelationship import (
    relationship_builder)
from lp.answers.browser.questiontarget import (
    QuestionTargetFacetMixin, QuestionTargetAnswersMenu)
from lp.services.worlddata.interfaces.country import ICountry
from lp.registry.interfaces.packaging import IPackaging, IPackagingUtil
from lp.registry.interfaces.pocket import PackagePublishingPocket
from lp.registry.interfaces.product import IProductSet
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.series import SeriesStatus
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.translations.interfaces.potemplate import IPOTemplateSet
from canonical.launchpad import _
from canonical.launchpad.webapp import (
    ApplicationMenu, GetitemNavigation, Link, redirection,
    StandardLaunchpadFacets, stepto)
from canonical.launchpad.webapp.launchpadform import (
    action, custom_widget, LaunchpadFormView, ReturnToReferrerMixin)
from canonical.launchpad.webapp import canonical_url
from canonical.launchpad.webapp.authorization import check_permission
from canonical.launchpad.webapp.breadcrumb import Breadcrumb
from canonical.launchpad.webapp.menu import structured
from canonical.launchpad.webapp.publisher import LaunchpadView

from canonical.lazr.utils import smartquote


class SourcePackageNavigation(GetitemNavigation, BugTargetTraversalMixin):

    usedfor = ISourcePackage

    @stepto('+pots')
    def pots(self):
        potemplateset = getUtility(IPOTemplateSet)
        sourcepackage_pots = potemplateset.getSubset(
            distroseries=self.context.distroseries,
            sourcepackagename=self.context.sourcepackagename)

        if not check_permission(
            'launchpad.TranslationsAdmin', sourcepackage_pots):
            self.context.distroseries.checkTranslationsViewable()

        return sourcepackage_pots

    @stepto('+filebug')
    def filebug(self):
        """Redirect to the IDistributionSourcePackage +filebug page."""
        sourcepackage = self.context
        distro_sourcepackage = sourcepackage.distribution.getSourcePackage(
            sourcepackage.name)

        redirection_url = canonical_url(
            distro_sourcepackage, view_name='+filebug')
        if self.request.form.get('no-redirect') is not None:
            redirection_url += '?no-redirect'
        return redirection(redirection_url)


class SourcePackageBreadcrumb(Breadcrumb):
    """Builds a breadcrumb for an `ISourcePackage`."""
    @property
    def text(self):
        return smartquote('"%s" source package') % (self.context.name)


class SourcePackageFacets(QuestionTargetFacetMixin, StandardLaunchpadFacets):

    usedfor = ISourcePackage
    enable_only = ['overview', 'bugs', 'branches', 'answers', 'translations']


class SourcePackageOverviewMenu(ApplicationMenu):

    usedfor = ISourcePackage
    facet = 'overview'
    links = [
        'distribution_source_package', 'edit_packaging', 'remove_packaging',
        'changelog', 'builds', 'set_upstream',
        ]

    def distribution_source_package(self):
        target = canonical_url(self.context.distribution_sourcepackage)
        text = 'All versions of %s source in %s' % (
            self.context.name, self.context.distribution.displayname)
        return Link(target, text, icon='package-source')

    def changelog(self):
        return Link('+changelog', 'View changelog', icon='list')

    def edit_packaging(self):
        return Link('+edit-packaging', 'Change upstream link', icon='edit')

    def remove_packaging(self):
        return Link(
            '+remove-packaging', 'Remove upstream link', icon='remove')

    def set_upstream(self):
        return Link("+edit-packaging", "Set upstream link", icon="add")

    def builds(self):
        text = 'Show builds'
        return Link('+builds', text, icon='info')


class SourcePackageAnswersMenu(QuestionTargetAnswersMenu):

    usedfor = ISourcePackage
    facet = 'answers'

    links = QuestionTargetAnswersMenu.links + ['gethelp']

    def gethelp(self):
        return Link('+gethelp', 'Help and support options', icon='info')


class SourcePackageChangeUpstreamStepOne(ReturnToReferrerMixin, StepView):
    """A view to set the `IProductSeries` of a sourcepackage."""
    schema = Interface
    _field_names = []

    step_name = 'sourcepackage_change_upstream_step1'
    template = ViewPageTemplateFile(
        '../templates/sourcepackage-edit-packaging.pt')
    label = 'Link to an upstream project'
    page_title = label
    step_description = 'Choose project'
    product = None

    def setUpFields(self):
        super(SourcePackageChangeUpstreamStepOne, self).setUpFields()
        series = self.context.productseries
        if series is not None:
            default = series.product
        else:
            default = None
        product_field = copy_field(
            IProductSeries['product'], default=default)
        self.form_fields += Fields(product_field)

    # Override ReturnToReferrerMixin.next_url.
    next_url = None

    def main_action(self, data):
        """See `MultiStepView`."""
        self.next_step = SourcePackageChangeUpstreamStepTwo
        self.request.form['product'] = data['product']


class SourcePackageChangeUpstreamStepTwo(ReturnToReferrerMixin, StepView):
    """A view to set the `IProductSeries` of a sourcepackage."""
    schema = IProductSeries
    _field_names = ['product']

    step_name = 'sourcepackage_change_upstream_step2'
    template = ViewPageTemplateFile(
        '../templates/sourcepackage-edit-packaging.pt')
    label = 'Link to an upstream project'
    page_title = label
    step_description = 'Choose project series'
    product = None

    # The DropdownWidget is used, since the VocabularyPickerWidget
    # does not support visible=False to turn it into a hidden input
    # to continue passing the variable in the form.
    custom_widget('product', DropdownWidget, visible=False)
    custom_widget('productseries', LaunchpadRadioWidget)

    def setUpFields(self):
        super(SourcePackageChangeUpstreamStepTwo, self).setUpFields()

        # The vocabulary for the product series is overridden to just
        # include active series from the product selected in the
        # previous step.
        product_name = self.request.form['field.product']
        self.product = getUtility(IProductSet)[product_name]
        series_list = [
            series for series in self.product.series
            if series.status != SeriesStatus.OBSOLETE
            ]

        # If the product is not being changed, then the current
        # productseries can be the default choice. Otherwise,
        # it will not exist in the vocabulary.
        if (self.context.productseries is not None
            and self.context.productseries.product == self.product):
            series_default = self.context.productseries
            # This only happens for obsolete series, since they aren't
            # added to the vocabulary normally.
            if series_default not in series_list:
                series_list.append(series_default)
        else:
            series_default = None

        # Put the development focus at the top of the list and create
        # the vocabulary.
        dev_focus = self.product.development_focus
        if dev_focus in series_list:
            series_list.remove(dev_focus)
        vocab_terms = [
            SimpleTerm(series, series.name, series.name)
            for series in series_list
            ]
        dev_focus_term = SimpleTerm(
            dev_focus, dev_focus.name, "%s (Recommended)" % dev_focus.name)
        vocab_terms.insert(0, dev_focus_term)

        productseries_choice = Choice(
            __name__='productseries',
            title=_("Series"),
            description=_("The series in this project."),
            vocabulary=SimpleVocabulary(vocab_terms),
            default=series_default,
            required=True)

        # The product selected in the previous step should be displayed,
        # but a widget can't be readonly and pass its value with the
        # form, so the real product field passes the value, and this fake
        # product field displays it.
        display_product_field = TextLine(
            __name__='fake_product',
            title=_("Project"),
            default=self.product.displayname,
            readonly=True)

        self.form_fields = (
            Fields(display_product_field, productseries_choice)
            + self.form_fields)

    # Override ReturnToReferrerMixin.next_url until the main_action()
    # is called.
    next_url = None

    main_action_label = u'Change'
    def main_action(self, data):
        productseries = data['productseries']
        # Because it is part of a multistep view, the next_url can't
        # be set until the action is called, or it will skip the step.
        self.next_url = self._return_url
        if self.context.productseries == productseries:
            # There is nothing to do.
            return
        self.context.setPackaging(productseries, self.user)
        self.request.response.addNotification('Upstream link updated.')


class SourcePackageChangeUpstreamView(MultiStepView):
    """A view to set the `IProductSeries` of a sourcepackage."""
    page_title = SourcePackageChangeUpstreamStepOne.page_title
    label = SourcePackageChangeUpstreamStepOne.label
    total_steps = 2
    first_step = SourcePackageChangeUpstreamStepOne


class SourcePackageRemoveUpstreamView(ReturnToReferrerMixin,
                                      LaunchpadFormView):
    """A view for removing the link to an upstream package."""

    schema = Interface
    field_names = []
    label = 'Unlink an upstream project'
    page_title = label

    @action('Unlink')
    def unlink(self, action, data):
        old_series = self.context.productseries
        getUtility(IPackagingUtil).deletePackaging(
            self.context.productseries,
            self.context.sourcepackagename,
            self.context.distroseries)
        self.request.response.addInfoNotification(
            'Removed upstream association between %s and %s.' % (
            old_series.title, self.context.distroseries.displayname))


class SourcePackageView:
    """A view for (distro series) source packages."""

    def initialize(self):
        # lets add a widget for the product series to which this package is
        # mapped in the Packaging table
        raw_field = IPackaging['productseries']
        bound_field = raw_field.bind(self.context)
        self.productseries_widget = getMultiAdapter(
            (bound_field, self.request), IInputWidget)
        self.productseries_widget.setRenderedValue(self.context.productseries)
        # List of languages the user is interested on based on their browser,
        # IP address and launchpad preferences.
        self.status_message = None
        self.error_message = None
        self.processForm()

    @property
    def label(self):
        return self.context.title

    @property
    def cancel_url(self):
        return canonical_url(self.context)

    def processForm(self):
        # look for an update to any of the things we track
        form = self.request.form
        if form.has_key('packaging'):
            if self.productseries_widget.hasValidInput():
                new_ps = self.productseries_widget.getInputValue()
                # we need to create or update the packaging
                self.context.setPackaging(new_ps, self.user)
                self.productseries_widget.setRenderedValue(new_ps)
                self.request.response.addInfoNotification(
                    'Upstream link updated, thank you!')
                self.request.response.redirect(canonical_url(self.context))
            else:
                self.error_message = structured('Invalid series given.')

    def published_by_pocket(self):
        """This morfs the results of ISourcePackage.published_by_pocket into
        something easier to parse from a page template. It becomes a list of
        dictionaries, sorted in dbschema item order, each representing a
        pocket and the packages in it."""
        result = []
        thedict = self.context.published_by_pocket
        for pocket in PackagePublishingPocket.items:
            newdict = {'pocketdetails': pocket}
            newdict['packages'] = thedict[pocket]
            result.append(newdict)
        return result

    def binaries(self):
        """Format binary packages into binarypackagename and archtags"""
        results = {}
        all_arch = sorted([arch.architecturetag for arch in
                           self.context.distroseries.architectures])
        for bin in self.context.currentrelease.binaries:
            distroarchseries = bin.build.distroarchseries
            if bin.name not in results:
                results[bin.name] = []

            if bin.architecturespecific:
                results[bin.name].append(distroarchseries.architecturetag)
            else:
                results[bin.name] = all_arch
            results[bin.name].sort()

        return results

    def _relationship_parser(self, content):
        """Wrap the relationship_builder for SourcePackages.

        Define apt_pkg.ParseSrcDep as a relationship 'parser' and
        IDistroSeries.getBinaryPackage as 'getter'.
        """
        getter = self.context.distroseries.getBinaryPackage
        parser = ParseSrcDepends
        return relationship_builder(content, parser=parser, getter=getter)

    @property
    def builddepends(self):
        return self._relationship_parser(
            self.context.currentrelease.builddepends)

    @property
    def builddependsindep(self):
        return self._relationship_parser(
            self.context.currentrelease.builddependsindep)

    @property
    def build_conflicts(self):
        return self._relationship_parser(
            self.context.currentrelease.build_conflicts)

    @property
    def build_conflicts_indep(self):
        return self._relationship_parser(
            self.context.currentrelease.build_conflicts_indep)

    def requestCountry(self):
        return ICountry(self.request, None)

    def browserLanguages(self):
        return helpers.browserLanguages(self.request)

    @property
    def potemplates(self):
        return list(self.context.getCurrentTranslationTemplates())


class SourcePackageHelpView:
    """A View to show Answers help."""

    page_title = 'Help and support options'


class SourcePackageAssociationPortletView(LaunchpadFormView):
    """A view for linking to an upstream package."""

    schema = Interface
    custom_widget(
        'upstream', LaunchpadRadioWidget, orientation='vertical')
    product_suggestions = None

    def setUpFields(self):
        """See `LaunchpadFormView`."""
        super(SourcePackageAssociationPortletView, self).setUpFields()
        self.request.annotations['show_edit_buttons'] = True
        # Find registered products that are similarly named to the source
        # package.
        product_vocab = getVocabularyRegistry().get(None, 'Product')
        matches = product_vocab.searchForTerms(self.context.name)
        # Based upon the matching products, create a new vocabulary with
        # term descriptions that include a link to the product.
        self.product_suggestions = []
        vocab_terms = []
        for item in matches:
            product = item.value
            self.product_suggestions.append(product)
            item_url = canonical_url(product)
            description = """<a href="%s">%s</a>""" % (
                item_url, escape(product.displayname))
            vocab_terms.append(SimpleTerm(product, product.name, description))
        upstream_vocabulary = SimpleVocabulary(vocab_terms)

        self.form_fields = Fields(
            Choice(__name__='upstream',
                   title=_('Registered upstream project'),
                   default=None,
                   vocabulary=upstream_vocabulary,
                   required=True))

    @action('Link to Upstream Project', name='link')
    def link(self, action, data):
        upstream = data.get('upstream')
        self.context.setPackaging(upstream.development_focus, self.user)
        self.request.response.addInfoNotification(
            'The project %s was linked to this source package.' %
            upstream.displayname)
        self.next_url = self.request.getURL()


class SourcePackageUpstreamConnectionsView(LaunchpadView):
    """A shared view with upstream connection info."""

    @property
    def has_bugtracker(self):
        """Does the product have a bugtracker set?"""
        if self.context.productseries is None:
            return False
        product = self.context.productseries.product
        if product.official_malone:
            return True
        bugtracker = product.bugtracker
        if bugtracker is None:
            if product.project is not None:
                bugtracker = product.project.bugtracker
        if bugtracker is None:
            return False
        return True
