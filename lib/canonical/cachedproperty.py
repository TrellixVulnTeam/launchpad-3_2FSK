# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

"""Cached properties for situations where a property is computed once and
then returned each time it is asked for.
"""

__metaclass__ = type

import transaction


def cachedproperty(attrname_or_fn):
    """A decorator for methods that makes them properties with their return
    value cached.

    The value is cached on the instance, using the attribute name provided.

    If you don't provide a name, the mangled name of the property is used.

    >>> class CachedPropertyTest(object):
    ...
    ...     @cachedproperty('_foo_cache')
    ...     def foo(self):
    ...         print 'foo computed'
    ...         return 23
    ...
    ...     @cachedproperty
    ...     def bar(self):
    ...         print 'bar computed'
    ...         return 69

    >>> cpt = CachedPropertyTest()
    >>> getattr(cpt, '_foo_cache', None) is None
    True
    >>> cpt.foo
    foo computed
    23
    >>> cpt.foo
    23
    >>> cpt._foo_cache
    23
    >>> cpt.bar
    bar computed
    69
    >>> cpt._bar_cached_value
    69

    The cache is invalidated at transaction boundaries.

    >>> cpt.bar
    69
    >>> transaction.abort()
    >>> cpt.bar
    bar computed
    69
    >>> transaction.commit()
    >>> cpt.bar
    bar computed
    69

    """
    if isinstance(attrname_or_fn, basestring):
        attrname = attrname_or_fn
        return CachedPropertyForAttr(attrname)
    else:
        fn = attrname_or_fn
        attrname = '_%s_cached_value' % fn.__name__
        return CachedProperty(attrname, fn)


class CachedPropertyForAttr:

    def __init__(self, attrname):
        self.attrname = attrname

    def __call__(self, fn):
        return CachedProperty(self.attrname, fn)


_marker = object()


class CachedProperty:

    def __init__(self, attrname, fn):
        self.fn = fn
        self.attrname = attrname

    # Store the transaction the cached value is valid for,
    # so we can detect when it has become invalid.
    last_transaction = None

    def __get__(self, inst, cls=None):
        if inst is None:
            return self
        cachedresult = getattr(inst, self.attrname, _marker)
        current_transaction = transaction.get()
        if (cachedresult is _marker
            or self.last_transaction is not current_transaction):
            result = self.fn(inst)
            setattr(inst, self.attrname, result)
            self.last_transaction = current_transaction
            return result
        else:
            return cachedresult


if __name__ == '__main__':
    import doctest
    doctest.testmod()
