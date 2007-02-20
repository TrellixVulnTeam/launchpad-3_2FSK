# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Widgets related to IProject."""

__metaclass__ = type

from textwrap import dedent

from zope.app.form import InputWidget
from zope.app.form.browser.widget import BrowserWidget, renderElement
from zope.app.form.interfaces import (
    ConversionError, IInputWidget, InputErrors, MissingInputError)
from zope.app.form.utility import setUpWidget
from zope.interface import implements
from zope.schema import Choice

from canonical.launchpad.interfaces import UnexpectedFormData
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.webapp.interfaces import IAlwaysSubmittedWidget


class ProjectScopeWidget(BrowserWidget, InputWidget):
    """Widget for selecting a scope. Either 'All projects' or only one."""

    implements(IAlwaysSubmittedWidget, IInputWidget)

    default_option = "all"

    def __init__(self, field, request):
        super(ProjectScopeWidget, self).__init__(field, request)

        # We copy the title, description and vocabulary from the main
        # field since it determines the valid target types.
        target_field = Choice(
            __name__='target', title=field.title,
            description=field.description, vocabulary=field.vocabularyName,
            required=True)
        setUpWidget(
            self, target_field.__name__, target_field, IInputWidget,
            prefix=self.name)

    def setUpOptions(self):
        """Set up options to be rendered."""
        self.options = {}
        for option in ['all', 'project']:
            attributes = dict(
                type='radio', name=self.name, value=option,
                id='%s.option.%s' % (self.name, option))
            if self.request.form.get(self.name, self.default_option) == option:
                attributes['checked'] = 'checked'
            if option == 'project':
                attributes['onclick'] = (
                    "document.getElementById('field.scope.target').focus();")
            self.options[option] = renderElement('input', **attributes)
        self.target_widget.onKeyPress = (
            "selectWidget('%s.option.project', event)" % self.name)

    def hasInput(self):
        """See zope.app.form.interfaces.IInputWidget."""
        return self.name in self.request.form

    def hasValidInput(self):
        """See zope.app.form.interfaces.IInputWidget."""
        try:
            self.getInputValue()
            return True
        except (InputErrors, UnexpectedFormData, LaunchpadValidationError):
            return False

    def getInputValue(self):
        """See zope.app.form.interfaces.IInputWidget."""
        scope = self.request.form.get(self.name)
        if scope == 'all':
            return None
        elif scope == 'project':
            try:
                return self.target_widget.getInputValue()
            except MissingInputError:
                raise LaunchpadValidationError('Please enter a project name')
            except ConversionError:
                entered_name = self.request.form.get("%s.target" % self.name)
                raise LaunchpadValidationError(
                    "There is no project named '%s' registered in"
                    " Launchpad", entered_name)
        else:
            raise UnexpectedFormData("No valid option was selected.")

    def setRenderedValue(self, value):
        """See IWidget."""
        if value is None:
            self.default_option = 'all'
            self.target_widget.setRenderedValue(None)
        else:
            self.default_option = 'project'
            self.target_widget.setRenderedValue(value)

    def __call__(self):
        """See zope.app.form.interfaces.IBrowserWidget."""
        self.setUpOptions()
        return "\n".join([
            self.renderScopeOptions(),
            self.target_widget()])

    def renderScopeOptions(self):
        """Render the HTML for the scope radio widgets."""
        return dedent('''\
        <label>
          %(all)s All projects
        </label>
        <label>
          %(project)s One project:
        </label>
        ''' % self.options)
