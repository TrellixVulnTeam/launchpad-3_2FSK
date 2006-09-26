# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Launchpad Form View Classes
"""

__metaclass__ = type

__all__ = [
    'LaunchpadFormView',
    'LaunchpadEditFormView',
    'action',
    'custom_widget',
    ]

import transaction
from zope.interface import providedBy
from zope.interface.advice import addClassAdvisor
from zope.event import notify
from zope.formlib import form
from zope.formlib.form import action
from zope.app.form import CustomWidgetFactory
from zope.app.form.interfaces import IInputWidget

from canonical.launchpad.webapp.publisher import LaunchpadView
from canonical.launchpad.webapp.snapshot import Snapshot
from canonical.launchpad.event import SQLObjectModifiedEvent

# marker to represent "focus the first widget in the form"
_first_widget_marker = object()


class LaunchpadFormView(LaunchpadView):

    # The prefix used for all form inputs.
    prefix = 'field'

    # The form schema
    schema = None
    # Subset of fields to use
    field_names = None
    # Dictionary mapping field names to custom widgets
    custom_widgets = ()

    # The next URL to redirect to on successful form submission
    next_url = None

    # The name of the widget that will receive initial focus in the form.
    # By default, the first widget will receive focus.  Set this to None
    # to disable setting of initial focus.
    initial_focus_widget = _first_widget_marker

    label = ''

    actions = ()

    render_context = False

    form_result = None

    def __init__(self, context, request):
        LaunchpadView.__init__(self, context, request)
        self.errors = []
        self.form_wide_errors = []
        self.widget_errors = {}

    def initialize(self):
        self.setUpFields()
        self.setUpWidgets()

        data = {}
        errors, action = form.handleSubmit(self.actions, data, self._validate)

        # no action selected, so return
        if action is None:
            return

        if errors:
            self.form_result = action.failure(data, errors)
            self._abort()
        else:
            self.form_result = action.success(data)
            if self.next_url:
                self.request.response.redirect(self.next_url)

    def render(self):
        """Return the body of the response.

        By default, this method will execute the template attribute to
        render the content. But if an action handler was executed and
        it returned a value other than None, that value will be used as
        the rendered content.

        See LaunchpadView.render() for other information.
        """
        if self.form_result is not None:
            return self.form_result
        else:
            return self.template()

    def _abort(self):
        """Abort the form edit.

        This will be called in the case of a validation error.
        """
        # XXX: 20060802 jamesh
        # This should really be dooming the transaction rather than
        # aborting.  What we really want is to prevent more work being
        # done and then committed.
        transaction.abort()

    def setUpFields(self):
        assert self.schema is not None, "Schema must be set for LaunchpadFormView"
        self.form_fields = form.Fields(self.schema,
                                       render_context=self.render_context)
        if self.field_names is not None:
            self.form_fields = self.form_fields.select(*self.field_names)

        for field in self.form_fields:
            if field.__name__ in self.custom_widgets:
                field.custom_widget = self.custom_widgets[field.__name__]

    def setUpWidgets(self):
        # XXX: 20060802 jamesh
        # do we want to do anything with ignore_request?
        self.widgets = form.setUpWidgets(
            self.form_fields, self.prefix, self.context, self.request,
            data=self.initial_values, ignore_request=False)

    @property
    def initial_values(self):
        """Override this in your subclass if you want any widgets to have
        initial values.
        """
        return {}

    def addError(self, message):
        """Add a form wide error"""
        self.form_wide_errors.append(message)
        self.errors.append(message)

    def setFieldError(self, field_name, message):
        """Set the error associated with a particular field

        If the validator for the field also flagged an error, the
        message passed to this method will be used in preference.
        """
        self.widget_errors[field_name] = message
        self.errors.append(message)

    def _validate(self, action, data):
        # XXXX 2006-09-26 jamesh

        # If a form field is disabled, then no data will be sent back.
        # getWidgetsData() raises an exception when this occurs, even
        # if the field is not marked as required.
        #
        # To work around this, we pass a subset of widgets to
        # getWidgetsData().
        widgets = []
        for input, widget in self.widgets.__iter_input_and_widget__():
            if (input and IInputWidget.providedBy(widget) and
                not widget.hasInput()):
                if widget.context.required:
                    self.setFieldError(widget.context.__name__,
                                       'Required field is missing')
            else:
                widgets.append((input, widget))
        widgets = form.Widgets(widgets, len(self.prefix)+1)
        for error in form.getWidgetsData(widgets, self.prefix, data):
            self.errors.append(error)
        for error in form.checkInvariants(self.form_fields, data):
            self.addError(error)

        # perform custom validation
        self.validate(data)
        return self.errors

    @property
    def error_count(self):
        # this should use ngettext if we ever translate Launchpad's UI
        count = len(self.form_wide_errors)
        for field in self.form_fields:
            if field.__name__ in self.widget_errors:
                count += 1
            else:
                widget = self.widgets.get(field.__name__)
                if widget and widget.error():
                    count +=1

        if count == 0:
            return ''
        elif count == 1:
            return 'There is 1 error.'
        else:
            return 'There are %d errors.' % count

    def getWidgetError(self, field_name):
        """Get the error associated with a particular widget.

        If an error message is available in widget_errors, it is
        returned.  As a fallback, the corresponding widget's error()
        method is called.
        """
        if field_name in self.widget_errors:
            return self.widget_errors[field_name]
        else:
            return self.widgets[field_name].error()

    def validate(self, data):
        """Validate the form.

        For each error encountered, the addError() method should be
        called to log the problem.
        """
        pass

    def focusedElementScript(self):
        """Helper function to construct the script element content."""
        # Work out which widget needs to be focused.  First we check
        # for the first widget with an error set:
        first_widget = None
        for widget in self.widgets:
            if first_widget is None:
                first_widget = widget
            if self.getWidgetError(widget.context.__name__):
                break
        else:
            # otherwise we use the widget named by self.initial_focus_widget
            if self.initial_focus_widget is _first_widget_marker:
                widget = first_widget
            elif self.initial_focus_widget is not None:
                widget = self.widgets[self.initial_focus_widget]
            else:
                widget = None

        if widget is None:
            return ''
        else:
            return ("<!--\n"
                    "setFocusByName('%s');\n"
                    "// -->" % widget.name)


class LaunchpadEditFormView(LaunchpadFormView):

    render_context = True

    def updateContextFromData(self, data):
        """Update the context object based on form data.

        If any changes were made, SQLObjectModifiedEvent will be
        emitted.

        This method should be called by an action method of the form.
        """
        context_before_modification = Snapshot(
            self.context, providing=providedBy(self.context))
        if form.applyChanges(self.context, self.form_fields, data):
            field_names = [form_field.__name__
                           for form_field in self.form_fields]
            notify(SQLObjectModifiedEvent(self.context,
                                          context_before_modification,
                                          field_names))


class custom_widget:
    """A class advisor for overriding the default widget for a field."""

    def __init__(self, field_name, widget, **kwargs):
        self.field_name = field_name
        if widget is None:
            self.widget = None
        else:
            self.widget = CustomWidgetFactory(widget, **kwargs)
        addClassAdvisor(self.advise)

    def advise(self, cls):
        if cls.custom_widgets is None:
            cls.custom_widgets = {}
        else:
            cls.custom_widgets = dict(cls.custom_widgets)
        cls.custom_widgets[self.field_name] = self.widget
        return cls


# XXX: 20060809 jamesh
# this is an evil hack to allow us to share the widget macros between
# the new and old form base classes.
def getWidgetError(view, widget):
    if hasattr(view, 'getWidgetError'):
        return view.getWidgetError(widget.context.__name__)
    else:
        return widget.error()
