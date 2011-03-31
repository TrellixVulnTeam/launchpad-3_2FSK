YUI.add('lp.app.picker', function(Y) {

var namespace = Y.namespace('lp.app.picker');

var BATCH_SIZE = 6;
var MAX_BATCHES = 20;

/* Add a picker widget which will PATCH a given attribute on
 * a given resource.
 *
 * @method addPickerPatcher
 * @param {String} vocabulary Name of the vocabulary to query.
 * @param {String} resource_uri The object being modified.
 * @param {String} attribute_name The attribute on the resource being
 *                                modified.
 * @param {String} content_box_id
 * @param {Object} config Object literal of config name/value pairs.
 *     config.header: a line of text at the top of the widget.
 *     config.step_title: overrides the subtitle.
 *     config.remove_button_text: Override the default 'Remove' text.
 *     config.null_display_value: Override the default 'None' text.
 *     config.show_remove_button: Should the remove button be shown?
 *         Defaults to false, should be a boolean.
 *     config.show_assign_me_botton: Should the 'assign me' button be shown?
 *         Defaults to false, should be a boolean.
 *     config.show_search_box: Should the search box be shown.
 *         Vocabularies that are not huge should not have a search box.
 */
namespace.addPickerPatcher = function (
    vocabulary, resource_uri, attribute_name,
    content_box_id, config) {

    if (Y.UA.ie) {
        return;
    }

    var show_remove_button = false;
    var show_assign_me_button = false;
    var remove_button_text = 'Remove';
    var null_display_value = 'None';
    var show_search_box = true;
    resource_uri = Y.lp.client.normalize_uri(resource_uri)

    if (config !== undefined) {
        if (config.remove_button_text !== undefined) {
            remove_button_text = config.remove_button_text;
        }

        if (config.null_display_value !== undefined) {
            null_display_value = config.null_display_value;
        }

        if (config.show_remove_button !== undefined) {
            show_remove_button = config.show_remove_button;
        }

        if (config.show_assign_me_button !== undefined) {
            show_assign_me_button = config.show_assign_me_button;
        }

        if (config.show_search_box !== undefined) {
            show_search_box = config.show_search_box;
        }
    }

    var content_box = Y.one('#' + content_box_id);

    var activator = new Y.lazr.activator.Activator(
        {contentBox: content_box});

    var failure_handler = function (xid, response, args) {
        activator.renderFailure(
            Y.Node.create(
                '<div>' + response.statusText +
                    '<pre>' + response.responseText + '</pre>' +
                '</div>'));
    };

    var show_hide_buttons = function () {
        var link = content_box.one('.yui3-activator-data-box a');
        if (remove_button) {
            if (link === null || !show_remove_button) {
                remove_button.addClass('yui-picker-hidden');
            } else {
                remove_button.removeClass('yui-picker-hidden');
            }
        }

        if (assign_me_button) {
            if (link !== null
                && link.get('href').indexOf(LP.links.me + '/') != -1) {
                assign_me_button.addClass('yui-picker-hidden');
            } else {
                assign_me_button.removeClass('yui-picker-hidden');
            }
        }
    };

    var save = function (picker_result) {
        activator.renderProcessing();
        var success_handler = function (entry) {
          activator.renderSuccess(entry.getHTML(attribute_name));
          show_hide_buttons();
          return;
        };

        var patch_payload = {};
        patch_payload[attribute_name] = Y.lp.client.get_absolute_uri(
            picker_result.api_uri);

        var client = new Y.lp.client.Launchpad();
        client.patch(picker._resource_uri, patch_payload, {
            accept: 'application/json;include=lp_html',
            on: {
                success: success_handler,
                failure: failure_handler
            }
        });
    };

    var assign_me = function () {
        picker.hide();
        save({
            image: '/@@/person',
            title: 'Me',
            api_uri: LP.links.me
        });
    };

    var remove = function () {
        picker.hide();
        activator.renderProcessing();
        var success_handler = function (entry) {
            activator.renderSuccess(Y.Node.create(null_display_value));
            show_hide_buttons();
        };

        var patch_payload = {};
        patch_payload[attribute_name] = null;

        var client = new Y.lp.client.Launchpad();
        // Use picker._resource_uri, since it might have been changed
        // from the outside after the widget has already been initialized.
        client.patch(picker._resource_uri, patch_payload, {
            accept: 'application/json;include=lp_html',
            on: {
                success: success_handler,
                failure: failure_handler
            }
        });
    };

    config.save = save;
    var picker = namespace.create(vocabulary, config);
    picker._resource_uri = resource_uri;
    var extra_buttons = Y.Node.create(
        '<div style="text-align: center; height: 3em; ' +
        'white-space: nowrap"/>');
    var remove_button, assign_me_button;
    if (show_remove_button) {
        remove_button = Y.Node.create(
            '<a class="yui-picker-remove-button bg-image" ' +
            'href="javascript:void(0)" ' +
            'style="background-image: url(/@@/remove); padding-right: 1em">' +
            remove_button_text + '</a>');
        remove_button.on('click', remove);
        extra_buttons.appendChild(remove_button);
    }
    if (show_assign_me_button) {
        assign_me_button = Y.Node.create(
            '<a class="yui-picker-assign-me-button bg-image" ' +
            'href="javascript:void(0)" ' +
            'style="background-image: url(/@@/person)">' +
            'Assign Me</a>');
        assign_me_button.on('click', assign_me);
        extra_buttons.appendChild(assign_me_button);
    }
    picker.set('footer_slot', extra_buttons);

    // If we are to pre-load the vocab, we need a spinner.
    // We set it up here because we only want to do it once and the
    // activator.subscribe callback below is called each time the picker
    // is activated.
    if( !show_search_box ) {
        // The spinner displays a "Loading..." message while vocab loads.
        config.temp_spinner = create_temporary_spinner(picker);
    }

    activator.subscribe('act', function (e) {
        if (!show_search_box) {
          config.temp_spinner.removeClass('unseen');
          picker.set('min_search_chars', 0);
          picker.fire('search', '');
          picker.get('contentBox').one('.yui3-picker-search-box').addClass('unseen');
        }
        picker.show();
    });
    activator.render();

    show_hide_buttons();

    return picker;
};

/*
 * Show the Loading.... spinner (used when we preload the entire vocab).
 */
function create_temporary_spinner(picker) {
    var node = picker.get('contentBox').one('.yui3-picker-batches');
    var temp_spinner = Y.Node.create([
    '<div class="unseen" align="center">',
    '<img src="/@@/spinner"/>Loading...',
    '</div>'].join(''));
    node.insert(temp_spinner, node);
    return temp_spinner;
}

/*
 * Remove the Loading.... spinner (if it exists).
 */
function hide_temporary_spinner(temp_spinner) {
    if( temp_spinner != null )
        temp_spinner.addClass('unseen');
}

/**
  * Creates a picker widget that has already been rendered and hidden.
  *
  * @requires dom, dump, lazr.overlay, lazr.picker
  * @method create
  * @param {String} vocabulary Name of the vocabulary to query.
  * @param {Object} config Optional Object literal of config name/value pairs.
  *                        config.header is a line of text at the top of
  *                        the widget.
  *                        config.step_title overrides the subtitle.
  *                        config.save is a Function (optional) which takes
  *                        a single string argument.
  */
namespace.create = function (vocabulary, config) {
    if (Y.UA.ie) {
        return;
    }

    if (config !== undefined) {
        var header = 'Choose an item.';
        if (config.header !== undefined) {
            header = config.header;
        }

        var step_title = "Enter search terms";
        if (config.step_title !== undefined) {
            step_title = config.step_title;
        }
    }

    if (typeof vocabulary != 'string') {
        throw new TypeError(
            "vocabulary argument for Y.lp.picker.create() must be a " +
            "string: " + vocabulary);
    }

    var new_config = Y.merge(config, {
        align: {
            points: [Y.WidgetPositionAlign.CC,
                     Y.WidgetPositionAlign.CC]
        },
        progressbar: true,
        progress: 100,
        headerContent: "<h2>" + header + "</h2>",
        steptitle: step_title,
        zIndex: 1000,
        visible: false
        });
    var picker = new Y.lazr.Picker(new_config);

    picker.subscribe('save', function (e) {
        Y.log('Got save event.');
        if (Y.Lang.isFunction(config.save)) {
            config.save(e.details[Y.lazr.Picker.SAVE_RESULT]);
        }
    });

    picker.subscribe('cancel', function (e) {
        Y.log('Got cancel event.');
    });

    // Search for results, create batches and update the display.
    // in the widget.
    var search_handler = function (e) {
        Y.log('Got search event:' + Y.dump(e.details));
        var search_text = e.details[0];
        var selected_batch = e.details[1] || 0;
        var start = BATCH_SIZE * selected_batch;
        var client = new Y.lp.client.Launchpad();

        var success_handler = function (ignore, response, args) {
            var entry = Y.JSON.parse(response.responseText);
            var total_size = entry.total_size;
            var start = entry.start;
            var results = entry.entries;

            hide_temporary_spinner(config.temp_spinner);
            if (total_size > (MAX_BATCHES * BATCH_SIZE))  {
                picker.set('error',
                    'Too many matches. Please try to narrow your search.');
                // Display a single empty result item so that the picker
                // doesn't say that no items matched, which is contradictory.
                picker.set('results', [{}]);
                picker.set('batches', []);
            } else {
                picker.set('results', results);

                // Update the batches only if it's a new search.
                if (e.details[1] === undefined) {
                    var batches = [];
                    var stop = Math.ceil(total_size / BATCH_SIZE);
                    if (stop > 1) {
                        for (var i=0; i<stop; i++) {
                            batches.push({
                                    name: i+1,
                                    value: i
                                });
                        }
                    }

                    picker.set('batches', batches);
                }
            }
        };

        var qs = '';
        qs = Y.lp.client.append_qs(qs, 'name', vocabulary);
        qs = Y.lp.client.append_qs(qs, 'search_text', search_text);
        qs = Y.lp.client.append_qs(qs, 'batch', BATCH_SIZE);
        qs = Y.lp.client.append_qs(qs, 'start', start);

        // The uri needs to be relative, so that the vocabulary
        // has the same context as the form. Some vocabularies
        // use the context to limit the results to the same project.
        var uri = '@@+huge-vocabulary?' + qs;

        Y.io(uri, {
            headers: {'Accept': 'application/json'},
            timeout: 20000,
            on: {
                success: success_handler,
                failure: function (arg) {
                    hide_temporary_spinner(config.temp_spinner);
                    picker.set('error', 'Loading results failed.');
                    picker.set('search_mode', false);
                    Y.log("Loading " + uri + " failed.");
                }
            }
        });
    };

    picker.after('search', search_handler);

    picker.render();
    picker.hide();
    return picker;
};

}, "0.1", {"requires": [
    "io", "dom", "dump", "lazr.picker", "lazr.activator", "json-parse",
    "lp.client"
    ]});
