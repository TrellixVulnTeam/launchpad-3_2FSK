# Copyright 2008 Canonical Ltd.

# This file is part of launchpadlib.
#
# launchpadlib is free software: you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation, either version 3 of the License, or (at your option)
# any later version.
#
# launchpadlib is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or
# FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General Public License for
# more details.
#
# You should have received a copy of the GNU General Public License along with
# launchpadlib.  If not, see <http://www.gnu.org/licenses/>.

"""Common support for web service collections."""

__metaclass__ = type
__all__ = [
    'Collection',
    'Entry',
    'NamedOperation',
    'Resource',
    ]


import simplejson
from urlparse import urlparse

from launchpadlib._utils.uri import URI
from launchpadlib.errors import HTTPError
from wadllib.application import Resource as WadlResource


class HeaderDictionary:
    """A dictionary that bridges httplib2's and wadllib's expectations.

    httplib2 expects all header dictionary access to give lowercase
    header names. wadllib expects to access the header exactly as it's
    specified in the WADL file, which means the official HTTP header name.

    This class transforms keys to lowercase before doing a lookup on
    the underlying dictionary. That way wadllib can pass in the
    official header name and httplib2 will get the lowercased name.
    """
    def __init__(self, wrapped_dictionary):
        self.wrapped_dictionary = wrapped_dictionary

    def get(self, key, default=None):
        """Retrieve a value, converting the key to lowercase."""
        return self.wrapped_dictionary.get(key.lower())

    def __getitem__(self, key):
        """Retrieve a value, converting the key to lowercase."""
        missing = object()
        value = self.get(key, missing)
        if value is missing:
            raise KeyError(key)
        return value


class LaunchpadBase:
    """Base class for classes that know about Launchpad."""

    def __init__(self, root):
        """Initialize with respect to a Launchpad object.

        :param root: A Launchpad object.
        """
        self._root = root

    def _transform_resources_to_links(self, dictionary):
        """Replace Resource objects with their URLs.

        In a web service, resources are identified by their
        URLs. Sending URLs over the wire avoids the need for any
        custom way of identifying objects.
        """
        new_dictionary = {}
        for key, value in dictionary.items():
            if isinstance(value, Resource):
                value = value.self_link
            new_dictionary[self._get_external_param_name(key)] = value
        return new_dictionary

    def _get_external_param_name(self, param_name):
        """Turn a launchpadlib name into something to be sent over HTTP."""
        raise NotImplementedError

    def _wrap_resource(self, resource, representation=None,
                       representation_media_type='application/json',
                       representation_needs_processing=True, param_name=None):
        """Create a launchpadlib Resource from a wadllib Resource.

        :param resource: The wadllib Resource to wrap.
        :param representation: A previously fetched representation of
                               this resource, to be reused.
        :param representation_media_type: The media type of the previously
                                          fetched representation.
        :param param_name: The name of the link that was followed to get
                           to this resource.
        :param representation_needs_processing: Set to False if the
            'representation' parameter should be used as
            is.
        :return: An instance of the appropriate launchpadlib Resource
        subclass.
        """
        if representation is None:
            # Get a representation of the linked resource.
            representation = self._root._browser.get(resource)
            representation_media_type = 'application/json'

        # We happen to know that all Launchpad resource types are
        # defined in a single document. Turn the resource's type_url
        # into an anchor into that document: this is its resource
        # type. Then look up a client-side class that corresponds to
        # the resource type.
        type_url = resource.type_url
        resource_type = urlparse(type_url)[-1]
        default = Entry
        if param_name is not None:
            if param_name.endswith('_collection_link'):
                default = Collection
        r_class = RESOURCE_TYPE_CLASSES.get(resource_type, default)
        return r_class(
            self._root, resource.bind(
                representation, representation_media_type,
                representation_needs_processing))


class Resource(LaunchpadBase):
    """Base class for Launchpad's HTTP resources."""

    def __init__(self, root, wadl_resource):
        """Initialize with respect to a wadllib Resource object."""
        if root is None:
            # This _is_ the root.
            root = self
        # These values need to be put directly into __dict__ to avoid
        # calling __setattr__, which would cause an infinite recursion.
        self.__dict__['_root'] = root
        self.__dict__['_wadl_resource'] = wadl_resource

    def lp_has_parameter(self, param_name):
        """Does this resource have a parameter with the given name?"""
        return self._get_external_param_name(param_name) is not None

    def lp_get_parameter(self, param_name):
        """Get the value of one of the resource's parameters.

        :return: A scalar value if the parameter is not a link. A new
                 Resource object, whose resource is bound to a
                 representation, if the parameter is a link.
        """
        for suffix in ['_link', '_collection_link']:
            param = self._wadl_resource.get_parameter(param_name + suffix)
            if param is not None:
                return self._wrap_resource(
                    param.linked_resource, param_name=param.name)
        param = self._wadl_resource.get_parameter(param_name)
        if param is None:
            raise KeyError("No such parameter: %s" % param_name)
        return param.get_value()

    def lp_get_named_operation(self, operation_name):
        """Get a custom operation with the given name.

        :return: A NamedOperation instance that can be called with
                 appropriate arguments to invoke the operation.
        """
        params = { 'ws.op' : operation_name }
        method = self._wadl_resource.get_method('get', query_params=params)
        if method is None:
            method = self._wadl_resource.get_method(
                'post', representation_params=params)
        if method is None:
            raise KeyError("No operation with name: %s" % operation_name)
        return NamedOperation(self._root, self, method)

    def lp_refresh(self, new_url=None):
        """Update this resource's representation."""
        if new_url is not None:
            self._wadl_resource._url = new_url
        representation = self._root._browser.get(self._wadl_resource)
        # __setattr__ assumes we're setting an attribute of the resource,
        # so we manipulate __dict__ directly.
        self.__dict__['_wadl_resource'] = self._wadl_resource.bind(
            representation, 'application/json')

    def __getattr__(self, attr):
        """Try to retrive a named operation or parameter of the given name."""
        try:
            return self.lp_get_parameter(attr)
        except KeyError:
            pass
        try:
            return self.lp_get_named_operation(attr)
        except KeyError:
            raise AttributeError("'%s' object has no attribute '%s'"
                                 % (self.__class__.__name__, attr))

    def _get_external_param_name(self, param_name):
        """What's this parameter's name in the underlying representation?"""
        for suffix in ['_link', '_collection_link', '']:
            name = param_name + suffix
            if self._wadl_resource.get_parameter(name):
                return name
        return None


class NamedOperation(LaunchpadBase):
    """A class for a named operation to be invoked with GET or POST."""

    def __init__(self, root, resource, wadl_method):
        """Initialize with respect to a WADL Method object"""
        super(NamedOperation, self).__init__(root)
        self.resource = resource
        self.wadl_method = wadl_method

    def __call__(self, **kwargs):
        """Invoke the method and process the result."""
        http_method = self.wadl_method.name
        args = self._transform_resources_to_links(kwargs)
        if http_method in ('get', 'head', 'delete'):
            url = self.wadl_method.build_request_url(**args)
            in_representation = ''
            extra_headers = {}
        else:
            url = self.wadl_method.build_request_url()
            (media_type,
             in_representation) = self.wadl_method.build_representation(
                **args)
            extra_headers = { 'Content-type' : media_type }
        response, content = self._root._browser._request(
            url, in_representation, http_method, extra_headers=extra_headers)

        if response.status == 201:
            # The operation may have resulted in the creation of a new
            # resource. If so, fetch it.
            wadl_response = self.wadl_method.response.bind(
                HeaderDictionary(response))
            wadl_parameter = wadl_response.get_parameter('Location')
            wadl_resource = wadl_parameter.linked_resource
            # Fetch a representation of the new resource.
            response, content = self._root._browser._request(
                wadl_resource.url)
            # Return an instance of the appropriate launchpadlib
            # Resource subclass.
            return self._wrap_resource(
                wadl_resource, content, response['content-type'])
        else:
            if http_method == 'post':
                # The method call probably modified this resource in
                # an unknown way. Refresh its representation.
                self.resource.lp_refresh()
            # Process the returned content, assuming we know how.
            if response['content-type'] == 'application/json':
                return simplejson.loads(content)
            return content

    def _get_external_param_name(self, param_name):
        """Named operation parameter names are sent as is."""
        return param_name


class Entry(Resource):
    """A class for an entry-type resource that can be updated with PATCH."""

    def __init__(self, root, wadl_resource):
        super(Entry, self).__init__(root, wadl_resource)
        # Initialize this here in a semi-magical way so as to stop a
        # particular infinite loop that would follow.  Setting
        # self._dirty_attributes would call __setattr__(), which would
        # turn around immediately and get self._dirty_attributes.  If
        # this latter was not in the instance dictionary, that would
        # end up calling __getattr__(), which would again reference
        # self._dirty_attributes.  This is where the infloop would
        # occur.  Poking this directly into self.__dict__ means that
        # the check for self._dirty_attributes won't call __getattr__(),
        # breaking the cycle.
        self.__dict__['_dirty_attributes'] = {}
        super(Entry, self).__init__(root, wadl_resource)

    def __str__(self):
        return '%s at %s' % (self.resource_type_link, self.self_link)

    def __getattr__(self, name):
        """Try to retrive a parameter of the given name."""
        if name != '_dirty_attributes':
            if name in self._dirty_attributes:
                return self._dirty_attributes[name]
        return super(Entry, self).__getattr__(name)

    def __setattr__(self, name, value):
        """Set the parameter of the given name."""
        if not self.lp_has_parameter(name):
            raise AttributeError("'%s' object has no attribute '%s'" %
                                 (self.__class__.__name__, name))
        self._dirty_attributes[name] = value

    def lp_refresh(self, new_url=None):
        """Update this resource's representation."""
        super(Entry, self).lp_refresh(new_url)
        self._dirty_attributes.clear()

    def lp_save(self):
        """Save changes to the entry."""
        representation = self._transform_resources_to_links(
            self._dirty_attributes)

        # PATCH the new representation to the 'self' link.  It's possible that
        # this will cause the object to be permanently moved.  Catch that
        # exception and refresh our representation.
        try:
            self._root._browser.patch(URI(self.self_link), representation)
        except HTTPError, error:
            if error.response.status == 301:
                self.lp_refresh(error.response['location'])
            else:
                raise
        self._dirty_attributes.clear()
        self.lp_refresh()


class Collection(Resource):
    """A collection-type resource that supports pagination."""

    def __init__(self, root, wadl_resource):
        """Create a collection object."""
        super(Collection, self).__init__(root, wadl_resource)

    def __len__(self):
        """The number of items in the collection.

        :return: length of the collection
        :rtype: int
        """
        try:
            return int(self.total_size)
        except AttributeError:
            raise TypeError('collection size is not available')

    def __iter__(self):
        """Iterate over the items in the collection.

        :return: iterator
        :rtype: sequence of `Person`
        """
        current_page = self._wadl_resource.representation
        while True:
            for entry_dict in current_page.get('entries', {}):
                resource_url = entry_dict['self_link']
                resource_type_link = entry_dict['resource_type_link']
                wadl_application = self._wadl_resource.application
                resource_type = wadl_application.get_resource_type(
                    resource_type_link)
                resource = WadlResource(
                    self._wadl_resource.application, resource_url,
                    resource_type.tag)
                yield self._wrap_resource(
                    resource, entry_dict, 'application/json', False)
            next_link = current_page.get('next_collection_link')
            if next_link is None:
                break
            current_page = simplejson.loads(
                self._root._browser.get(URI(next_link)))

    def __getitem__(self, key):
        """Look up a subordinate resource by unique ID."""
        try:
            url = self._get_url_from_id(key)
        except NotImplementedError:
            raise TypeError("unsubscriptable object")
        if url is None:
            raise KeyError(key)

        # We don't know what kind of resource this is. Even the
        # subclass doesn't necessarily know, because some resources
        # (the person list) are gateways to more than one kind of
        # resource (people, and teams). The only way to know for sure
        # is to retrieve a representation of the resource and see how
        # the resource describes itself.
        try:
            representation = simplejson.loads(self._root._browser.get(url))
        except HTTPError, error:
            # There's no resource corresponding to the given ID.
            if error.response.status == 404:
                raise KeyError(key)
            raise
        # We know that every Launchpad resource has a 'resource_type_link'
        # in its representation.
        resource_type_link = representation['resource_type_link']
        resource = WadlResource(self._root._wadl, url, resource_type_link)
        return Resource._wrap_resource(
            self._root, resource, representation=representation,
            representation_needs_processing=False)

    def _get_url_from_id(self, key):
        """Transform the unique ID of an object into its URL."""
        raise NotImplementedError()


class PersonSet(Collection):
    """A custom subclass capable of person lookup by username."""

    def _get_url_from_id(self, key):
        """Transform a username into the URL to a person resource."""
        return self._root.SERVICE_ROOT + '~' + str(key)


class BugSet(Collection):
    """A custom subclass capable of person lookup by bug ID."""

    def _get_url_from_id(self, key):
        """Transform a username into the URL to a person resource."""
        return self._root.SERVICE_ROOT + '/bugs/' + str(key)


# A mapping of resource type IDs to the client-side classes that handle
# those resource types.
RESOURCE_TYPE_CLASSES = { 'bugs' : BugSet,
                          'people' : PersonSet }
