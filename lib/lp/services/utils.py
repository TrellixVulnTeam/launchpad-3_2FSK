# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).


"""Implementations of the XML-RPC APIs for codehosting."""

__metaclass__ = type
__all__ = [
    'iter_split',
    'text_delta',
    'value_string',
    ]

from zope.security.proxy import isinstance as zope_isinstance
from lazr.enum import BaseItem


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


def value_string(item):
    """Return a unicode string representing an SQLObject value."""
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
