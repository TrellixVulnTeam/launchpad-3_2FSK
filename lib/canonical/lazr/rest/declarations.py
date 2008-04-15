# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Declaration helpers to define a web service."""

__metaclass__ = type
__all__ = [
    'COLLECTION_TYPE',
    'ENTRY_TYPE',
    'FIELD_TYPE',
    'LAZR_WEBSERVICE_EXPORTED',
    'LAZR_WEBSERVICE_NS',
    'collection_default_content',
    'export_collection',
    'export_entry',
    'export_field',
    ]

import sys

from zope.interface.advice import addClassAdvisor
from zope.interface.interface import TAGGED_DATA
from zope.interface.interfaces import IInterface
from zope.schema.interfaces import IField

LAZR_WEBSERVICE_NS = 'lazr.webservice'
LAZR_WEBSERVICE_EXPORTED = '%s.exported' % LAZR_WEBSERVICE_NS
COLLECTION_TYPE = 'collection'
ENTRY_TYPE = 'entry'
FIELD_TYPE = 'field'


def _check_called_from_interface_def(name):
    """Make sure that the declaration was used from within a class definition.
    """
    # 2 is our caller's caller.
    frame = sys._getframe(2)
    f_locals = frame.f_locals

    # Try to make sure we were called from a class def.
    if (f_locals is frame.f_globals) or ('__module__' not in f_locals):
        raise TypeError(
            "%s can only be used from within an interface definition." % name)


def _check_interface(name, interface):
    """Check that interface provides IInterface or raise a TypeError."""
    if not IInterface.providedBy(interface):
        raise TypeError("%s can only be used on an interface." % name)


def _get_interface_tags():
    """Retrieve the dictionary containing tagged values for the interface.

    This will create it, if it hasn't been defined yet.
    """
    # Our caller is contained within the interface definition.
    f_locals = sys._getframe(2).f_locals
    return f_locals.setdefault(TAGGED_DATA, {})


def export_entry():
    """Mark the content interface as exported on the web service as an entry.
    """
    _check_called_from_interface_def('export_entry()')
    def mark_entry(interface):
        """Class advisor that tags the interface once it is created."""
        _check_interface('export_entry()', interface)
        interface.setTaggedValue(
            LAZR_WEBSERVICE_EXPORTED, dict(type=ENTRY_TYPE))

        # Set the name of the fields that didn't specify it using the 'as'
        # parameter in export_field. This must be done here, because the
        # field's __name__ attribute is only set when the interface is
        # created.
        for name in interface.names(False):
            tag = interface[name].queryTaggedValue(LAZR_WEBSERVICE_EXPORTED)
            if tag is None:
                continue
            if tag['type'] != FIELD_TYPE:
                continue
            if tag['as'] is None:
                tag['as'] = name

        return interface
    addClassAdvisor(mark_entry)


def export_field(field, as=None):
    """Mark the field as part of the entry data model.

    :param as: the name under which the field is published in the entry. By
        default, the same name is used.
    :raises TypeError: if called on an object which doesn't provide IField.
    """
    if not IField.providedBy(field):
        raise TypeError("export_field() can only be used on IFields.")
    field.setTaggedValue(
        LAZR_WEBSERVICE_EXPORTED, dict(type=FIELD_TYPE, as=as))


def export_collection():
    """Mark the interface as exported on the web service as a collection.

    :raises TypeError: if the interface doesn't have a method decorated with
        @collection_default_content.
    """
    _check_called_from_interface_def('export_collection()')

    # Set the tag at this point, so that future declarations can
    # check it.
    tags = _get_interface_tags()
    tags[LAZR_WEBSERVICE_EXPORTED] = dict(type=COLLECTION_TYPE)

    def verify_collection(interface):
        """Class advisor verifying the collection export requirements."""
        _check_interface('export_collection()', interface)

        tag = interface.getTaggedValue(LAZR_WEBSERVICE_EXPORTED)
        if 'collection_default_content' not in tag:
            raise TypeError(
                "export_collection() is missing a method tagged with "
                "@collection_default_content.")
        return interface

    addClassAdvisor(verify_collection)


def collection_default_content(f):
    """Decorates the method that provides the default values of a collection.

    :raises TypeError: if not called from within an interface exported as a
        collection, or if used more than once in the same interface.
    """
    _check_called_from_interface_def('@collection_default_content')

    tags = _get_interface_tags()
    tag = tags.get(LAZR_WEBSERVICE_EXPORTED)
    if tag is None or tag['type'] != COLLECTION_TYPE:
        raise TypeError(
            "@collection_default_content can only be used from within an "
            "interface exported as a collection.")

    if 'collection_default_content' in tag:
        raise TypeError(
            "only one method should be marked with "
            "@collection_default_content.")

    tag['collection_default_content'] = f.__name__

    return f
