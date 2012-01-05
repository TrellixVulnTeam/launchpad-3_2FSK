/* Copyright 2009-2011 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * A milestone form overlay that can create a milestone within any page.
 *
 * @module Y.lp.registry.milestoneoverlay
 * @requires  dom, node, io-base, lp.anim, lazr.formoverlay
 */
YUI.add('lp.registry.milestoneoverlay', function(Y) {
    Y.log('loading lp.registry.milestoneoverlay');
    var module = Y.namespace('lp.registry.milestoneoverlay');

    var milestone_form;
    var milestone_form_uri;
    var series_uri;
    var next_step;
    var client_sync = false;

    var save_new_milestone = function(data) {

        var parameters = {
            name: data['field.name'][0].toLowerCase(),
            code_name: data['field.code_name'][0],
            summary: data['field.summary'][0]
        };

        var date_targeted = Y.Lang.trim(data['field.dateexpected'][0]);
        if (date_targeted !== '') {
            parameters.date_targeted = date_targeted;
        }

        var finish_new_milestone = function(ignore) {
            milestone_form.clearError();
            milestone_form.hide();
            // Reset the HTML form inside the widget.
            milestone_form.get('contentBox').one('form').reset();
            if (Y.Lang.isValue(next_step)) {
                next_step(parameters);
            }
        };

        var set_milestone_tags = function(milestone) {
            var tagstring = data['field.tags'][0].toLowerCase();
            var tags = Y.lp.bugs.bug_tags_entry.parse_tags(tagstring);

            if (tags.length === 0) {
                return finish_new_milestone();
            }

            var parameters = {
                tags: tags
            };
            milestone.named_post('setTags', {
                parameters: parameters,
                on: {
                    success: finish_new_milestone,
                    failure: function (ignore, response, args) {
                        var error_box = Y.one('#milestone-error');
                        var error_message = '<strong>' + response.statusText +
                                            '</strong><p>' +
                                            response.responseText +
                                            '</p>';
                        milestone_form.showError(error_message);
                    }
                }
            });
        };

        var client = new Y.lp.client.Launchpad({sync: client_sync});
        client.named_post(series_uri, 'newMilestone', {
            parameters: parameters,
            on: {
                success: set_milestone_tags,
                failure: function (ignore, response, args) {
                    var error_box = Y.one('#milestone-error');
                    var error_message = '<strong>' + response.statusText +
                                        '</strong><p>' +
                                        response.responseText +
                                        '</p>';
                    milestone_form.showError(error_message);
                }
            }
        });
    };
    module.save_new_milestone = save_new_milestone;

    var setup_milestone_form = function () {
        var form_submit_button = Y.Node.create(
            '<input type="submit" name="field.actions.register" ' +
            'id="formoverlay-add-milestone" value="Create Milestone"/>');
        milestone_form = new Y.lazr.FormOverlay({
            headerContent: '<h2>Create Milestone</h2>',
            form_submit_button: form_submit_button,
            centered: true,
            form_submit_callback: save_new_milestone,
            visible: false
        });
        milestone_form.render();
        milestone_form.loadFormContentAndRender(milestone_form_uri);
        Y.lp.app.calendar.add_calendar_widgets();
        milestone_form.show();
    };
    module.setup_milestone_form = setup_milestone_form;

    var show_milestone_form = function(e) {
        e.preventDefault();
        if (milestone_form) {
            milestone_form.show();
        } else {
            // This function call is asynchronous, so we can move
            // milestone_form.show() below it.
            setup_milestone_form();
        }
    };

    var configure = function(config) {
        if (config === undefined) {
            throw new Error(
                "Missing attach_widget config for milestoneoverlay.");
        }
        if (config.milestone_form_uri === undefined ||
            config.series_uri === undefined) {
            throw new Error(
                "attach_widget config for milestoneoverlay has " +
                "undefined properties.");
        }
        milestone_form_uri = config.milestone_form_uri;
        series_uri = config.series_uri;
        // For testing purposes next_step may be undefined.
        if (Y.Lang.isValue(config.next_step)) {
            next_step = config.next_step;
        }
        if (Y.Lang.isValue(config.sync)) {
            client_sync = config.sync;
        }
    };
    module.configure = configure;

    /**
      * Attaches a milestone form overlay widget to an element.
      *
      * @method attach_widget
      * @param {Object} config Object literal of config name/value pairs.
      *                        config.milestone_form_uri is the URI of the
      *                            milestone form to display.
      *                        config.series_uri is the URI to post the
      *                            form data to create the milestone.
      *                        activate_node is the node that shows the form
      *                            when it is clicked.
      *                        next_step is the function to be called after
      *                            the milestone is created.
      */
    module.attach_widget = function(config) {
        if (Y.UA.ie) {
            return;
        }
        configure(config);
        config.activate_node.on('click', show_milestone_form);
    };

}, "0.1", {"requires": ["dom",
                        "node",
                        "io-base",
                        "lp.anim",
                        "lazr.formoverlay",
                        "lp.app.calendar",
                        "lp.client",
                        "lp.bugs.bug_tags_entry"
                        ]});
