
// An AJAX client that runs against Launchpad's web service.
LP = (typeof(LP) != "undefined") ? LP : {};
LP.client = (typeof LP.client != "undefined") ? LP.client : {};
LP.client.links = (typeof LP.links !== "undefined") ? LP.client.links : {};
LP.client.cache = (typeof LP.objects !== "undefined") ? LP.client.cache : {};

LPS.use("attribute", "io-base", "json-parse", "json-stringify", function(Y) {

LP.client.HTTP_CREATED = 201;
LP.client.HTTP_SEE_ALSO = 303;
LP.client.HTTP_NOT_FOUND = 404;

LP.client.XHTML = 'application/xhtml+xml';

/* Log the normal attributes accessible via o[key], and if it is a
 * YUI node, log all of the attributes accessible via o.get(key).
 * This function is not recursive to keep the log output reasonable.
 *
 * @method log_object
 * @param o The object being logged.
 * @param {String} name An optional name to describe the object.
 */
LP.log_object = function(o, name) {
    var result;
    var format = function(value) {
        if (typeof value == 'string') {
            value = value.substring(0, 200); // Truncate long strings.
            return '"' + value + '"';
        } else if (typeof value == 'function') {
            // Only log the function parameters instead
            // of the whole code block.
            return String(value).split(" {")[0];
        } else if (value instanceof Array) {
            return 'Array of length ' + value.length;
        } else {
            return String(value);
        }
    };

    var introspect = function(collection) {
        var items = [];
        var keys = [];
        var key;
        for (key in collection) {
            if (collection.hasOwnProperty(key)) {
                keys.push(key);
            }
        }
        keys.sort();
        for (var index in keys) {
            if (keys.hasOwnProperty(index)) {
                key = keys[index];
                var value;
                try {
                    value = format(collection[key]);
                } catch (e) {
                    // This is necessary to handle attributes which
                    // will throw a permission denied error.
                    value = e.message;
                }
                items.push(key + '=' + value);
            }
        }
        return items.join(',\n  ');
    };

    if (o === null || typeof o == 'string' || typeof o == 'function') {
        result = format(o);
    } else {
        result = '(direct-attributes)\n  ' + introspect(o);
        if (o.getAttrs !== undefined) {
            result += '\n(get()-attributes)\n  ' + introspect(o.getAttrs());
        }
    }
    if (name !== undefined) {
        result = name + ': ' + result;
    }
    Y.log(result);
};

// Generally useful functions.
LP.client.append_qs = function(qs, key, value) {
    /* Append a key-value pair to a query string. */
    if (qs === undefined) {
        qs = "";
    }
    if (qs.length > 0) {
        qs += '&';
    }
    qs += encodeURIComponent(key) + "=" + encodeURIComponent(value);
    return qs;
};

LP.client.normalize_uri = function(uri) {
    /* Converts an absolute URI into a relative URI.

       Appends the root to a relative URI that lacks the root.

       Does nothing to a relative URI that includes the root.*/
    var host_start = uri.indexOf('//');
    if (host_start != -1) {
        var host_end = uri.indexOf('/', host_start+2);
        // eg. "http://www.example.com/api/devel/foo";
        // Don't try to insert the service base into what was an
        // absolute URL. So "http://www.example.com/foo" becomes "/foo"
        return uri.substring(host_end, uri.length);
    }

    var base = "/api/devel";
    if (uri.indexOf(base.substring(1, base.length)) === 0) {
        // eg. "api/devel/foo"
        return '/' + uri;
    }
    if (uri.indexOf(base) !== 0) {
        if (uri.indexOf('/') !== 0) {
            // eg. "foo/bar"
            uri = base + '/' + uri;
        } else {
            // eg. "/foo/bar"
            uri = base + uri;
        }
    }
    return uri;
};

/**
 * After normalizing the uri, turn it into an absolute uri.
 * This is useful for passing in parameters to named_post and patch.
 *
 * @method get_absolute_uri
 * @param {String} uri
 * @return {String} URI.
 */
LP.client.get_absolute_uri = function(uri) {
    var location = document.location;

    uri = LP.client.normalize_uri(uri);
    return location.protocol + '//' + location.host + uri;
};

/**
 * Turn an entry resource URI and a field name into a field resource URI.
 * @method get_field_uri
 * @param {String} base_uri
 * @param {String} field_name
 * @return {String} URI
 */
LP.client.get_field_uri = function(base_uri, field_name) {
    base_uri = LP.client.normalize_uri(base_uri);
    field_name = escape(field_name);
    if (base_uri.charAt(base_uri.length - 1) == '/') {
        return base_uri + field_name;
    } else {
        return base_uri + '/' + field_name;
    }
};

LP.client.add_accept = function(config, headers) {
    if (headers === undefined) {
        headers = {};
    }
    var accept = config.accept || 'application/json';
    headers.Accept = accept;
    return headers;
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
    var representation, wrapped;
    if (old_on_success) {
        var media_type = response.getResponseHeader('Content-Type');
        if (media_type == 'application/json') {
            representation = Y.JSON.parse(response.responseText);
            wrapped = client.wrap_resource(uri, representation);
            return old_on_success(wrapped);
        } else {
            return old_on_success(response.responseText);
        }
    }
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
        Y.io(LP.client.normalize_uri(hosted_file.uri), y_config);
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
            var client = args[0];
            var original_url = args[1];
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
    var index, entry;
    this.init(client, representation, uri);
    for (index = 0 ; index < this.entries.length ; index++) {
        entry = this.entries[index];
        this.entries[index] = new LP.client.Entry(client, 
        	entry, entry.self_link);
    }
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

    // Copy the representation keys into our own set of attributes, and add
    // an attribute-change event listener for caching purposes.
    for (key in representation) {
        if (representation.hasOwnProperty(key)) {
            this.addAttr(key, {value: representation[key]});
            this.on(key + "Change", this.mark_as_dirty);
        }
    }
};

LP.client.Entry.prototype = new LP.client.Resource();

// Augment with Attribute so that we can listen for attribute change events.
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
    var uri = LP.client.normalize_uri(this.get('self_link'));
    this.lp_client.patch(uri, representation, config, headers);
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
    'get': function (uri, config) {
        /* Get the current state of a resource. */
        var on = Y.merge(config.on);
        var start = config.start;
        var size = config.size;
        var data = config.data;
        var headers = LP.client.add_accept(config);
        uri = LP.client.normalize_uri(uri);
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
                         'headers': headers,
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
        var on = Y.merge(config.on);
        var parameters = config.parameters;
        uri = LP.client.normalize_uri(uri);
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
        uri = LP.client.normalize_uri(uri);

        var old_on_success = on.success;
        on.success = LP.client.wrap_resource_on_success;
        args = [this, uri, old_on_success];

        var extra_headers = {
                "X-HTTP-Method-Override": "PATCH",
                "Content-Type": "application/json",
                "X-Content-Type-Override": "application/json"
        };
        if (headers !== undefined) {
            for (name in headers) {
                if (headers.hasOwnProperty(name)) {
                    extra_headers[name] = headers[name];
                }
            }
        }
        extra_headers = LP.client.add_accept(config, extra_headers);

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
                return new LP.client.Collection(this, representation, uri);
            } else {
                // It's a random JSON object. Leave it alone.
                return representation;
            }
        } else if (representation.resource_type_link.search(
            /\/#service-root$/) !== -1) {
            return new LP.client.Root(this, representation, uri);
        } else if (representation.total_size === undefined) {
            return new LP.client.Entry(this, representation, uri);
        } else {
            return new LP.client.Collection(this, representation, uri);
        }
    }
};
});

LPS.add('lp.client.plugins', function (Y) {

/**
 * A collection of plugins to hook LP.client into widgets.
 *
 * @module lp.client.plugins
 */

/**
 * This plugin overrides the widget _saveData method to update the
 * underlying model object using a PATCH call.
 *
 * @namespace lp.client.plugins
 * @class PATCHPlugin
 * @extends Widget
 */
function PATCHPlugin () {
    PATCHPlugin.superclass.constructor.apply(this, arguments);
}

Y.mix(PATCHPlugin, {
    /**
     * The identity of the plugin.
     *
     * @property PATCHPlugin.NAME
     * @type String
     * @static
     */
    NAME: 'PATCHPlugin',

    /**
     * The namespace of the plugin.
     *
     * @property PATCHPlugin.NS
     * @type String
     * @static
     */
    NS: 'patcher',

    /**
     * Static property used to define the default attribute configuration of
     * this plugin.
     *
     * @property PATCHPlugin.ATTRS
     * @type Object
     * @static
     */
    ATTRS : {
        /**
         * Name of the attribute to patch.
         *
         * @attribute patch
         * @type String
         */
        patch: {},

        /**
         * URL of the resource to PATCH.
         *
         * @attribute resource
         * @type String
         */
        resource: {},

        /**
         * Is this a patch for only a field,
         * not the entire resource object?
         *
         * @attribute patch_field
         * @type Boolean
         */
        patch_field: false,

        /**
         * The function to use to format the returned result into a form that
         * can be inserted into the page DOM.
         *
         * The default value is a function that simply returns the result
         * unmodified.
         *
         * @attribute formatter
         * @type Function
         * @default null
         */
        formatter: {
            valueFn: function() { return this._defaultFormatter; }
        }
}});

/**
 * Helper object for handling XHR failures.
 * clearProgressUI() and showError() need to be defined by the callsite
 * using this object.
 *
 * @class ErrorHandler
 */
LP.client.ErrorHandler = function () {

};
LP.client.ErrorHandler.prototype = {
    /**
     * Clear the progress indicator.
     *
     * The default implementation does nothing. Override this to provide
     * an implementation to remove the UI elements used to indicate
     * progress. After this method is called, the UI should be ready for
     * repeating the interaction, allowing the user to retry submitting
     * the data.
     *
     * @method clearProgressUI
     */
    clearProgressUI: function () {},

    /**
     * Show the error message to the user.
     *
     * The default implementation does nothing. Override this to provide
     * an implementation to display the UI elements containing the error
     * message.
     *
     * @method showError
     * @param error_msg The error text to display.
     */
    showError: function (error_msg) {},

    /**
     * Return a failure handler function for XHR requests.
     *
     * Assign the result of this function as the failure handler when
     * doing an XHR request using the API client.
     *
     * @method getFailureHandler
     */
    getFailureHandler: function () {
        var self = this;
        return function (ioId, o) {
            self.clearProgressUI();
            // If it was a timeout...
            if(o.status == 503) {
                self.showError(
                    'Timeout error, please try again in a few minutes.');
            // If it was a server error...
            } else if(o.status >= 500) {
                var server_error = 'Server error, please contact an administrator.';
                if(o.getResponseHeader('X-Lazr-OopsId')) {
                    server_error = server_error + ' OOPS ID:' + o.getResponseHeader('X-Lazr-OOPSid');
                }
                self.showError(server_error);
            // Otherwise we send some sane text as an error
            } else {
                self.showError(o.responseText);
            }
        };
    }
};


Y.extend(PATCHPlugin, Y.Plugin.Base, {

    /**
     * Configuration parameters that will be passed through to the LP.client
     * call.
     *
     * @property extra_config
     * @type Hash
     */
    extra_config: null,

    /**
     * Constructor code.  Check that the required config parameters are
     * present and wrap the host _saveData method.
     *
     * @method initializer
     * @protected
     */
    initializer: function(config) {
        if (!Y.Lang.isString(config.patch)) {
            Y.fail("missing config: 'patch' containing the attribute name");
        }

        if (!Y.Lang.isString(config.resource)) {
            Y.fail("missing config: 'resource' containing the URL to patch");
        }

        // Save the config object that the user passed in so that we can pass
        // any extra parameters through to the LP.client constructor.
        this.extra_config = config || {};

        // Save a reference to the original _saveData()
        //method before wrapping it.
        this.original_save = config.host._saveData;

        // We want to run our PATCH code instead of the original
        // 'save' method.  Using doBefore() means that
        // unplugging our code will leave the original
        // widget in a clean state.
        this.doBefore("_saveData", this.doPATCH);

        var self = this;
        this.error_handler = new LP.client.ErrorHandler();
        this.error_handler.clearProgressUI = function () {
            config.host._uiClearWaiting();
        };
        this.error_handler.showError = function (error_msg) {
            config.host.showError(error_msg);
        };
    },

    /**
     * Send a PATCH request with the widget's input value for the
     * configured attribute.
     *
     * It will set the widget in waiting status, do the PATCH.
     * Success will call the original widget save method.
     *
     * Errors are reported through the widget's showError() method.
     *
     * @method doPATCH
     */
    doPATCH: function() {
        var owner = this.get("host"),
            original_save = this.original_save;

        // Set the widget in 'waiting' state.
        owner._uiSetWaiting();

        var client =  new LP.client.Launchpad();
        var formatter = Y.bind(this.get('formatter'), this);
        var attribute = this.get('patch');

        var patch_payload;
        var val = owner.getInput();
        if (this.get('patch_field')) {
            patch_payload = val;
        } else {
            patch_payload = {};
            patch_payload[attribute] = val;
        }

        var callbacks = {
            on: {
                success: function (entry) {
                    owner._uiClearWaiting();
                    var new_value = formatter(entry, attribute);
                    original_save.apply(owner, [new_value]);
                },
                failure: this.error_handler.getFailureHandler()
            }
        };

        var cfg = Y.merge(callbacks, this.extra_config);

        client.patch(this.get('resource'), patch_payload, cfg);

        // Prevent the method we are hooking before from running.
        return new Y.Do.Halt();
    },

    /**
     * Return the webservice Entry object attribute that is to be shown in the
     * page DOM.
     *
     * This function may be overridden in various ways.
     *
     * @method _defaultFormatter
     * @protected
     * @param result {Entry|String} A Launchpad webservice Entry object, or
     * the unmodified result string if the default Content-Type wasn't used.
     * @param attribute {String} The resource attribute that the PATCH request
     * was sent to.
     * @return {String|Node} A string or Node instance to be inserted into
     * the DOM.
     */
    _defaultFormatter: function(result, attribute) {
        if (Y.Lang.isString(result)) {
            return result;
        } else {
            return result.get(attribute);
        }
    }
});

Y.namespace('lp.client.plugins');
Y.lp.client.plugins.PATCHPlugin = PATCHPlugin;

}, "0.1", {"requires": ["plugin", "dump", "lazr.editor"]});
