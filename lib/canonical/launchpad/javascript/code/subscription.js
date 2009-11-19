/*
   Copyright (c) 2009, Canonical Ltd. All rights reserved.

   This program is free software: you can redistribute it and/or modify
   it under the terms of the GNU Affero General Public License as published by
   the Free Software Foundation, either version 3 of the License, or
   (at your option) any later version.

   This program is distributed in the hope that it will be useful,
   but WITHOUT ANY WARRANTY; without even the implied warranty of
   MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
   GNU Affero General Public License for more details.

   You should have received a copy of the GNU Affero General Public License
   along with this program. If not, see <http://www.gnu.org/licenses/>.
*/

YUI.add('code.branch.subscription', function(Y) {

/*
 * Tools for working with branch subscriptions.
 *
 * @module lp.code.branch.subscription
 * @namespace lp.code.branch.subscription
 */

var namespace = Y.namespace('code.branch.subscription');

var display_name,   // The logged in user's displayname.
    user_name,      // The logged in user's username.
    me;             // The logged in user's url.

/*
 * Set up the name vars that are used by the widget.
 *
 * @param client {object} An LPClient instance
 */
var setUpNames = function (client) {
    me = LP.client.links.me;
    user_name = me.substring(2);

    // There is no need to set display_name if it exists.
    if (display_name !== undefined) {
        return;
    }

    var config = {
        on: {
            success: function(person) {
                display_name = person.lookup_value('display_name');
            }
        }
    };
    client.get(me, config);
};

/*
 * A widget for handling branch subscriptions.
 *
 * @attribute direct_subscribers {Y.Node} Wrapper div for the subscriber list.
 * @attribute self_subscribe {Y.Node} Container for "Subscribe" link.
 */
var SubscriptionWidget = function(config) {
    SubscriptionWidget.superclass.constructor.apply(this, arguments);
};

SubscriptionWidget.NAME = 'branch-subscription-widget';
SubscriptionWidget.ATTRS = {
    direct_subscribers: {},
    self_subscribe: {}
};
SubscriptionWidget.HTML_PARSER = {
    direct_subscribers: '.branch-subscribers-outer',
    self_subscribe: '.subscribe-self'
};

Y.extend(SubscriptionWidget, Y.Widget, {

    initializer: function () {

        this._lp_client = new LP.client.Launchpad();
        this._branch_repr = LP.client.cache.context;
        setUpNames(this._lp_client);

        var form_url = this.get("self_subscribe").get("href") + '/++form++';
        var lp_client = this._lp_client;
        var form_overlay = new Y.lazr.FormOverlay({
            headerContent: "<h2>Subscribe to branch</h2>",
            form_submit_button: Y.Node.create(
                '<button type="submit" name="field.actions.subscribe" ' +
                'value="Subscribe" class="lazr-pos lazr-btn">Ok</button>'),
            form_cancel_button: Y.Node.create(
                '<button type="button" name="field.actions.cancel" ' +
                'class="lazr-neg lazr-btn">Cancel</button>'),
            centered: true,
            form_submit_callback: function(data ) {

                form_overlay.hide();

                var img_src = '/@@/persongray';
                var html = [
                    '<div id="temp-username">',
                    '  <img src="' + img_src + '" alt="" width="14" ',
                    'height="14" /> ',
                    display_name,
                    '  <img id="temp-name-spinner" src="/@@/spinner" alt="" ',
                    '    style="position:absolute;right:8px" /></div>'
                    ].join('');
                var link_node = Y.Node.create(html);

                var subscribers = Y.get('.branch-subscribers');
                var next = subscribers.query('div')[0];
                if (next) {
                    subscribers.insertBefore(link_node, next);
                } else {
                    // Handle the case of the displayed "None".
                    var none_subscribers = Y.get('#none-subscribers');
                    if (none_subscribers) {
                        var none_parent = none_subscribers.get('parentNode');
                        none_parent.removeChild(none_subscribers);
                    }
                    subscribers.appendChild(link_node);
                }

                /* XXX: rockstar - bug=389188 - Select boxes don't pass the
                 * data across the way the API is expecting it to come.  This
                 * basically means that the data passed into this function is
                 * worthless in this situation.
                 */
                var notification_level = document.getElementById(
                    'field.notification_level');
                var notification_level_update = notification_level.options[
                    notification_level.selectedIndex].text;
                var max_diff_lines = document.getElementById(
                    'field.max_diff_lines');
                var max_diff_lines_update = max_diff_lines.options[
                    max_diff_lines.selectedIndex].text;
                var review_level = document.getElementById(
                    'field.review_level');
                var review_level_update = review_level.options[
                    review_level.selectedIndex].text;

                config = {
                    on: {
                        success: function(updated_entry) {
                            Y.fire('branch:subscriber-list-stale');
                        },
                        failure: function(id, response) {
                            Y.log(response.responseText);
                            subscription_form_overlay.show();
                        }
                    },
                    parameters: {
                        person: LP.client.get_absolute_uri(me),
                        notification_level: notification_level_update,
                        max_diff_lines: max_diff_lines_update,
                        code_review_level: review_level_update
                    }
                };

                lp_client.named_post(LP.client.cache.context.self_link,
                    'subscribe', config);
            },
            visible: false
        });
        // We want to keep the handle to the form_overlay around.
        this._form_overlay = form_overlay;

        // loadFormContentAndRender doesn't actually render.
        this._form_overlay.loadFormContentAndRender(form_url);
        this._form_overlay.render();

        this._updateSubscribersList = function() {
            Y.io('+branch-portlet-subscriber-content', {
                on: {
                    success: function(id, response) {
                        Y.get('#branch-subscribers-outer').set(
                            'innerHTML', response.responseText);
                        var anim = Y.lazr.anim.green_flash({
                            node: Y.get('#subscriber-' + user_name)
                        });
                        anim.run();
                    },
                    failure: function(id, response) {
                        Y.get('#subscriber-list').set(
                            'innerHTML', 'A problem has occurred.');
                    }
                }});
        };
    },
    renderUI: function () {},
    bindUI: function() {
        var form_overlay = this._form_overlay;
        this.get("self_subscribe").on('click', function(e) {
            // IE tables don't support innerHTML after render.
            if (Y.UA.ie) {
                return;
            }
            e.halt();
            form_overlay.show();
        });
        this.get("self_subscribe").addClass("js-action");

        Y.on(
            'branch:subscriber-list-stale',
            this._updateSubscribersList);
    },
    syncUI: function() {}
});
namespace.SubscriptionWidget = SubscriptionWidget;

}, '0.1', {'requires': [
    'event',
    'io',
    'lazr.formoverlay',
    'node',
    'dump'
    ]});
