# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Infrastructure for testing LaunchpadFormView subclasses."""

__metaclass__ = type

from canonical.launchpad.webapp.interaction import get_current_principal
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from zope.security.management import (
    endInteraction, newInteraction, queryInteraction, restoreInteraction)

class LaunchpadFormHarness:

    def __init__(self, context, view_class, form_values=None,
                 request_class=LaunchpadTestRequest):
        self.context = context
        self.view_class = view_class
        self.request_class = request_class
        self._render(form_values)

    def _render(self, form_values=None, method='GET'):
        self.request = self.request_class(
            method=method, form=form_values, PATH_INFO='/')
        if queryInteraction() is not None:
            self.request.setPrincipal(get_current_principal())
        # Setup a new interaction using self.request, create the view,
        # initialize() it and then restore the original interaction.
        endInteraction()
        newInteraction(self.request)
        self.view = self.view_class(self.context, self.request)
        self.view.initialize()
        restoreInteraction()

    def submit(self, action_name, form_values, method='POST'):
        action_name = '%s.actions.%s' % (self.view.prefix, action_name)
        form_values = dict(form_values)
        form_values[action_name] = ''
        self._render(form_values, method)

    def hasErrors(self):
        return bool(self.view.errors)

    def getFormErrors(self):
        return self.view.form_wide_errors

    def getFieldError(self, field_name):
        return self.view.getFieldError(field_name)

    def wasRedirected(self):
        return self.request.response.getStatus() in [302, 303]

    def redirectionTarget(self):
        return self.request.response.getHeader('location')
