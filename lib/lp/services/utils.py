# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Generic Python utilities.

Functions, lists and so forth. Nothing here that does system calls or network
stuff.
"""

__metaclass__ = type
__all__ = [
    'CachingIterator',
    'decorate_with',
    'iter_split',
    'run_with',
    'synchronize',
    'text_delta',
    'value_string',
    ]

import itertools

from lazr.enum import BaseItem

from twisted.python.util import mergeFunctionMetadata
from zope.security.proxy import isinstance as zope_isinstance


def iter_split(string, splitter):
    """Iterate over ways to split 'string' in two with 'splitter'.

    If 'string' is empty, then yield nothing. Otherwise, yield tuples like
    ('a/b/c', ''), ('a/b', 'c'), ('a', 'b/c') for a string 'a/b/c' and a
    splitter '/'.

    The tuples are yielded such that the first tuple has everything in the
    first tuple. With each iteration, the first element gets smaller and the
    second gets larger. It stops iterating just before it would have to yield
    ('', 'a/b/c').
    """
    if string == '':
        return
    tokens = string.split(splitter)
    for i in reversed(range(1, len(tokens) + 1)):
        yield splitter.join(tokens[:i]), splitter.join(tokens[i:])


def synchronize(source, target, add, remove):
    """Update 'source' to match 'target' using 'add' and 'remove'.

    Changes the container 'source' so that it equals 'target', calling 'add'
    with any object in 'target' not in 'source' and 'remove' with any object
    not in 'target' but in 'source'.
    """
    need_to_add = [obj for obj in target if obj not in source]
    need_to_remove = [obj for obj in source if obj not in target]
    for obj in need_to_add:
        add(obj)
    for obj in need_to_remove:
        remove(obj)


def value_string(item):
    """Return a unicode string representing value.

    This text is special cased for enumerated types.
    """
    if item is None:
        return '(not set)'
    elif zope_isinstance(item, BaseItem):
        return item.title
    else:
        return unicode(item)


def text_delta(instance_delta, delta_names, state_names, interface):
    """Return a textual delta for a Delta object.

    A list of strings is returned.

    Only modified members of the delta will be shown.

    :param instance_delta: The delta to generate a textual representation of.
    :param delta_names: The names of all members to show changes to.
    :param state_names: The names of all members to show only the new state
        of.
    :param interface: The Zope interface that the input delta compared.
    """
    output = []
    indent = ' ' * 4

    # Fields for which we have old and new values.
    for field_name in delta_names:
        delta = getattr(instance_delta, field_name, None)
        if delta is None:
            continue
        title = interface[field_name].title
        old_item = value_string(delta['old'])
        new_item = value_string(delta['new'])
        output.append("%s%s: %s => %s" % (indent, title, old_item, new_item))
    for field_name in state_names:
        delta = getattr(instance_delta, field_name, None)
        if delta is None:
            continue
        title = interface[field_name].title
        if output:
            output.append('')
        output.append('%s changed to:\n\n%s' % (title, delta))
    return '\n'.join(output)


class CachingIterator:
    """Remember the items extracted from the iterator for the next iteration.

    Some generators and iterators are expensive to calculate, like calculating
    the merge sorted revision graph for a bazaar branch, so you don't want to
    call them too often.  Rearranging the code so it doesn't call the
    expensive iterator can make the code awkward.  This class provides a way
    to have the iterator called once, and the results stored.  The results
    can then be iterated over again, and more values retrieved from the
    iterator if necessary.
    """

    def __init__(self, iterator):
        self.iterator = iterator
        self.data = []

    def __iter__(self):
        index = itertools.count()
        while True:
            pos = index.next()
            try:
                yield self.data[pos]
            except IndexError:
                # Defer to the iterator.
                pass
            else:
                continue
            if self.iterator is None:
                break
            try:
                item = self.iterator.next()
            except StopIteration:
                self.iterator = None
                break
            self.data.append(item)
            yield item


def run_with(context, function, *args, **kwargs):
    """Run 'function' with 'context'.

    Runs the given function with arbitrary arguments and keyword arguments
    with the given context. Returns the return value of 'function'.
    """
    with context:
        return function(*args, **kwargs)


def decorate_with(context):
    """Create a decorator that runs decorated functions with 'context'."""
    def decorator(function):
        def decorated(*args, **kwargs):
            with context:
                return function(*args, **kwargs)
        return mergeFunctionMetadata(function, decorated)
    return decorator
