# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

__metaclass__ = type

from zope.app.form.browser.textwidgets import IntWidget, TextWidget
from zope.app.form.interfaces import ConversionError, WidgetInputError
from zope.component import getUtility
from zope.schema.interfaces import ConstraintNotSatisfied

from canonical.launchpad.interfaces import IBugSet, NotFoundError
from canonical.launchpad.validators import LaunchpadValidationError


class BugWidget(IntWidget):
    """A widget for displaying a field that is bound to an IBug."""
    def _toFormValue(self, value):
        """See zope.app.form.widget.SimpleInputWidget."""
        if value == self.context.missing_value:
            return self._missing
        else:
            return value.id

    def _toFieldValue(self, input):
        """See zope.app.form.widget.SimpleInputWidget."""
        if input == self._missing:
            return self.context.missing_value
        else:
            try:
                return getUtility(IBugSet).getByNameOrID(input)
            except (NotFoundError, ValueError):
                raise ConversionError("Not a valid bug number or nickname.")


class BugTagsWidget(TextWidget):
    """A widget for editing bug tags."""

    def __init__(self, field, value_type, request):
        # We don't use value_type.
        TextWidget.__init__(self, field, request)

    def _toFormValue(self, value):
        """Convert the list of strings to a single, space separated, string."""
        if value:
            return u' '.join(value)
        else:
            return self._missing

    def _toFieldValue(self, input):
        """Convert a space separated string to a list of strings."""
        input = input.strip()
        if input == self._missing:
            return []
        else:
            return sorted(tag.lower() for tag in input.split())

    def getInputValue(self):
        try:
            return TextWidget.getInputValue(self)
        except WidgetInputError, input_error:
            # The standard error message isn't useful at all. We look to
            # see if it's a ConstraintNotSatisfied error and change it
            # to a better one. For simplicity, we care only about the
            # first error.
            validation_errors = input_error.args[2]
            for validatation_error in validation_errors.args[0]:
                if isinstance(validatation_error, ConstraintNotSatisfied):
                    self._error = WidgetInputError(
                        input_error.args[0], input_error.args[1],
                        LaunchpadValidationError(
                            "'%s' isn't a valid tag name",
                            validatation_error.args[0]))
                raise self._error
            else:
                raise
