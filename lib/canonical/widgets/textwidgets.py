# Copyright 2004-2006 Canonical Ltd.  All rights reserved.

import datetime
import pytz
import re

from zope.datetime import parse, DateTimeError
from zope.app.form.browser.textwidgets import TextAreaWidget, TextWidget
from zope.app.form.interfaces import ConversionError

from canonical.launchpad.interfaces import UnexpectedFormData
from canonical.launchpad.webapp.uri import URI, InvalidURIError

# XXX matsubara 2006-05-10: Should I move our NewLineToSpacesWidget to
# this module?


class StrippedTextWidget(TextWidget):
    """A widget that strips leading and trailing whitespaces."""

    def _toFieldValue(self, input):
        return TextWidget._toFieldValue(self, input.strip())


class LowerCaseTextWidget(StrippedTextWidget):
    """A widget that converts text to lower case."""

    cssClass = 'lowerCaseText'

    def _toFieldValue(self, input):
        return StrippedTextWidget._toFieldValue(self, input.lower())


class TokensTextWidget(StrippedTextWidget):
    """A widget that normalises the space between words.

    Punctuation is removed, and extra whitespace is stripped.
    """

    def _toFieldValue(self, input):
        """See `SimpleInputWidget`.

        Accept only alphanumeric characters and '-'.  Everything
        else is replaced with a single space.
        """
        normalised_text = re.sub(r'[^\w-]+', ' ', input)
        return super(TokensTextWidget, self)._toFieldValue(normalised_text)


class LocalDateTimeWidget(TextWidget):
    """A datetime widget that uses a particular time zone."""

    timeZoneName = 'UTC'

    def _toFieldValue(self, input):
        """Convert a string to a datetime value.

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__='foo', title=u'Foo')
          >>> widget = LocalDateTimeWidget(field, TestRequest())

        The widget converts an empty string to the missing value:

          >>> widget._toFieldValue('') == field.missing_value
          True

        By default, the date is interpreted as UTC:

          >>> print widget._toFieldValue('2006-01-01 12:00:00')
          2006-01-01 12:00:00+00:00

        But it will handle other time zones:

          >>> widget.timeZoneName = 'Australia/Perth'
          >>> print widget._toFieldValue('2006-01-01 12:00:00')
          2006-01-01 12:00:00+08:00

        Invalid dates result in a ConversionError:

          >>> print widget._toFieldValue('not a date')  #doctest: +ELLIPSIS
          Traceback (most recent call last):
            ...
          ConversionError: ('Invalid date value', ...)
        """
        if input == self._missing:
            return self.context.missing_value
        try:
            year, month, day, hour, minute, second, dummy_tz = parse(input)
            second, micro = divmod(second, 1.0)
            micro = round(micro * 1000000)
            dt = datetime.datetime(year, month, day,
                                   hour, minute, int(second), int(micro))
        except (DateTimeError, ValueError, IndexError), v:
            raise ConversionError('Invalid date value', v)
        tz = pytz.timezone(self.timeZoneName)
        return tz.localize(dt)

    def _toFormValue(self, value):
        """Convert a date to its string representation.

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__='foo', title=u'Foo')
          >>> widget = LocalDateTimeWidget(field, TestRequest())

        The 'missing' value is converted to an empty string:

          >>> widget._toFormValue(field.missing_value)
          u''

        Dates are displayed without an associated time zone:

          >>> dt = datetime.datetime(2006, 1, 1, 12, 0, 0,
          ...                        tzinfo=pytz.timezone('UTC'))
          >>> widget._toFormValue(dt)
          '2006-01-01 12:00:00'

        The date value will be converted to the widget's time zone
        before being displayed:

          >>> widget.timeZoneName = 'Australia/Perth'
          >>> widget._toFormValue(dt)
          '2006-01-01 20:00:00'
        """
        if value == self.context.missing_value:
            return self._missing
        tz = pytz.timezone(self.timeZoneName)
        return value.astimezone(tz).strftime('%Y-%m-%d %H:%M:%S')


class URIWidget(TextWidget):
    """A widget that represents a URI."""

    displayWidth = 44
    cssClass = 'urlTextType'


class DelimitedListWidget(TextAreaWidget):
    """A widget that represents a list as whitespace-delimited text.

    The delimiting methods can be easily overridden to work with
    comma, semi-colon, or other delimiters.
    """

    def __init__(self, field, value_type, request):
        # We don't use value_type.
        super(DelimitedListWidget, self).__init__(field, request)

    # The default splitting function, which splits on
    # white-space. Subclasses can override this if different
    # delimiting rules are needed.
    split = staticmethod(unicode.split)

    # The default joining function, which simply separates each list
    # item with a newline. Subclasses can override this if different
    # delimiters are needed.
    join = staticmethod(u'\n'.join)

    def _toFormValue(self, value):
        """Converts a list to a newline separated string.

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__='foo', title=u'Foo')
          >>> widget = DelimitedListWidget(field, None, TestRequest())

        The 'missing' value is converted to an empty string:

          >>> widget._toFormValue(field.missing_value)
          u''

        By default, lists are displayed one item on a line:

          >>> names = ['fred', 'bob', 'harry']
          >>> widget._toFormValue(names)
          u'fred\\r\\nbob\\r\\nharry'
        """
        if value == self.context.missing_value:
            value = self._missing
        elif value is None:
            value = self._missing
        else:
            value = self.join(value)
        return super(DelimitedListWidget, self)._toFormValue(value)

    def _toFieldValue(self, value):
        """Convert the input string into a list.

          >>> from zope.publisher.browser import TestRequest
          >>> from zope.schema import Field
          >>> field = Field(__name__='foo', title=u'Foo')
          >>> widget = DelimitedListWidget(field, None, TestRequest())

        The widget converts an empty string to the missing value:

          >>> widget._toFieldValue('') == field.missing_value
          True

        By default, lists are split by whitespace:

          >>> print widget._toFieldValue(u'fred\\nbob harry')
          [u'fred', u'bob', u'harry']
        """
        value = super(
            DelimitedListWidget, self)._toFieldValue(value)
        if value == self.context.missing_value:
            return value
        else:
            return self.split(value)
