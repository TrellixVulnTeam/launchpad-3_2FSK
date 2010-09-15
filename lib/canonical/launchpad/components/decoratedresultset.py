# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=E0611,W0212

__metaclass__ = type
__all__ = [
    'DecoratedResultSet',
    ]

from lazr.delegates import delegates
from storm import Undef
from storm.zope.interfaces import IResultSet
from zope.security.proxy import removeSecurityProxy


class DecoratedResultSet(object):
    """A decorated Storm ResultSet for 'Magic' (presenter) classes.

    Because `DistroSeriesBinaryPackage` doesn't actually exist in the
    database, the `DistroSeries`.searchPackages method uses the
    `DistroSeriesPackageCache` object to search for packages within a
    `DistroSeries`.

    Nonetheless, the users of the searchPackages method (such as the
    `DistroSeriesView`) expect a result set of DSBPs. Rather than executing
    the query prematurely and doing a list comprehension on the complete
    result set (which could be very large) to convert all the results (even
    though batching may mean only a window of 10 results is required), this
    adapted result set converts the results only when they are needed.

    This behaviour is required for other classes as well (Distribution,
    DistroArchSeries), hence a generalised solution.
    """
    delegates(IResultSet, context='result_set')

    def __init__(self, result_set, result_decorator=None, pre_iter_hook=None,
        slice_info=False):
        """
        :param result_set: The original result set to be decorated.
        :param result_decorator: The method with which individual results
            will be passed through before being returned.
        :param pre_iter_hook: The method to be called (with the 'result_set')
            immediately before iteration starts.
        :param slice_info: If True pass information about the slice parameters
            to the result_decoratora and pre_iter_hook. any() and similar
            methods will cause None to be supplied.
        """
        self.result_set = result_set
        self.result_decorator = result_decorator
        self.pre_iter_hook = pre_iter_hook
        self.slice_info = slice_info

    def decorate_or_none(self, result, row_index=None):
        """Decorate a result or return None if the result is itself None"""
        if result is None:
            return None
        else:
            if self.result_decorator is None:
                return result
            elif self.slice_info:
                return self.result_decorator(result, row_index)
            else:
                return self.result_decorator(result)

    def copy(self, *args, **kwargs):
        """See `IResultSet`.

        :return: The decorated version of the returned result set.
        """
        new_result_set = self.result_set.copy(*args, **kwargs)
        return DecoratedResultSet(
            new_result_set, self.result_decorator, self.pre_iter_hook,
            self.slice_info)

    def config(self, *args, **kwargs):
        """See `IResultSet`.

        :return: The decorated result set.after updating the config.
        """
        self.result_set.config(*args, **kwargs)
        return self

    def __iter__(self, *args, **kwargs):
        """See `IResultSet`.

        Yield a decorated version of the returned value.
        """
        # Execute/evaluate the result set query.
        results = list(self.result_set.__iter__(*args, **kwargs))
        if self.slice_info:
            # Calculate slice data
            start = self.result_set._offset
            if start is Undef:
                start = 0
            stop = start + len(results)
            slice_info = slice(start, stop)
        if self.pre_iter_hook is not None:
            if self.slice_info:
                self.pre_iter_hook(results, slice_info)
            else:
                self.pre_iter_hook(results)
        if self.slice_info:
            start = slice_info.start
            for offset, value in enumerate(results):
                yield self.decorate_or_none(value, offset + start)
        else:
            for value in results:
                yield self.decorate_or_none(value)

    def __getitem__(self, *args, **kwargs):
        """See `IResultSet`.

        :return: The decorated version of the returned value.
        """
        # Can be a value or result set...
        value = self.result_set.__getitem__(*args, **kwargs)
        naked_value = removeSecurityProxy(value)
        if IResultSet.providedBy(naked_value):
            return DecoratedResultSet(
                value, self.result_decorator, self.pre_iter_hook,
                self.slice_info)
        else:
            return self.decorate_or_none(value)

    def any(self, *args, **kwargs):
        """See `IResultSet`.

        :return: The decorated version of the returned value.
        """
        value = self.result_set.any(*args, **kwargs)
        return self.decorate_or_none(value)

    def first(self, *args, **kwargs):
        """See `IResultSet`.

        :return: The decorated version of the returned value.
        """
        value = self.result_set.first(*args, **kwargs)
        return self.decorate_or_none(value)

    def last(self, *args, **kwargs):
        """See `IResultSet`.

        :return: The decorated version of the returned value.
        """
        value = self.result_set.last(*args, **kwargs)
        return self.decorate_or_none(value)

    def one(self, *args, **kwargs):
        """See `IResultSet`.

        :return: The decorated version of the returned value.
        """
        value = self.result_set.one(*args, **kwargs)
        return self.decorate_or_none(value)

    def order_by(self, *args, **kwargs):
        """See `IResultSet`.

        :return: The decorated version of the returned result set.
        """
        new_result_set = self.result_set.order_by(*args, **kwargs)
        return DecoratedResultSet(
            new_result_set, self.result_decorator, self.pre_iter_hook,
            self.slice_info)
