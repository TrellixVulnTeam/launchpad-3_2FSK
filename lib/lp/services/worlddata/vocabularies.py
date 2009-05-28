# Copyright 2005 Canonical Ltd.  All rights reserved.

__all__ = [
    'TimezoneNameVocabulary',
    ]

__metaclass__ = type

import pytz

from zope.interface import alsoProvides
from zope.schema.vocabulary import SimpleVocabulary

from canonical.lazr.interfaces.timezone import ITimezoneNameVocabulary


# create a sorted list of the common time zone names, with UTC at the start
_values = sorted(pytz.common_timezones)
_values.remove('UTC')
_values.insert(0, 'UTC')
# The tzdata package may not contain all the timezone files that pytz
# thinks exist.
for timezone_name in _values:
    try:
        pytz.timezone(timezone_name)
    except (pytz.UnknownTimeZoneError, IOError):
        # XXX Edwin Grubbs 2008-07-03 bug=244681
        # pytz.timezone() should not throw an IOError.
        _values.remove(timezone_name)

_timezone_vocab = SimpleVocabulary.fromValues(_values)
alsoProvides(_timezone_vocab, ITimezoneNameVocabulary)
del _values

def TimezoneNameVocabulary(context=None):
    return _timezone_vocab
