# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Infrastructure for testing LaunchpadFormView subclasses."""

__metaclass__ = type

from zope.formlib import form
from canonical.launchpad.webapp import LaunchpadFormView
from canonical.launchpad.webapp.servers import LaunchpadTestRequest


class LaunchpadFormHarness:

    def __init__(self, context, view_class, form_values=None):
        self.context = context
        self.view_class = view_class
        self._render(form_values)

    def _render(self, form_values=None):
        self.request = LaunchpadTestRequest(form=form_values)
        self.view = self.view_class(self.context, self.request)
        self.view.initialize()

    def submit(self, action_name, form_values):
        action_name = '%s.actions.%s' % (self.view.prefix, action_name)
        form_values = dict(form_values)
        form_values[action_name] = ''
        self._render(form_values)

    def hasErrors(self):
        return bool(self.view.errors)

    def getFormErrors(self):
        return self.view.form_wide_errors

    def getWidgetError(self, field_name):
        return self.view.widgets[field_name].error()

    def wasRedirected(self):
        return self.request.response.getStatus() in [302, 303]

    def redirectionTarget(self):
        return self.request.response.getHeader('location')
