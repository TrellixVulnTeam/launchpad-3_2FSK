# Copyright 2008 Canonical Ltd.  All rights reserved.
# Pylint doesn't grok zope interfaces.
# pylint: disable-msg=E0211,E0213

"""Interfaces for different kinds of HTTP resources."""

__metaclass__ = type
__all__ = [
    'IByteStorage',
    'IByteStorageResource',
    'ICollection',
    'ICollectionResource',
    'IEntry',
    'IEntryField',
    'IEntryFieldResource',
    'IEntryResource',
    'IFieldHTMLUnmarshaller',
    'IFieldMarshaller',
    'IHTTPResource',
    'IJSONPublishable',
    'IJSONRequestCache',
    'IResourceOperation',
    'IResourceGETOperation',
    'IResourcePOSTOperation',
    'IScopedCollection',
    'IServiceRootResource',
    'ITopLevelEntryLink',
    'IUnmarshallingDoesntNeedValue',
    'LAZR_WEBSERVICE_NAME',
    'LAZR_WEBSERVICE_NS',
    'WebServiceLayer',
    ]

from zope.interface import Attribute, Interface
# These two should really be imported from zope.interface, but
# the import fascist complains because they are not in __all__ there.
from zope.interface.interface import invariant
from zope.interface.exceptions import Invalid
from zope.publisher.interfaces.browser import IDefaultBrowserLayer


# The namespace prefix for LAZR web service-related tags.
LAZR_WEBSERVICE_NS = 'lazr.webservice'

# The namespace for LAZR web service tags having to do with the names
# of things.
LAZR_WEBSERVICE_NAME = '%s.name' % LAZR_WEBSERVICE_NS


class IHTTPResource(Interface):
    """An object published through HTTP."""

    def __call__():
        """Publish the object."""

    def getETag(media_type):
        "An ETag for this resource's current state."


class IJSONPublishable(Interface):
    """An object that can be published as a JSON data structure."""

    def toDataForJSON():
        """Return a representation that can be turned into JSON.

        The representation must consist entirely of simple data
        structures and IJSONPublishable objects.
        """

class IServiceRootResource(IHTTPResource):
    """A service root object that also acts as a resource."""

    def getTopLevelPublications(request):
        """Return a mapping of top-level link names to published objects."""


class IEntryResource(IHTTPResource):
    """A resource that represents an individual object."""

    def do_GET():
        """Retrieve this entry.

        :return: A string representation.
        """

    def do_PATCH(representation):
        """Update this entry.

        Try to update the entry to the field and values sent by the client.

        :param representation: A JSON representation of the field and values
            that should be modified.
        :return: None or an error message describing validation errors. The
            HTTP status code should be set appropriately.
        """

    def getContext():
        """Return the underlying entry for this resource."""


class IEntryFieldResource(IHTTPResource):
    """A resource that represents one of an entry's fields."""

    def do_GET():
        """Retrieve the value of the field.

        :return: A string representation.
        """


class ICollectionResource(IHTTPResource):
    """A resource that represents a collection of entry resources."""

    def do_GET():
        """Retrieve this collection.

        :return: A string representation.
        """


class IResourceOperation(Interface):
    """A one-off operation invokable on a resource."""

    def __call__():
        """Invoke the operation and create the HTTP response.

        :returns: If the result is a string, it's assumed that the
        Content-Type was set appropriately, and the result is returned
        as is. Otherwise, the result is serialized to JSON and served
        as application/json.
        """

    send_modification_event = Attribute(
        "Whether or not to send out an event when this operation completes.")


class IResourceGETOperation(IResourceOperation):
    """A one-off operation invoked through GET.

    This might be a search or lookup operation.
    """
    return_type = Attribute(
        "The type of the resource returned by this operation, if any.")


class IResourcePOSTOperation(IResourceOperation):
    """A one-off operation invoked through POST.

    This should be an operation that modifies the data set.
    """


class IEntry(Interface):
    """An entry, exposed as a resource by an IEntryResource."""

    schema = Attribute(
        'The schema describing the data fields on this entry.')

    @invariant
    def schemaIsProvided(value):
        """Make sure that the entry also provides its schema."""
        if not value.schema.providedBy(value):
            raise Invalid(
                "%s doesn't provide its %s schema." % (
                    type(value).__name__, value.schema.__name__))


class ICollection(Interface):
    """A collection, driven by an ICollectionResource."""

    entry_schema = Attribute("The schema for this collection's entries.")

    def find():
        """Retrieve all entries in the collection under the given scope.

        :return: A list of IEntry objects.
        """


class IScopedCollection(ICollection):

    relationship = Attribute("The relationship between an entry and a "
                             "collection.")
    collection = Attribute("The collection scoped to an entry.")


class IFieldHTMLUnmarshaller(Interface):
    """An interface that converts generic strings to HTML representations.

    This can be a callable class, or a function that returns another
    function.
    """

    def __call__(value):
        """Return the HTML version of the given string value."""


class IEntryField(Interface):
    """An individual field of an entry."""

    entry = Attribute("The entry whose field this is.")

    field = Attribute("The field, bound to the entry.")


class ITopLevelEntryLink(Interface):
    """A link to a special entry.

    For instance, an alias for the currently logged-in user.

    The link will be present in the representation of the service root
    resource.
    """

    link_name = Attribute("The name of the link to this entry in the "
                          "representation of the service root resource. "
                          "'_link' will be automatically appended.")

    entry_type = Attribute("The interface defined by the entry on the "
                           "other end of the link.")


class WebServiceLayer(IDefaultBrowserLayer):
    """Marker interface for requests to the web service."""


class IJSONRequestCache(Interface):
    """A cache of objects exposed as URLs or JSON representations."""

    links = Attribute("Objects whose links need to be exposed.");
    objects = Attribute("Objects whose JSON representations need "
                        "to be exposed.");


class IByteStorage(Interface):
    """A sequence of bytes stored on the server.

    The bytestream is expected to have a URL other than the one used
    by the web service.
    """

    alias_url = Attribute("The external URL to the byte stream.")
    filename = Attribute("Filename for the byte stream.")
    is_stored = Attribute("Whether or not there's a previously created "
                          "external byte stream here.")

    def createStored(mediaType, representation, filename=None):
        """Create a new stored bytestream.

        :param filename: The name of the file being stored. If None,
        the name of the storage field is used instead.
        """

    def deleteStored():
        """Delete an existing stored bytestream."""


class IByteStorageResource(IHTTPResource):
    """A resource that represents an external binary file."""

    def do_GET():
        """Redirect the client to the externally hosted file."""

    def do_PUT(media_type, representation):
        """Update the stored bytestream.

        :param media_type: The media type of the proposed new bytesteram.
        :param representation: The proposed new bytesteram.
        :return: None or an error message describing validation errors. The
            HTTP status code should be set appropriately.
        """

    def do_DELETE():
        """Delete the stored bytestream."""


class IFieldMarshaller(Interface):
    """A mapper between schema fields and their representation on the wire."""

    representation_name = Attribute(
        'The name to use for this field within the representation.')

    def marshall_from_json_data(value):
        """Transform the given data value into an object.

        This is used in PATCH/PUT requests when modifying the field, to get
        the actual value to use from the data submitted via JSON.

        :param value: A value obtained by deserializing a string into
            a JSON data structure.

        :return: The value that should be used to update the field.

        """

    def marshall_from_request(value):
        """Return the value to use based on the request submitted value.

        This is used by operation where the data comes from either the
        query string or the form-encoded POST data.

        :param value: The value submitted as part of the request.

        :return: The value that should be used to update the field.
        """

    def unmarshall(entry, value):
        """Transform an object value into a value suitable for JSON.

        :param entry: The entry whose field this is.
        :value: The object value of the field.

        :return: A value that can be serialized as part of a JSON hash.
        """


class IUnmarshallingDoesntNeedValue(Interface):
    """A marker interface for unmarshallers that work without values.

    Most marshallers transform the value they're given, but some work
    entirely on the field name. If they use this marker interface
    we'll save time because we won't have to calculate the value.
    """
