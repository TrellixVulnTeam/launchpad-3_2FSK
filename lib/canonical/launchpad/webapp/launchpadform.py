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

from canonical.launchpad.webapp.publisher import LaunchpadView
from canonical.launchpad.webapp.snapshot import Snapshot
from canonical.launchpad.event import SQLObjectModifiedEvent


class LaunchpadFormView(LaunchpadView):

    # the prefix used for all form inputs.
    prefix = 'field'

    # the form schema
    schema = None
    # subset of fields to use
    field_names = None
    # dictionary mapping field names to custom widgets
    custom_widgets = ()

    # the next URL to redirect to on successful form submission
    next_url = None

    label = ''

    actions = ()

    render_context = False

    def __init__(self, context, request):
        LaunchpadView.__init__(self, context, request)
        self.errors = []
        self.top_of_page_errors = []

    def initialize(self):
        self.setUpFields()
        self.setUpWidgets()

        data = {}
        errors, action = form.handleSubmit(self.actions, data, self._validate)

        if errors:
            action.failure(data, errors)
            self._abort()
        elif errors is not None:
            action.success(data)
            if self.next_url:
                self.request.response.redirect(self.next_url)

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
        # XXX: 20060802 jamesh
        # expose omit_readonly=True ??
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
        self.top_of_page_errors.append(message)
        self.errors.append(message)

    def setFieldError(self, field_name, message):
        """Set the error associated with a particular field

        If the validator for the field also flagged an error, the
        message passed to this method will be used in preference.
        """
        # XXX: 20060803 jamesh
        # todo
        raise NotImplementedError

    def _validate(self, action, data):
        for error in form.getWidgetsData(self.widgets, self.prefix, data):
            self.errors.append(error)
        for error in form.checkInvariants(self.form_fields, data):
            self.addError(error)

        # perform custom validation
        self.validate(data)
        return self.errors

    @property
    def error_count(self):
        # this should use ngettext if we ever translate Launchpad's UI
        if len(self.errors) == 0:
            return ''
        elif len(self.errors) == 1:
            return 'There is 1 error'
        else:
            return 'There are %d errors' % len(self.errors)

    def validate(self, data):
        """Validate the form.

        For each error encountered, the addError() method should be
        called to log the problem.
        """
        pass


class LaunchpadEditFormView(LaunchpadFormView):

    render_context = False

    def update_context_from_data(self, data):
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
