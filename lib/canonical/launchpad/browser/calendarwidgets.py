# Copyright 2005 Canonical Ltd

__metaclass__ = type

__all__ = [
    'LocalDateTimeWidget',
    'LocalDateTimeDisplayWidget',
    'TimeDurationWidget',
    'TimeDurationDisplayWidget',
    ]

import re
from datetime import datetime, timedelta

from zope.interface import implements

from zope.component import getUtility
from zope.schema.interfaces import IText
from zope.app.form import InputWidget
from zope.app.form.browser import TextAreaWidget, TextWidget
from zope.app.form.browser.widget import (
    DisplayWidget, SimpleInputWidget, renderElement)
from zope.app.form.interfaces import ConversionError, InputErrors

from canonical.launchpad import _
from canonical.launchpad.interfaces import ILaunchBag

_date_re = re.compile(
    r'^(\d\d\d\d)-(\d\d?)-(\d\d?)\ +(\d\d?):(\d\d)(?::(\d\d))?$')
class LocalDateTimeWidget(TextWidget):

    implements(IText)
    width = 20

    def _toFieldValue(self, input):
        input = input.strip()
        if input == self._missing:
            return self.context.missing_value

        match = _date_re.match(input)
        if not match:
            raise ConversionError('Could not parse date (expected '
                                  'format "YYYY-mm-dd HH:MM[:SS])')
        year = int(match.group(1))
        month = int(match.group(2))
        day = int(match.group(3))
        hour = int(match.group(4))
        minute = int(match.group(5))
        second = match.group(6)
        if second:
            second = int(second)
        else:
            second = 0

        user_timezone = getUtility(ILaunchBag).timezone
        try:
            val = datetime(year, month, day, hour, minute, second,
                            tzinfo=user_timezone)
            return val
        except ValueError, e:
            raise ConversionError(str(e))

    def _toFormValue(self, value):
        if value == self.context.missing_value:
            return self._missing
        else:
            user_timezone = getUtility(ILaunchBag).timezone
            value = value.astimezone(user_timezone)
            return value.strftime('%Y-%m-%d %H:%M:%S')

class LocalDateTimeDisplayWidget(DisplayWidget):

    def __call__(self):
        if self._renderedValueSet():
            value = self._data
        else:
            value = self.context.default

        if value is None:
            return ""

        user_timezone = getUtility(ILaunchBag).timezone
        value = value.astimezone(user_timezone)
        return value.strftime('%Y-%m-%d %H:%M:%S %Z')

class TimeDurationWidget(SimpleInputWidget):
    """A widget for entering a time duration."""

    _missing = (u'', 'h')

    def _getFormInput(self):
        return [self.request.get(self.name),
                self.request.get('%s.unit' % self.name)]

    def _toFieldValue(self, input):
        if input[0] == self._missing[0]:
            return self.context.missing_value
        value, unit = input
        try:
            value = float(value)
        except ValueError, e:
            raise ConversionError(str(e))
        if unit == 'm':
            return timedelta(minutes=value)
        elif unit == 'h':
            return timedelta(hours=value)
        elif unit == 'd':
            return timedelta(days=value)
        elif unit == 'w':
            return timedelta(weeks=value)
        else:
            raise ConversionError('unknown time unit %r' % unit)

    def _toFormValue(self, value):
        if value == self.context.missing_value:
            return self._missing
        else:
            # pick an appropriate unit
            if value.seconds % 3600 != 0:
                return (unicode(value.seconds / 60.0), 'm')
            elif value.seconds % 86400 != 0:
                return (unicode(value.seconds / 3600.0), 'h')
            elif value.seconds % 604800 != 0:
                return (unicode(value.seconds / 86400.0), 'd')
            else:
                return (unicode(value.seconds / 604800.0), 'w')

    def _getFormValue(self):
        """Returns a value suitable for use in an HTML form."""
        # I'm replicating this function so that the "except InputErrors"
        # case returns the form value as _getFormInput() does.
        #   -- James Henstridge (2005-01-17)
        if not self._renderedValueSet():
            if self.hasInput():
                try:
                    value = self.getInputValue()
                except InputErrors:
                    if self.request.form.has_key(self.name):
                        return self._getFormInput()
                    else:
                        return self._missing
            else:
                value = self._getDefault()
        else:
            value = self._data
        return self._toFormValue(value)

    def __call__(self):
        count_val, unit_val = self._getFormValue()
        render = []
        render.append(renderElement('input',
                                    type='text',
                                    name=self.name,
                                    id=self.name,
                                    value=count_val,
                                    cssClass=self.cssClass,
                                    extra=self.extra))
        render.append(u'\n')
        render.append(u'<select name="%s.unit">\n' % self.name)
        for (unit, label) in [ ('m', _('minutes')),
                               ('h', _('hours')),
                               ('d', _('days')),
                               ('w', _('weeks')) ]:
            if unit == unit_val:
                render.append(
                    u'<option selected="selected" value="%s">%s</option>\n'
                    % (unit, label))
            else:
                render.append(u'<option value="%s">%s</option>\n'
                              % (unit, label))
        render.append(u'</select>\n')
        return ''.join(render)

    def hidden(self):
        count_val, unit_val = self._getFormValue()
        render = []
        render.append(renderElement('input',
                                    type='hidden',
                                    name=self.name,
                                    id=self.name,
                                    value=count_val,
                                    cssClass=self.cssClass,
                                    extra=self.extra))
        render.append(renderElement('input',
                                    type='hidden',
                                    name='%s.unit' % self.name,
                                    id='%s.unit' % self.name,
                                    value=unit_val,
                                    cssClass=self.cssClass,
                                    extra=self.extra))
        return ''.join(render)

class TimeDurationDisplayWidget(DisplayWidget):

    def __call__(self):
        if self._renderedValueSet():
            value = self._data
        else:
            value = self.context.default

        if value is None:
            return ""

        # pick an appropriate unit
        if value.seconds % 3600 != 0:
            return '%g minutes' % (value.seconds / 60.0)
        elif value.seconds % 86400 != 0:
            return '%g hours' % (value.seconds / 3600.0)
        elif value.seconds % 604800 != 0:
            return '%g days' % (value.seconds / 86400.0)
        else:
            return '%g weeks' % (value.seconds / 604800.0)
