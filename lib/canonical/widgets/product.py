# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Widgets related to IProduct."""

__metaclass__ = type
__all__ = [
    'GhostWidget',
    'LicenseWidget',
    'ProductBugTrackerWidget',
    'ProductNameWidget',
    ]

import cgi
import math

from zope.app.form import CustomWidgetFactory
from zope.app.form.browser.textwidgets import TextWidget
from zope.app.form.browser.widget import renderElement
from zope.app.form.interfaces import IInputWidget
from zope.app.form.utility import setUpWidget
from zope.component import getUtility
from zope.schema import Choice, Text

from z3c.ptcompat import ViewPageTemplateFile

from canonical.launchpad.browser.widgets import DescriptionWidget
from canonical.launchpad.fields import StrippedTextLine
from canonical.launchpad.interfaces import (
    BugTrackerType, IBugTracker, IBugTrackerSet, ILaunchBag)
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.validators.email import email_validator
from canonical.launchpad.vocabularies.dbobjects import (
    WebBugTrackerVocabulary)
from canonical.launchpad.webapp import canonical_url
from canonical.widgets.itemswidgets import (
    CheckBoxMatrixWidget, LaunchpadDropdownWidget, LaunchpadRadioWidget)
from canonical.widgets.textwidgets import (
    LowerCaseTextWidget, StrippedTextWidget)


class ProductBugTrackerWidget(LaunchpadRadioWidget):
    """Widget for selecting a product bug tracker."""

    _joinButtonToMessageTemplate = u'%s&nbsp;%s'

    def __init__(self, field, vocabulary, request):
        # pylint: disable-msg=W0233
        LaunchpadRadioWidget.__init__(self, field, vocabulary, request)

        # Bug tracker widget.
        self.bugtracker = Choice(
            vocabulary=WebBugTrackerVocabulary(),
            __name__='bugtracker')
        self.bugtracker_widget = CustomWidgetFactory(LaunchpadDropdownWidget)
        setUpWidget(
            self, 'bugtracker', self.bugtracker, IInputWidget,
            prefix=self.name, value=field.context.bugtracker,
            context=field.context)
        if self.bugtracker_widget.extra is None:
            self.bugtracker_widget.extra = ''
        ## Select the corresponding radio option automatically if
        ## the user selects a bug tracker.
        self.bugtracker_widget.extra += (
            ' onchange="selectWidget(\'%s.2\', event);"' % self.name)

        # Upstream email address field and widget.
        ## This is to make email address bug trackers appear
        ## separately from the main bug tracker list.
        self.upstream_email_address = StrippedTextLine(
            required=False, constraint=email_validator,
            __name__='upstream_email_address')
        self.upstream_email_address_widget = (
            CustomWidgetFactory(StrippedTextWidget))
        setUpWidget(
            self, 'upstream_email_address', self.upstream_email_address,
            IInputWidget, prefix=self.name, value='',
            context=self.upstream_email_address.context)
        ## Select the corresponding radio option automatically if
        ## the user starts typing.
        if self.upstream_email_address_widget.extra is None:
            self.upstream_email_address_widget.extra = ''
        self.upstream_email_address_widget.extra += (
            ' onkeypress="selectWidget(\'%s.3\', event);"' % self.name)

    def _renderItem(self, index, text, value, name, cssClass, checked=False):
        # This form has a custom need to render their labels separately,
        # because of a Firefox problem: see comment in renderItems.
        kw = {}
        if checked:
            kw['checked'] = 'checked'
        id = '%s.%s' % (name, index)
        elem = renderElement(u'input',
                             value=value,
                             name=name,
                             id=id,
                             cssClass=cssClass,
                             type='radio',
                             **kw)
        return '%s&nbsp;%s' % (elem, text)

    def _toFieldValue(self, form_value):
        if form_value == "malone":
            return self.context.malone_marker
        elif form_value == "external":
            return self.bugtracker_widget.getInputValue()
        elif form_value == "external-email":
            email_address = self.upstream_email_address_widget.getInputValue()
            if email_address is None or len(email_address) == 0:
                self.upstream_email_address_widget._error = (
                    LaunchpadValidationError(
                        'Please enter an email address.'))
                raise self.upstream_email_address_widget._error
            bugtracker = getUtility(IBugTrackerSet).ensureBugTracker(
                'mailto:%s' % email_address, getUtility(ILaunchBag).user,
                BugTrackerType.EMAILADDRESS)
            return bugtracker
        elif form_value == "project":
            return None

    def getInputValue(self):
        return self._toFieldValue(self._getFormInput())

    def setRenderedValue(self, value):
        self._data = value
        if value is not self.context.malone_marker:
            self.bugtracker_widget.setRenderedValue(value)

    def _renderLabel(self, text, index):
        """Render a label for the option with the specified index."""
        option_id = '%s.%s' % (self.name, index)
        return u'<label for="%s" style="font-weight: normal">%s</label>' % (
            option_id, text)

    def error(self):
        """Concatenate errors from this widget and sub-widgets."""
        # pylint: disable-msg=E1002
        errors = [super(ProductBugTrackerWidget, self).error(),
                  self.upstream_email_address_widget.error()]
        return '; '.join(err for err in errors if len(err) > 0)

    def renderItems(self, value):
        """Custom-render the radio-buttons and dependent widgets.

        Some of the radio options have dependent widgets: the bug
        tracker drop-down box, and the email address text field. To
        render these in the correct place we must override the default
        rendering of `LaunchpadRadioWidget`.

        We must also make sure that these dependent widgets are
        populated with the correct information, specifically the bug
        tracker selected, or the email address where bugs must be
        reported.
        """
        field = self.context
        product = field.context
        if value == self._missing:
            value = field.missing_value

        # Bugs tracked in Launchpad Bugs.
        malone_item_arguments = dict(
            index=0, text=self._renderLabel("In Launchpad", 0),
            value="malone", name=self.name, cssClass=self.cssClass)

        # Project or somewhere else.
        project = product.project
        if project is None or project.bugtracker is None:
            project_bugtracker_caption = "Somewhere else"
        else:
            project_bugtracker_caption = (
                'In the %s bug tracker (<a href="%s">%s</a>)</label>' % (
                    project.displayname, canonical_url(project.bugtracker),
                    cgi.escape(project.bugtracker.title)))
        project_bugtracker_arguments = dict(
            index=1, text=self._renderLabel(project_bugtracker_caption, 1),
            value="project", name=self.name, cssClass=self.cssClass)

        # External bug tracker.
        ## The bugtracker widget can't be within the <label> tag,
        ## since Firefox doesn't cope with it well.
        external_bugtracker_text = "%s %s" % (
            self._renderLabel("In a registered bug tracker:", 2),
            self.bugtracker_widget())
        external_bugtracker_arguments = dict(
            index=2, text=external_bugtracker_text,
            value="external", name=self.name, cssClass=self.cssClass)

        # Upstream email address (special-case bug tracker).
        if (IBugTracker.providedBy(value) and
            value.bugtrackertype == BugTrackerType.EMAILADDRESS):
            self.upstream_email_address_widget.setRenderedValue(
                value.baseurl.lstrip('mailto:'))
        external_bugtracker_email_text = "%s %s" % (
            self._renderLabel("By emailing an upstream bug contact:", 3),
            self.upstream_email_address_widget())
        external_bugtracker_email_arguments = dict(
            index=3, text=external_bugtracker_email_text,
            value="external-email", name=self.name, cssClass=self.cssClass)

        # All the choices arguments in order.
        all_arguments = [malone_item_arguments,
                         external_bugtracker_arguments,
                         external_bugtracker_email_arguments,
                         project_bugtracker_arguments]

        # Figure out the selected choice.
        if value == field.malone_marker:
            selected = malone_item_arguments
        elif value != self.context.missing_value:
            # value will be 'external-email' if there was an error on
            # upstream_email_address_widget.
            if (value == 'external-email' or (
                    IBugTracker.providedBy(value) and
                    value.bugtrackertype == BugTrackerType.EMAILADDRESS)):
                selected = external_bugtracker_email_arguments
            else:
                selected = external_bugtracker_arguments
        else:
            selected = project_bugtracker_arguments

        # Render.
        for arguments in all_arguments:
            if arguments is selected:
                render = self.renderSelectedItem
            else:
                render = self.renderItem
            yield render(**arguments)


class LicenseWidget(CheckBoxMatrixWidget):
    """A CheckBox widget with a custom template.

    The allow_pending_license is provided so that $product/+edit
    can display radio buttons to show that the license field is
    optional for pre-existing products that have never had a license set.
    """
    template = ViewPageTemplateFile('templates/license.pt')
    allow_pending_license = False

    CATEGORIES = {
        'AFFERO'        : 'recommended',
        'APACHE'        : 'recommended',
        'BSD'           : 'recommended',
        'GNU_GPL_V2'    : 'recommended',
        'GNU_GPL_V3'    : 'recommended',
        'GNU_LGPL_V2_1' : 'recommended',
        'GNU_LGPL_V3'   : 'recommended',
        'MIT'           : 'recommended',
        'CC_0'          : 'recommended',
        'ACADEMIC'      : 'more',
        'ARTISTIC'      : 'more',
        'ARTISTIC_2_0'  : 'more',
        'COMMON_PUBLIC' : 'more',
        'ECLIPSE'       : 'more',
        'EDUCATIONAL_COMMUNITY': 'more',
        'MPL'           : 'more',
        'OPEN_SOFTWARE' : 'more',
        'PHP'           : 'more',
        'PUBLIC_DOMAIN' : 'more',
        'PYTHON'        : 'more',
        'ZPL'           : 'more',
        'CC_BY'         : 'more',
        'CC_BY_SA'      : 'more',
        'PERL'          : 'deprecated',
        'OTHER_PROPRIETARY' : 'special',
        'OTHER_OPEN_SOURCE' : 'special',
        'DONT_KNOW'     : 'special',
        }

    items_by_category = None

    def __init__(self, field, vocabulary, request):
        # pylint: disable-msg=E1002
        super(LicenseWidget, self).__init__(field, vocabulary, request)
        # We want to put the license_info widget inside the licenses widget's
        # HTML, for better alignment and JavaScript dynamism.  This is
        # accomplished by ghosting the form's license_info widget (see
        # lp/registry/browser/product.py and the GhostWidget implementation
        # below) and creating a custom widget here.  It's a pretty simple text
        # widget so create that now.  The fun part is that it's all within the
        # same form, so posts work correctly.
        self.license_info = Text(__name__='license_info')
        self.license_info_widget = CustomWidgetFactory(DescriptionWidget)
        # The initial value of the license_info widget will be taken from the
        # field's context when available.  This will be the IProduct when
        # we're editing an existing project, but when we're creating a new
        # one, it'll be an IProductSet, which does not have license_info.
        initial_value = getattr(field.context, 'license_info', None)
        setUpWidget(
            self, 'license_info', self.license_info, IInputWidget,
            prefix='field', value=initial_value,
            context=field.context)
        # These will get filled in by _categorize().  They are the number of
        # selected licenses in the category.  The actual count doesn't matter,
        # since if it's greater than 0 it will start opened.  NOte that we
        # always want the recommended licenses to be opened, so we initialize
        # its value to 1.
        self.recommended_count = 1
        self.more_count = 0
        self.deprecated_count = 0
        self.special_count = 0

    def textForValue(self, term):
        """See `ItemsWidgetBase`."""
        # This will return just the DBItem's text.  We want to wrap that text
        # in the URL to the license, which is stored in the DBItem's
        # description.
        # pylint: disable-msg=E1002
        value = super(LicenseWidget, self).textForValue(term)
        if term.value.url is None:
            return value
        else:
            return ('%s&nbsp;<a href="%s" class="sprite external-link">'
                    '<span class="invisible-link">view license</span></a>'
                    % (value, term.value.url))

    def renderItem(self, index, text, value, name, cssClass):
        """See `ItemsEditWidgetBase`."""
        # pylint: disable-msg=E1002
        rendered = super(LicenseWidget, self).renderItem(
            index, text, value, name, cssClass)
        self._categorize(value, rendered)
        return rendered

    def renderSelectedItem(self, index, text, value, name, cssClass):
        """See `ItemsEditWidgetBase`."""
        # pylint: disable-msg=E1002
        rendered = super(LicenseWidget, self).renderSelectedItem(
            index, text, value, name, cssClass)
        category = self._categorize(value, rendered)
        # Increment the category counter.  This is used by the template to
        # determine whether a category should start opened or not.
        attribute_name = category + '_count'
        setattr(self, attribute_name, getattr(self, attribute_name) + 1)
        return rendered

    def _categorize(self, value, rendered):
        # Place the value in the proper category.
        if self.items_by_category is None:
            self.items_by_category = {}
        # When allow_pending_license is set, we'll see a radio button labeled
        # "I haven't specified the license yet".  In that case, do not show
        # the "I don't know" option.
        if self.allow_pending_license and value == 'DONT_KNOW':
            return
        category = self.CATEGORIES.get(value)
        assert category is not None, 'Uncategorized value: %s' % value
        self.items_by_category.setdefault(category, []).append(rendered)
        return category

    def __call__(self):
        # Trigger textForValue() which does the categorization of the
        # individual checkbox items.  We don't actually care about the return
        # value though since we'll be building up our checkbox tables
        # manually.
        # pylint: disable-msg=E1002
        super(LicenseWidget, self).__call__()
        self.recommended = self._renderTable('recommended', 3)
        self.more = self._renderTable('more', 3)
        self.deprecated = self._renderTable('deprecated')
        self.special = self._renderTable('special')
        return self.template()

    def _renderTable(self, category, column_count=1):
        # The tables are wrapped in divs, since IE8 does not respond
        # to setting the table's height to zero.
        html = ['<div id="%s"><table>' % category]
        rendered_items = self.items_by_category[category]
        row_count = int(math.ceil(len(rendered_items) / float(column_count)))
        for i in range(0, row_count):
            html.append('<tr>')
            for j in range(0, column_count):
                index = i + (j * row_count)
                if index >= len(rendered_items):
                    break
                html.append('<td>%s</td>' % rendered_items[index])
            html.append('</tr>')
        html.append('</table></div>')
        return '\n'.join(html)


class ProductNameWidget(LowerCaseTextWidget):
    """A text input widget that looks like a url path component entry.

    URL: http://launchpad.net/[____________]
    """
    template = ViewPageTemplateFile('templates/project-url.pt')

    def __init__(self, *args):
        # pylint: disable-msg=E1002
        self.read_only = False
        super(ProductNameWidget, self).__init__(*args)

    def __call__(self):
        return self.template()

    @property
    def product_name(self):
        return self.request.form.get('field.name', '').lower()

    @property
    def widget_type(self):
        if self.read_only:
            return 'hidden'
        else:
            return 'text'


class GhostWidget(TextWidget):
    """A simple widget that has no HTML."""

    # This suppresses the stuff above the widget.
    display_label = False
    # This suppresses the stuff underneath the widget.
    hint = ''

    # This suppresses all of the widget's HTML.
    def __call__(self):
        """See `SimpleInputWidget`."""
        return ''
