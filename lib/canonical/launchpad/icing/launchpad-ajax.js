// An AJAX client that runs against Launchpad's web service.
LP = (typeof(LP) != "undefined") ? LP : {};
LP.client = (typeof LP.client != "undefined") ? LP.client : {};
LP.client.links = (typeof LP.links !== "undefined") ? LP.client.links : {};
LP.client.cache = (typeof LP.objects !== "undefined") ? LP.client.cache : {};

YUI().use("attribute", "io", "json-parse", "json-stringify", function(Y) {

LP.client.HTTP_CREATED = 201;
LP.client.HTTP_SEE_ALSO = 303;
LP.client.HTTP_NOT_FOUND = 404;

// Generally useful functions.
LP.client.append_qs = function(qs, key, value) {
    /* Append a key-value pair to a query string. */
    if (qs === undefined) {
        qs = "";
    }
    if (qs.length > 0) {
        qs += '&';
    }
    qs += escape(key) + "=" + escape(value);
    return qs;
};

LP.client.extract_webservice_start = function(url) {
    /* Extract the service's root URI from any Launchpad web service URI. */
    var host_start = url.indexOf('//');
    var host_end = url.indexOf('/', host_start+2);
    return url.substring(0, host_end+1) + 'api/beta/';
};

LP.client.start_and_size = function(data, start, size) {
    /* Create a query string with values for ws.start and/or ws.size. */
    if (start !== undefined) {
        data = LP.client.append_qs(data, "ws.start", start);
    }
    if (size !== undefined) {
        data = LP.client.append_qs(data, "ws.size", size);
    }
    return data;
};

LP.client.wrap_resource_on_success = function(ignore, response, args) {
    var client = args[0];
    var uri = args[1];
    var old_on_success = args[2];
    var representation = Y.JSON.parse(response.responseText);
    var wrapped = client.wrap_resource(uri, representation);
    return old_on_success(wrapped);
};


// The resources that come together to make Launchpad.

// A hosted file resource.

LP.client.HostedFile = function(client, uri, content_type, contents) {
    /* A binary file manipulable through the web service. */
    this.lp_client = client;
    this.uri = uri;
    this.content_type = content_type;
    this.contents = contents;
};

LP.client.HostedFile.prototype = {

    'lp_save' : function(config) {
        /* Write a new version of this file back to the web service. */
        var on = config.on;
        var disposition = 'attachment; filename="' + this.filename + '"';
        var hosted_file = this;
        var args = hosted_file;
        var y_config = {
            method: "PUT",
            'on': on,
            'headers': {"Content-Type": hosted_file.content_type,
                        "Content-Disposition": disposition},
            'arguments': args,
            'data': hosted_file.contents};
        Y.io(hosted_file.uri, y_config);
    },

    'lp_delete' : function(config) {
        var on = config.on;
        var hosted_file = this;
        var args = hosted_file;
        var y_config = { method: "DELETE",
                         on: on,
                         'arguments': args };
        Y.io(hosted_file.uri, y_config);
    }
};

LP.client.Resource = function() {
    /* The base class for objects retrieved from Launchpad's web service. */
};
LP.client.Resource.prototype = {
    'init': function(client, representation, uri) {
        /* Initialize a resource with its representation and URI. */
        this.lp_client = client;
        this.lp_original_uri = uri;
        for (key in representation) {
            if (representation.hasOwnProperty(key)) {
                this[key] = representation[key];
            }
        }
    },

    'lookup_value': function(key) {
        /* A common getter interface for Entrys and non-Entrys. */
        return this[key];
    },

    'follow_link': function(link_name, config) {
        /* Return the object at the other end of the named link. */
        var on = config.on;
        var uri = this.lookup_value(link_name + '_link');
        if (uri === undefined) {
            uri = this.lookup_value(link_name + '_collection_link');
        }
        if (uri === undefined) {
            throw new Error("No such link: " + link_name);
        }

        // If the response is 404, it means we have a hosted file that
        // doesn't exist yet. If the response is 303 and goes off to another
        // site, that means we have a hosted file that does exist. Either way
        // we should turn the failure into a success.
        var on_success = on.success;
        var old_on_failure = on.failure;
        on.failure = function(ignore, response, args) {
            var client = args[1];
            var original_url = args[2];
            if (response.status == LP.client.HTTP_NOT_FOUND ||
                response.status == LP.client.HTTP_SEE_ALSO) {
                var file = new LP.client.HostedFile(client, original_url);
                return on_success(file);
            } else if (old_on_failure !== undefined) {
                return old_on_failure(ignore, response, args);
            }
        };
        this.lp_client.get(uri, {on: on});
    },

    'named_get': function(operation_name, config) {
        /* Get the result of a named GET operation on this resource. */
        return this.lp_client.named_get(this.lp_original_uri, operation_name,
                                        config);
    },

    'named_post': function(operation_name, config) {
        /* Trigger a named POST operation on this resource. */
        return this.lp_client.named_post(this.lp_original_uri, operation_name,
                                         config);
    }
};

// The service root resource.
LP.client.Root = function(client, representation, uri) {
    /* The root of the Launchpad web service. */
    this.init(client, representation, uri);
};
LP.client.Root.prototype = new LP.client.Resource();

LP.client.Collection = function(client, representation, uri) {
    /* A grouped collection of objets from the Launchpad web service. */
    this.init(client, representation, uri);
};

LP.client.Collection.prototype = new LP.client.Resource();

LP.client.Collection.prototype.lp_slice = function(on, start, size) {
    /* Retrieve a subset of the collection.

       :param start: Where in the collection to start serving entries.
       :param size: How many entries to serve.
    */
    return this.lp_client.get(this.lp_original_uri,
                              {on: on, start: start, size: size});
};


LP.client.Entry = function(client, representation, uri) {
    /* A single object from the Launchpad web service. */
    this.lp_client = client;
    this.lp_original_uri = uri;
    this.dirty_attributes = [];
    var entry = this;

    for (key in representation) {
        if (representation.hasOwnProperty(key)) {
            this.set(key, representation[key]);
            this.on(key + "Change", this.mark_as_dirty);
        }
    }
};

LP.client.Entry.prototype = new LP.client.Resource();
Y.augment(LP.client.Entry, Y.Attribute);

LP.client.Entry.prototype.mark_as_dirty = function(event) {
    /* Respond to an event triggered by modification to an Entry's field. */
    if (event.newVal != event.prevVal) {
        this.dirty_attributes.push(event.attrName);
    }
};

LP.client.Entry.prototype.lp_save = function(config) {
    /* Write modifications to this entry back to the web service. */
    var on = config.on;
    var representation = {};
    var entry = this;
    Y.each(this.dirty_attributes, function(attribute, key) {
            representation[attribute] = entry.get(attribute);
        });
    var headers = {};
    if (this.get('http_etag') !== undefined) {
        headers['If-Match'] = this.get('http_etag');
    }
    this.lp_client.patch(this.get('self_link'), representation, {on: on},
                         headers);
    this.dirty_attributes = [];
};

LP.client.Entry.prototype.lookup_value = function(key) {
    /* A common getter interface between Entrys and non-Entrys. */
    return this.get(key);
};


// The Launchpad client itself.

LP.client.Launchpad = function() {
    /* A client that makes HTTP requests to Launchpad's web service. */
};

LP.client.Launchpad.prototype = {
    'base': LP.client.extract_webservice_start(location.href),
    'get': function (uri, config) {
        /* Get the current state of a resource. */
        var on = config.on;
        var start = config.start;
        var size = config.size;
        var data = config.data;
        if (uri.indexOf("http") !== 0) {
            uri = this.base + uri;
        }
        if (data === undefined) {
            data = "";
        }
        if (start !== undefined || size !== undefined) {
            data = LP.client.start_and_size(data, start, size);
        }

        var old_on_success = on.success;
        on.success = LP.client.wrap_resource_on_success;

        var client = this;
        var y_config = { on: on,
                         'arguments': [client, uri, old_on_success],
                         data: data};
        Y.io(uri, y_config);
    },

    'named_get' : function(uri, operation_name, config) {
        /* Retrieve the value of a named GET operation on the given URI. */
        var parameters = config.parameters;
        var data = LP.client.append_qs("", "ws.op", operation_name);
        for (name in parameters) {
            if (parameters.hasOwnProperty(name)) {
                data = LP.client.append_qs(data, name, parameters[name]);
            }
        }
        config.data = data;
        return this.get(uri, config);
    },

    'named_post' : function (uri, operation_name, config) {
        /* Perform a named POST operation on the given URI. */
        var on = config.on;
        var parameters = config.parameters;
        if (uri.indexOf("http") !== 0) {
            uri = this.base + uri;
        }
        var data = LP.client.append_qs(data, "ws.op", operation_name);
        for (name in parameters) {
            if (parameters.hasOwnProperty(name)) {
                data = LP.client.append_qs(data, name, parameters[name]);
            }
        }

        var old_on_success = on.success;

        on.success = function(unknown, response, args) {
            if (response.status == LP.client.HTTP_CREATED) {
                // A new object was created as a result of the operation.
                // Get that object and run the callback on it instead.
                var new_location = response.getResponseHeader("Location");
                return client.get(new_location,
                                  { on: { success: old_on_success,
                                              failure: on.failure } });
            }
            return LP.client.wrap_resource_on_success(undefined, response, args);
        };
        var client = this;
        var y_config = { method: "POST",
                         on: on,
                         'arguments': [client, uri, old_on_success],
                         data: data};
        Y.io(uri, y_config);
    },

    'patch': function(uri, representation, config, headers) {
        var on = config.on;
        var data = Y.JSON.stringify(representation);
        if (uri.indexOf("http") !== 0) {
            uri = this.base + uri;
        }
        args = [this.lp_client, uri];

        var extra_headers = {
                "X-HTTP-Method-Override": "PATCH",
                "Content-Type": "application/json",
                "X-Content-Type-Override": "application/json"
        };
        if (headers) {
            for (name in headers) {
                if (headers.hasOwnProperty(name)) {
                    extra_headers[name] = headers[name];
                }
            }
        }

        var y_config = {
            'method': "POST",
            'on': on,
            'headers': extra_headers,
            'arguments': args,
            'data': data
        };
        Y.io(uri, y_config);
    },

    'wrap_resource': function(uri, representation) {
        /* Given a representation, turn it into a subclass of Resource. */
        var obj = undefined;
        if (representation === null || representation === undefined) {
            return representation;
        }
        if (representation.lp_redirect_location !== undefined) {
            uri = representation.lp_redirect_location;
        }
        if (representation.resource_type_link === undefined) {
            // This is a non-entry object returned by a named operation.
            // It's either a list or a random JSON object.
            if (representation.total_size !== undefined) {
                // It's a list. Treat it as a collection; it should be slicable.
                obj = new LP.client.Collection(this, representation, uri);
            }
            // It's a random JSON object. Leave it alone.
        } else if (representation.resource_type_link.search(
            /\/#service-root$/) !== -1) {
            obj = new LP.client.Root(this, representation, uri);
        } else if (representation.total_size === undefined) {
            obj = new LP.client.Entry(this, representation, uri);
        } else {
            obj = new LP.client.Collection(this, representation, uri);
        }
        return obj;
    }
};
});
