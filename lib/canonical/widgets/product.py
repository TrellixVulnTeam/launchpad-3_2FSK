# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Widgets related to IProduct."""

__metaclass__ = type


import cgi

from zope.app.form import CustomWidgetFactory
from zope.app.form.interfaces import IInputWidget
from zope.app.form.utility import setUpWidget

from canonical.launchpad.webapp import canonical_url
from canonical.widgets.itemswidgets import (
    LaunchpadDropdownWidget, LaunchpadRadioWidget)


class ProductBugTrackerWidget(LaunchpadRadioWidget):
    """Widget for selecting a product bug tracker."""

    _joinButtonToMessageTemplate = u'%s&nbsp;%s'

    def __init__(self, field, vocabulary, request):
        LaunchpadRadioWidget.__init__(self, field, vocabulary, request)
        self.bugtracker_widget = CustomWidgetFactory(
            LaunchpadDropdownWidget)
        setUpWidget(
            self, 'bugtracker', field, IInputWidget,
            prefix=self.name, value=field.context.bugtracker,
            context=field.context)
        if self.bugtracker_widget.extra is None:
            self.bugtracker_widget.extra = ''
        # Select the "External bug tracker" option automatically if the
        # user selects a bug tracker.
        self.bugtracker_widget.extra += (
            ' onchange="selectWidget(\'%s.2\', event);"' % self.name)


    def _toFieldValue(self, form_value):
        if form_value == "malone":
            return self.context.malone_marker
        elif form_value == "external":
            return self.bugtracker_widget.getInputValue()
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

    def renderItems(self, value):
        field = self.context
        product = field.context
        if value == self._missing:
            value = field.missing_value

        items = []
        malone_item_arguments = dict(
            index=0, text=self._renderLabel("Bugs are tracked in Launchpad", 0),
            value="malone", name=self.name, cssClass=self.cssClass)
        project = product.project
        if project is None or project.bugtracker is None:
            project_bugtracker_caption = "No bug tracker"
        else:
            project_bugtracker_caption = (
                'The <a href="%s">project</a> bug tracker:'
                ' <a href="%s">%s</a></label>' % (
                    canonical_url(project),
                    canonical_url(project.bugtracker),
                    cgi.escape(project.bugtracker.title)))
        project_bugtracker_arguments = dict(
            index=1, text=self._renderLabel(project_bugtracker_caption, 1),
            value="project", name=self.name, cssClass=self.cssClass)
        # The bugtracker widget can't be within the <label> tag, since
        # Firefox doesn't cope with it well.
        external_bugtracker_text = "%s %s" % (
            self._renderLabel("External bug tracker", 2),
            self.bugtracker_widget())
        external_bugtracker_arguments = dict(
            index=2, text=external_bugtracker_text,
            value="external", name=self.name, cssClass=self.cssClass)
        if value == field.malone_marker:
            items.append(self.renderSelectedItem(**malone_item_arguments))
            items.append(self.renderItem(**project_bugtracker_arguments))
            items.append(self.renderItem(**external_bugtracker_arguments))
        elif value != self.context.missing_value:
            items.append(self.renderItem(**malone_item_arguments))
            items.append(self.renderItem(**project_bugtracker_arguments))
            items.append(
                self.renderSelectedItem(**external_bugtracker_arguments))
        else:
            items.append(self.renderItem(**malone_item_arguments))
            items.append(
                self.renderSelectedItem(**project_bugtracker_arguments))
            items.append(self.renderItem(**external_bugtracker_arguments))

        return items
