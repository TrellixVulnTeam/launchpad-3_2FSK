# Copyright 2007 Canonical Ltd.  All rights reserved.

"""A simple display widget that renders like the tal expression fmt:link."""

__metaclass__ = type
__all__ = [
    'LinkWidget',
    ]

from zope.app.form.browser import DisplayWidget
from zope.app.traversing.interfaces import IPathAdapter
from zope.component import queryAdapter

class LinkWidget(DisplayWidget):
    """Renders using the tal formatter for fmt:link.

    Used by specifying `custom_widget('fieldname', LinkWidget)`.
    """

    def __init__(self, context, request, *ignored):
        """Ignores extra params such as vocabularies."""
        super(DisplayWidget, self).__init__(context, request)

    def __call__(self):
        adapter = queryAdapter(self._data, IPathAdapter, 'fmt')
        return adapter.link('')

    def hasInput(self):
        """The widget never has input."""
        return False
