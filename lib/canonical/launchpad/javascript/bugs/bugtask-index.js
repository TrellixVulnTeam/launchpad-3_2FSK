/* Copyright 2009 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Form overlay widgets and subscriber handling for bug pages.
 *
 * @module BugtaskIndex
 * @requires base, node, lazr.formoverlay, lazr.anim
 */

YUI.add('bugs.bugtask_index', function(Y) {

var bugs = Y.namespace('bugs');

// lazr.FormOverlay objects.
var duplicate_form_overlay;
var privacy_form_overlay;

// The url of the page used to update bug duplicates.
var update_dupe_url;

// The launchpad js client used.
var lp_client;

// The launchpad client entry for the current bug.
var lp_bug_entry;

// The bug itself, taken from cache.
var bug_repr;

// Overlay related vars.
var error_overlay;
var form_load_callbacks = {};
var submit_button_html =
    '<button type="submit" name="field.actions.change" ' +
    'value="Change" class="lazr-pos lazr-btn" >OK</button>';
var cancel_button_html =
    '<button type="button" name="field.actions.cancel" ' +
    'class="lazr-neg lazr-btn" >Cancel</button>';
var privacy_link;
var privacy_spinner;

/*
 * An object representing the bugtask subscribers portlet.
 *
 * Since the portlet loads via XHR and inline subscribing
 * depends on that portlet being loaded, setup a custom
 * event object, to provide a hook for initializing subscription
 * link callbacks after a bugs:portletloaded event.
 *
 * XXX deryck 2009-04-30 bug=369874 Now this object exists,
 * the inline js on bug-portlet-subscribers.pt should be moved here.
*/
var PortletTarget = function() {};
Y.augment(PortletTarget, Y.Event.Target);
Y.bugs.portlet = new PortletTarget();
Y.bugs.portlet.subscribe('bugs:portletloaded', function() {
    setup_subscription_link_handlers();
});
/*
 * If the subscribers portlet fails to load, clear any
 * click handlers, so the normal subscribe page can be reached.
 */
Y.bugs.portlet.subscribe('bugs:portletloadfailed', function(handlers) {
    if (Y.Lang.isArray(handlers)) {
        var click_handler = handlers[0];
        click_handler.detach();
    }
});

/*
 * Subscribing someone else requires loading a grayed out
 * username into the DOM until the subscribe action completes.
 * There are a couple XHR requests in check_can_be_unsubscribed
 * before the subscribe work can be done, so fire a custom event
 * bugs:nameloaded and do the work here when the event fires.
 */
Y.bugs.portlet.subscribe('bugs:nameloaded', function(subscription) {
    var error_handler = new LP.client.ErrorHandler();
    error_handler.clearProgressUI = function() {
        var temp_link = Y.get('#temp-username');
        if (temp_link) {
            var temp_parent = temp_link.get('parentNode');
            temp_parent.removeChild(temp_link);
        }
    };
    error_handler.showError = function(error_msg) {
        display_error(Y.get('.menu-link-addsubscriber'), error_msg);
    };

    var config = {
        on: {
            success: function() {
                var temp_link = Y.get('#temp-username');
                var temp_spinner = Y.get('#temp-name-spinner');
                temp_link.removeChild(temp_spinner);
                var anim = Y.lazr.anim.green_flash({ node: temp_link });
                anim.on('end', function() {
                    add_user_name_link(subscription);
                    var temp_parent = temp_link.get('parentNode');
                    temp_parent.removeChild(temp_link);
                });
                anim.run();
            },
            failure: error_handler.getFailureHandler()
        },
        parameters: {
            person: LP.client.get_absolute_uri(
                subscription.get('person').get('escaped_uri'))
        }
    };
    lp_client.named_post(bug_repr.self_link, 'subscribe', config);
});

Y.bugs.setup_bugtask_index = function() {
    /*
     * Check the page for links related to overlay forms and request the HTML
     * for these forms.
     */
    Y.on('load', function() {
        if (Y.UA.ie) {
            return;
        }
        // If the user is not logged in, then we need to defer to the
        // default behaviour.
        if (LP.client.links.me === undefined) {
            return;
        }

        if (lp_client === undefined || bug_repr === undefined) {
            setup_client_and_bug();
        }

        Y.on('io:complete', function(id, response_object) {
            form_load_callbacks[id](response_object.responseText);
        }, this);

        // First look for 'Mark as duplicate' links.
        var update_dupe_links = Y.all('.menu-link-mark-dupe');

        // If there are none, check for any 'change duplicate bug' links.
        if (!update_dupe_links){
            update_dupe_links = Y.all('#change_duplicate_bug');
        }

        if (update_dupe_links) {
            // First things first, pre-load the mark-dupe form.
            update_dupe_url = update_dupe_links.item(0).getAttribute('href');
            var mark_dupe_form_url = update_dupe_url + '/++form++';
            var dupe_form_id = Y.io(mark_dupe_form_url);
            form_load_callbacks[dupe_form_id.id] = createBugDuplicateFormOverlay;

            // Add an on-click handler to any links found that displays
            // the form overlay.
            update_dupe_links.on('click', function(e){
                // Only go ahead if we have received the form content by the
                // time the user clicks:
                if (duplicate_form_overlay){
                    e.preventDefault();
                    duplicate_form_overlay.show();
                }
            });
            // Add a class denoting them as js-action links.
            update_dupe_links.addClass('js-action');
        }

        privacy_link = Y.get('#privacy-link');

        if (privacy_link) {
            var privacy_link_url = privacy_link.getAttribute('href') + '/++form++';
            var privacy_div = Y.get('#privacy-text');
            var privacy_html = privacy_link.get('innerHTML') + ' ';
            privacy_div.set('innerHTML', privacy_html);
            var privacy_text = Y.get('#privacy-text');
            privacy_link = Y.Node.create(
                '<a id="privacy-link" class="sprite edit" title="[edit]">' +
                '<span class="invisible-link">edit</span></a>');
            privacy_link.set('href', privacy_link_url);
            privacy_text.appendChild(privacy_link);
            privacy_spinner = Y.Node.create(
                '<img src="/@@/spinner" style="display: none" />');
            privacy_text.appendChild(privacy_spinner);
            var privacy_form_id = Y.io(privacy_link_url);
            form_load_callbacks[privacy_form_id.id] = create_privacy_form_overlay;
            privacy_link.on('click', function(e) {
                if (privacy_form_overlay) {
                    e.preventDefault();
                    privacy_form_overlay.show();
                    // XXX Abel Deuring 2009-04-23, bug 365462
                    // Y.get('#field.private') returns null.
                    // Seems that YUI does not like IDs containing a '.'
                    document.getElementById('field.private').focus();
                }
            });
            privacy_link.addClass('js-action');
        }
    }, window);
};

/*
 * Clear the subscribe someone else picker.
 *
 * @method clear_picker
 * @param e {Object} The event object.
 */
function clear_picker(e) {
    var input = Y.get('.yui-picker-search-box input');
    input.set('value', '');
    this.set('error', '');
    this.set('results', [{}]);
    this._results_box.set('innerHTML', '');
    this.set('batches', []);
}

/*
 * Initialize click handler for the subscribe someone else link.
 *
 * @method setup_subscribe_someone_else_handler
 * @param subscription {Object} A Y.lp.Subscription object.
 */
function setup_subscribe_someone_else_handler(subscription) {
    var config = {
        header: 'Subscribe someone else',
        step_title: 'Search'
    };

    var picker = Y.lp.picker.create(
        'ValidPersonOrTeam',
        function(result) { subscribe_someone_else(result, subscription); },
        config);
    // Clear results and search terms on cancel or save.
    picker.on('save', clear_picker, picker);
    picker.on('cancel', clear_picker, picker);

    var subscription_link_someone_else = Y.get('.menu-link-addsubscriber');
    subscription_link_someone_else.on('click', function(e) {
        e.halt();
        picker.show();
    });
    subscription_link_someone_else.addClass('js-action');
}

/*
 * Initialize callbacks for subscribe/unsubscribe links.
 *
 * @method setup_subscription_link_handlers
 */
function setup_subscription_link_handlers() {
    if (LP.client.links.me === undefined) {
        return;
    }

    if (lp_client === undefined || bug_repr === undefined) {
        setup_client_and_bug();
    }

    var subscription = new Y.lp.Subscription({
        link: Y.get('.menu-link-subscription'),
        spinner: Y.get('#sub-unsub-spinner'),
        subscriber: new Y.lp.Subscriber({uri: LP.client.links.me})
    });

    var is_direct = subscription.get(
        'link').get('parentNode').hasClass('subscribed-true');
    var has_dupes = subscription.get(
        'link').get('parentNode').hasClass('dup-subscribed-true');
    subscription.set('is_direct', is_direct);
    subscription.set('has_dupes', has_dupes);

    if (subscription.is_node()) {
        subscription.get('link').on('click', function(e) {
            e.halt();
            subscription.set('can_be_unsubscribed', true);
            subscription.set('person', subscription.get('subscriber'));
            var parent = e.target.get('parentNode');
            // Look for the false conditions of subscription, which
            // is_direct_subscription, etc. don't report correctly,
            // to make sure we only use subscribe_current_user for
            // the current user.
            if (parent.hasClass('subscribed-false') &&
                parent.hasClass('dup-subscribed-false')) {
                subscribe_current_user(subscription);
            }
            else {
                unsubscribe_current_user(subscription);
            }
        });
        subscription.get('link').addClass('js-action');
    }

    setup_unsubscribe_icon_handlers(subscription);
    setup_subscribe_someone_else_handler(subscription);
    create_error_overlay();
}

/*
 * Set click handlers for unsubscribe remove icons.
 *
 * @method setup_unsubscribe_icon_handlers
 * @param subscription {Object} A Y.lp.Subscription object.
 */
function setup_unsubscribe_icon_handlers(subscription) {
    var unsubscribe_icons = Y.all('.unsub-icon');
    if (unsubscribe_icons) {
        unsubscribe_icons.on('click', function(e) {
            e.halt();
            unsubscribe_user_via_icon(e.target, subscription);
        });
    }
}

/*
 * Create the lp client and bug entry if we haven't done so already.
 *
 * @method setup_client_and_bug
 */
function setup_client_and_bug() {
    lp_client = new LP.client.Launchpad();

    if (bug_repr === undefined) {
        bug_repr = LP.client.cache.bug;
        lp_bug_entry = new LP.client.Entry(
            lp_client, bug_repr, bug_repr.self_link);
    }
}

/*
 * Creates the duplicate form overlay using the passed form content.
 *
 * @method createBugDuplicateFormOverlay
 */
function createBugDuplicateFormOverlay(form_content) {
    duplicate_form_overlay = new Y.lazr.FormOverlay({
        headerContent: '<h2>Mark bug report as duplicate</h2>',
        form_header: 'Marking the bug as a duplicate will, by default, ' +
                     'hide it from search results listings.',
        form_content: form_content,
        form_submit_button: Y.Node.create(submit_button_html),
        form_cancel_button: Y.Node.create(cancel_button_html),
        centered: true,
        form_submit_callback: update_bug_duplicate,
        visible: false
    });
    duplicate_form_overlay.render('#duplicate-form-container');
}

/*
 * Update the bug duplicate via the LP API
 */
function update_bug_duplicate(data) {
    // XXX noodles 2009-03-17 bug=336866 It seems the etag
    // returned by lp_save() is incorrect. Remove it for now
    // so that the second save does not result in a '412
    // precondition failed' error.
    //
    // XXX deryck 2009-04-29 bug=369293 Also, this has to
    // happen before *any* call to lp_save now that bug
    // subscribing can be done inline.  Named operations
    // don't return new objects, making the cached bug's
    // etag invalid as well.
    lp_bug_entry.removeAtt('http_etag');

    // Hide the formoverlay:
    duplicate_form_overlay.hide();

    // Add the spinner...
    var dupe_span = Y.get('#mark-duplicate-text');
    dupe_span.addClass('update-in-progress-message');

    // Set the new duplicate link on the bug entry.
    var new_dup_url = null;
    var new_dup_id = data['field.duplicateof'][0];
    if (new_dup_id !== '') {
        var self_link = lp_bug_entry.get('self_link');
        var last_slash_index = self_link.lastIndexOf('/');
        new_dup_url = self_link.slice(0, last_slash_index+1) + new_dup_id;
    }
    var old_dup_url = lp_bug_entry.get('duplicate_of_link');
    lp_bug_entry.set('duplicate_of_link', new_dup_url);

    // Create a config for the lp_save method
    config = {
        on: {
            success: function(updated_entry) {
                dupe_span.removeClass('update-in-progress-message');
                lp_bug_entry = updated_entry;

                if (new_dup_url !== null) {
                    dupe_span.set('innerHTML', [
                        'Duplicate of <a>bug #</a> ',
                        '<a class="menu-link-mark-dupe js-action sprite edit">',
                        '<span class="invisible-link">edit</span></a>'].join(""));
                    dupe_span.queryAll('a').item(0)
                        .set('href', '/bugs/' + new_dup_id)
                        .appendChild(document.createTextNode(new_dup_id));
                    dupe_span.queryAll('a').item(1)
                        .set('href', update_dupe_url);
                    show_comment_on_duplicate_warning();
                } else {
                    dupe_span.set('innerHTML', [
                        '<a class="menu-link-mark-dupe js-action ',
                        'sprite bug-dupe">Mark as duplicate</a>'].join(""));
                    dupe_span.query('a').set('href', update_dupe_url);
                    hide_comment_on_duplicate_warning();
                }
                Y.lazr.anim.green_flash({node: dupe_span}).run();
                // ensure the new link is hooked up correctly:
                dupe_span.query('a.menu-link-mark-dupe').on(
                    'click', function(e){
                        e.preventDefault();
                        duplicate_form_overlay.show();
                    });
            },
            failure: function(id, request) {
                dupe_span.removeClass('update-in-progress-message');
                if (request.status == 400) {
                    duplicate_form_overlay.showError(
                        new_dup_id + ' is not a valid bug number or' +
                        ' nickname.');
                } else {
                    duplicate_form_overlay.showError(request.responseText);
                }
                duplicate_form_overlay.show();

                // Reset the lp_bug_entry.duplicate_of_link as it wasn't
                // updated.
                lp_bug_entry.set('duplicate_of_link', old_dup_url);

            }
        }
    };

    // And save the updated entry.
    lp_bug_entry.lp_save(config);
}

/*
 * Ensure that a warning about adding a comment to a duplicate bug
 * is displayed.
 *
 * @method show_comment_on_duplicate_warning
 */
var show_comment_on_duplicate_warning = function() {
    var duplicate_warning = Y.get('#warning-comment-on-duplicate');
    if (duplicate_warning === null) {
        var container = Y.get('#new-comment');
        var first_node = container.get('firstChild');
        duplicate_warning = Y.Node.create(
            ['<div class="warning message" id="warning-comment-on-duplicate">',
             'Remember, this bug report is a duplicate. ',
             'Comment here only if you think the duplicate status is wrong.',
             '</div>'].join(''));
        container.insertBefore(duplicate_warning, first_node);
    }
};

/*
 * Ensure that no warning about adding a comment to a duplicate bug
 * is displayed.
 *
 * @method hide_comment_on_duplicate_warning
 */
var hide_comment_on_duplicate_warning = function() {
    var duplicate_warning = Y.get('#warning-comment-on-duplicate');
    if (duplicate_warning !== null) {
        duplicate_warning.ancestor().removeChild(duplicate_warning);
    }
};


/*
 * Create the privacy settings form overlay.
 *
 * @method create_privacy_form_overlay
 * @param form_content {String} The HTML data of the form overlay.
 */
var create_privacy_form_overlay = function(form_content) {
    privacy_form_overlay = new Y.lazr.FormOverlay({
        headerContent: '<h2>Change privacy settings</h2>',
        form_header: '',
        form_content: form_content,
        form_submit_button: Y.Node.create(submit_button_html),
        form_cancel_button: Y.Node.create(cancel_button_html),
        centered: true,
        form_submit_callback: update_privacy_settings,
        visible: false
    });
    privacy_form_overlay.render('#privacy-form-container');
    var node = Y.get('#form-container');
};

var update_privacy_settings = function(data) {
    // XXX noodles 2009-03-17 bug=336866 It seems the etag
    // returned by lp_save() is incorrect. Remove it for now
    // so that the second save does not result in a '412
    // precondition failed' error.
    //
    // XXX deryck 2009-04-29 bug=369293 Also, this has to
    // happen before *any* call to lp_save now that bug
    // subscribing can be done inline.  Named operations
    // don't return new objects, making the cached bug's
    // etag invalid as well.
    lp_bug_entry.removeAtt('http_etag');

    privacy_form_overlay.hide();

    var privacy_text = Y.get('#privacy-text');
    var privacy_div = Y.get('#privacy');
    privacy_link.setStyle('display', 'none');
    privacy_spinner.setStyle('display', 'inline');

    if (lp_client === undefined) {
        lp_client = new LP.client.Launchpad();
    }

    if (lp_bug_entry === undefined) {
        var bug_repr = LP.client.cache.bug;
        lp_bug_entry = new LP.client.Entry(
            lp_client, bug_repr, bug_repr.self_link);
    }

    var private = data['field.private'] !== undefined;
    var security_related =
        data['field.security_related'] !== undefined;

    lp_bug_entry.set('private', private);
    lp_bug_entry.set('security_related', security_related);
    var error_handler = new LP.client.ErrorHandler();
    error_handler.clearProgressUI = function () {
        privacy_spinner.setStyle('display', 'none');
        privacy_link.setStyle('display', 'inline');
    };
    error_handler.showError = function (error_msg) {
        Y.lazr.anim.red_flash({node: privacy_div}).run();
        privacy_form_overlay.showError(error_msg);
        privacy_form_overlay.show();
    };

    var config = {
        on: {
            success: function (updated_entry) {
                privacy_spinner.setStyle('display', 'none');
                privacy_link.setStyle('display', 'inline');
                lp_bug_entry = updated_entry;

                if (private) {
                    privacy_div.removeClass('public');
                    privacy_div.addClass('private');
                    privacy_text.set(
                        'innerHTML',
                        'This report is <strong>private</strong> ');
                } else {
                    privacy_div.removeClass('private');
                    privacy_div.addClass('public');
                    privacy_text.set(
                        'innerHTML', 'This report is public ');
                }
                privacy_text.appendChild(privacy_link);
                privacy_text.appendChild(privacy_spinner);

                var security_message = Y.get('#security-message');
                if (security_related) {
                    if (security_message === null) {
                        var security_message_html = [
                            '<div style="',
                            '    margin-top: 0.5em;',
                            '    padding-right: 18px;',
                            '    center right no-repeat;"',
                            '    class="sprite security"',
                            '    id="security-message"',
                            '>Security vulnerability</div>'
                        ].join('');
                        security_message = Y.Node.create(security_message_html);
                        privacy_div.appendChild(security_message);
                    }
                } else {
                    if (security_message !== null) {
                        privacy_div.removeChild(security_message);
                    }
                }
                Y.lazr.anim.green_flash({node: privacy_div}).run();
            },
            failure: error_handler.getFailureHandler()
        }
    };
    lp_bug_entry.lp_save(config);
};

/*
 * Create the form overlay to use when encountering errors.
 *
 * @method create_error_overlay
*/
function create_error_overlay() {
    if (error_overlay === undefined) {
        error_overlay = new Y.lazr.FormOverlay({
            headerContent: '<h2>Error</h2>',
            form_content:  '',
            form_submit_button: Y.Node.create(
                '<button style="display:none"></button>'),
            form_cancel_button: cancel_form_button(),
            centered: true,
            visible: false
        });
        error_overlay.render();
    }
}

/*
 * Create a form button for canceling an error form
 * that won't reload the page on submit.
 *
 * @method cancel_form_button
 * @return button {Node} The form's cancel button.
*/
function cancel_form_button() {
    var button = Y.Node.create('<button>OK</button>');
    button.on('click', function(e) {
        e.preventDefault();
        error_overlay.hide();
    });
    return button;
}

/*
 * Take an error message and display in an overlay (creating it if necessary).
 *
 * @method display_error
 * @param flash_node {Node} The node to red flash.
 * @param msg {String} The message to display.
*/
function display_error(flash_node, msg) {
    create_error_overlay();
    if (flash_node) {
        var anim = Y.lazr.anim.red_flash({ node: flash_node });
        anim.on('end', function(e) {
            error_overlay.showError(msg);
            error_overlay.show();
        });
        anim.run();
    } else {
        error_overlay.showError(msg);
        error_overlay.show();
    }
}

/*
 * Traverse the DOM of a given remove icon to find
 * the user's link.  Returns a URI of the form "/~username".
 *
 * @method get_user_uri_from_icon
 * @param icon {Node} The node representing a remove icon.
 * @return user_uri {String} The user's uri, without the hostname.
 */
function get_user_uri_from_icon(icon) {
    var parent_div = icon.get('parentNode').get('parentNode');
    // This should be parent_div.firstChild, but because of #text
    // and cross-browser issues, using the YUI query syntax is
    // safer here.
    var user_uri = parent_div.query('a').getAttribute('href');
    return user_uri;
}

/*
 * Build the HTML for a user link for the subscribers list.
 *
 * @method build_user_link_html
 * @param subscription {Object} A Y.lp.Subscription object.
 * @return html {String} The HTML used for creating a subscriber link.
 */
function build_user_link_html(subscription) {
    var name = subscription.get('person').get('name');
    var full_name = subscription.get('person').get('full_display_name');
    // Be paranoid about display_name, since timeouts or other errors
    // could mean display_name wasn't set on initialization.
    if (subscription.get('person').get('display_name') === '') {
        subscription.get('person').set_display_name();
    }
    var display_name = subscription.get('person').get('display_name');
    var terms = {
        name: name,
        display_name: display_name,
        full_name: full_name
    };

    if (subscription.is_current_user_subscribing()) {
        terms.subscribed_by = 'themselves';
    } else {
        terms.subscribed_by = 'by ' + full_name;
    }

    var html = Y.Node.create('<div><a></a></div>');
    html.addClass('subscriber-' + terms.name);

    html.query('a')
        .set('href', '/~' + terms.name)
        .set('name', terms.full_name)
        .set('title', 'Subscribed ' + terms.subscribed_by);

    var span;
    if (subscription.is_team()) {
        span = '<span class="sprite team"></span>';
    } else {
        span = '<span class="sprite person"></span>';
    }

    html.query('a')
        .appendChild(Y.Node.create(span))
        .appendChild(document.createTextNode(terms.display_name));

    // Add remove icon if the current user can unsubscribe the subscriber.
    if (subscription.can_be_unsubscribed_by_user()) {
        var icon_html = Y.Node.create(
            '<a href="+subscribe">' +
            '<img class="unsub-icon" src="/@@/remove" /></a>');
        icon_html
            .set('id', 'unsubscribe-' + terms.name)
            .set('title', 'Unsubscribe ' + terms.full_name);
        icon_html.query('img')
            .set('id', 'unsubscribe-icon-' + terms.name);
        html.appendChild(icon_html);
    }

    return html;
}

/*
 * Used to remove the user's name from the subscriber's list.
 *
 * @method remove_user_name_link
 * @param user_node {Node} Node representing the user name link.
 */
function remove_user_name_link(user_node) {
    var parent = user_node.get('parentNode');
    parent.removeChild(user_node);
}

/*
 * Returns the next node in alphabetical order after the subscriber
 * node now being added.  No node is returned to append to end of list.
 *
 * The name can appear in one of two different lists. 1) The list of
 * subscribers that can be unsubscribed by the current user, and
 * 2) the list of subscribers that cannont be unsubscribed.
 *
 * @method get_next_subscriber_node
 * @param subscription_link {Node} The sub/unsub link.
 * @return {Node} The node appearing next in the subscriber list or
 *          undefined if no node is next.
 */
function get_next_subscriber_node(subscription) {
    var full_name = subscription.get('person').get('full_display_name');
    var can_be_unsubscribed = subscription.can_be_unsubscribed_by_user();
    var nodes_by_name = {};
    var unsubscribables = [];
    var not_unsubscribables = [];

    // Use the list of subscribers pulled from the DOM to have sortable
    // lists of unsubscribable vs. not unsubscribale person links.
    var subscribers = Y.get('#subscribers-links');
    var all_subscribers = subscribers.queryAll('div');
    if (Y.Lang.isValue(all_subscribers)) {
        all_subscribers.each(function(sub_link) {
            if (sub_link.getAttribute('id') != 'temp-username') {
                // User's displayname is found via the link's "name" attribute.
                var sub_link_name = sub_link.query('a').getAttribute('name');
                nodes_by_name[sub_link_name] = sub_link;
                if (sub_link.query('img.unsub-icon')) {
                    unsubscribables.push(sub_link_name);
                } else {
                    not_unsubscribables.push(sub_link_name);
                }
            }
        });

        // Add the current subscription.
        if (can_be_unsubscribed) {
            unsubscribables.push(full_name);
        } else {
            not_unsubscribables.push(full_name);
        }
        unsubscribables.sort();
        not_unsubscribables.sort();
    } else {
        // If there is no all_subscribers, then we're dealing with
        // the printed None, so return.
        return;
    }

    var i;
    if ((!unsubscribables && !not_unsubscribables) ||
        // If A) neither list exists, B) the user belongs in the second
        // list but the second list doesn't exist, or C) user belongs in the
        // first list and the second doesn't exist, return no node to append.
        (!can_be_unsubscribed && !not_unsubscribables) ||
        (can_be_unsubscribed && unsubscribables && !not_unsubscribables)) {
        return;
    } else if (
        // If the user belongs in the first list, and the first list
        // doesn't exist, but the second one does, return the first node
        // in the second list.
        can_be_unsubscribed && !unsubscribables && not_unsubscribables) {
        return nodes_by_name[not_unsubscribables[0]];
    } else if (can_be_unsubscribed) {
        // If the user belongs in the first list, loop the list for position.
        for (i=0; i<unsubscribables.length; i++) {
            if (unsubscribables[i] == full_name) {
                if (i+1 < unsubscribables.length) {
                    return nodes_by_name[unsubscribables[i+1]];
                // If the current link should go at the end of the first
                // list and we're at the end of that list, return the
                // first node of the second list.  Due to earlier checks
                // we can be sure this list exists.
                } else if (i+1 >= unsubscribables.length) {
                    return nodes_by_name[not_unsubscribables[0]];
                }
            }
        }
    } else if (!can_be_unsubscribed) {
        // If user belongs in the second list, loop the list for position.
        for (i=0; i<not_unsubscribables.length; i++) {
            if (not_unsubscribables[i] == full_name) {
                if (i+1 < not_unsubscribables.length) {
                    return nodes_by_name[not_unsubscribables[i+1]];
                } else {
                    return;
                }
            }
        }
    }
}

/*
 * Add the user name to the subscriber's list.
 *
 * @method add_user_name_link
 */
function add_user_name_link(subscription) {
    var person = subscription.get('person');
    var link_node = build_user_link_html(subscription);
    var subscribers = Y.get('#subscribers-links');
    if (subscription.is_current_user_subscribing()) {
        // If this is the current user, then top post the name and be done.
        subscribers.insertBefore(link_node, subscribers.get('firstChild'));
    } else {
        var next = get_next_subscriber_node(subscription);
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
    }

    // Set the click handler if adding a remove icon.
    if (subscription.can_be_unsubscribed_by_user()) {
        var remove_icon = Y.get('#unsubscribe-icon-' + person.get('name'));
        remove_icon.on('click', function(e) {
            e.halt();
            unsubscribe_user_via_icon(e.target, subscription);
        });
    }
}

/*
 * Add a grayed out, temporary user name when subscribing
 * someone else.
 *
 * @method add_temp_user_name
 * @param subscription_link {Node} The sub/unsub link.
 */
function add_temp_user_name(subscription) {
    // Be paranoid about display_name, since timeouts or other errors
    // could mean display_name wasn't set on initialization.
    if (subscription.get('person').get('display_name') === '') {
        subscription.get('person').set_display_name();
    }
    var display_name = subscription.get('person').get('display_name');
    var img_src;
    if (subscription.is_team()) {
        img_src = '/@@/teamgray';
    } else {
        img_src = '/@@/persongray';
    }

    // The <span>...</span> below must *not* be <span/>. On FF (maybe
    // others, but at least on FF 3.0.11) will then not notice any
    // following sibling nodes, like the spinner image.
    var link_node = Y.Node.create([
        '<div id="temp-username"> ',
        '  <img alt="" width="14" height="14" />',
        '  <span>Other Display Name</span>',
        '  <img id="temp-name-spinner" src="/@@/spinner" alt="" ',
        '       style="position:absolute;right:8px" /></div>'].join(''));
    link_node.query('img').set('src', img_src);
    link_node.replaceChild(
        document.createTextNode(display_name),
        link_node.query('span'));

    var subscribers = Y.get('#subscribers-links');
    var next = get_next_subscriber_node(subscription);
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

    // Fire a custom event to know it's safe to begin
    // any actual subscribing work.
    Y.bugs.portlet.fire('bugs:nameloaded', subscription);
}

/*
 * Add the "None" div to the subscribers list if
 * there aren't any subscribers left.
 *
 * @method set_none_for_empty_subscribers
 */
function set_none_for_empty_subscribers() {
    var subscriber_list = Y.get('#subscribers-links');
    // Assume if subscriber_list has no child divs
    // then the list of subscribers is empty.
    if (!Y.Lang.isValue(subscriber_list.query('div')) &&
        !Y.Lang.isValue(Y.get('#none-subscribers'))) {
        var none_div = Y.Node.create('<div id="none-subscribers">None</div>');
        subscriber_list.appendChild(none_div);
    }

    // Clear the empty duplicate subscribers list if it exists.
    var dup_list = Y.get('#subscribers-from-duplicates');
    if (Y.Lang.isValue(dup_list) &&
        !Y.Lang.isValue(dup_list.query('div'))) {
        var parent = dup_list.get('parentNode');
        parent.removeChild(dup_list);
    }
}

/*
 * Set the class on subscription link's parentNode.
 *
 * This is used to reset the class used by the
 * click handler to know which link was clicked.
 *
 * @method set_subscription_link_parent_class
 * @param subscription_link {Node} The sub/unsub link.
 * @param subscribed {Boolean} The sub/unsub'ed flag for the class.
 * @param dupe_subscribed {Boolean} The sub/unsub'ed flag for dupes
 *                                  on the class.
 */
function set_subscription_link_parent_class(
    user_link, subscribed, dupe_subscribed) {

    var parent = user_link.get('parentNode');
    if (subscribed) {
        parent.removeClass('subscribed-false');
        parent.addClass('subscribed-true');
    } else {
        parent.removeClass('subscribed-true');
        parent.addClass('subscribed-false');
    }

    if (dupe_subscribed) {
        parent.removeClass('dup-subscribed-false');
        parent.addClass('dup-subscribed-true');
    } else {
        parent.removeClass('dup-subscribed-true');
        parent.addClass('dup-subscribed-false');
    }
}

/*
 * Unsubscribe a user from this bugtask when a remove icon is clicked.
 *
 * @method unsubscribe_user_via_icon
 * @param icon {Node} The remove icon that was clicked.
 * @param subscription {Object} A Y.lp.Subscription object.
*/
function unsubscribe_user_via_icon(icon, subscription) {
    icon.set('src', '/@@/spinner');
    var icon_parent = icon.get('parentNode');

    var user_uri = get_user_uri_from_icon(icon);
    var person = new Y.lp.Subscriber({uri: user_uri});
    subscription.set('person', person);

    // Determine if this is a dupe.
    var is_dupe;
    var icon_parent_div = icon_parent.get('parentNode');
    var dupe_id = 'dupe-subscriber-' + person.get('name');
    if (icon_parent_div.get('id') == dupe_id) {
        is_dupe = true;
    } else {
        is_dupe = false;
    }

    var error_handler = new LP.client.ErrorHandler();
    error_handler.clearProgressUI = function () {
        icon.set('src', '/@@/remove');
        // Grab the icon again to reset to click handler.
        var unsubscribe_icon = Y.get(
            '#unsubscribe-icon-' + person.get('name'));
        unsubscribe_icon.on('click', function(e) {
            e.halt();
            unsubscribe_user_via_icon(e.target, subscription);
        });

    };
    error_handler.showError = function (error_msg) {
        var flash_node = Y.get('.subscriber-' + person.get('name'));
        display_error(flash_node, error_msg);

    };

    var subscription_link = subscription.get('link');
    var config = {
        on: {
            success: function(client) {
                icon_parent.removeChild(icon);
                var anim = Y.lazr.anim.green_flash({ node: icon_parent_div });
                anim.on('end', function(e) {
                    remove_user_name_link(icon_parent_div);
                    set_none_for_empty_subscribers();
                    var person_link = Y.get(
                        '.subscriber-' + person.get('name'));
                    if (Y.Lang.isNull(person_link) &&
                        subscription.is_current_user_subscribing()) {
                            // Current user has been completely unsubscribed.
                            subscription_link.set('innerHTML', 'Subscribe');
                            set_subscription_link_parent_class(
                                subscription_link, false, false);
                            subscription.set('is_direct', false);
                            subscription.set('has_dupes', false);
                    } else {
                        if (is_dupe) {
                            // A direct subscription remains.
                            set_subscription_link_parent_class(
                                subscription_link, true, false);
                            subscription.set('is_direct', true);
                            subscription.set('has_dupes', false);
                        } else {
                            // A dupe subscription remains.
                            set_subscription_link_parent_class(
                                subscription_link, false, true);
                            subscription.set('is_direct', false);
                            subscription.set('has_dupes', true);
                        }
                    }
                    subscription_link.removeClass('sprite-after remove');
                    subscription_link.addClass('sprite add');
                });
                anim.run();
            },

            failure: error_handler.getFailureHandler()
        }
    };

    if (!subscription.is_current_user_subscribing()) {
        config.parameters = {
            person: LP.client.get_absolute_uri(user_uri)
        };
    }

    if (is_dupe) {
        lp_client.named_post(
            bug_repr.self_link, 'unsubscribeFromDupes', config);
    } else {
        lp_client.named_post(bug_repr.self_link, 'unsubscribe', config);
    }
}

/*
 * Subscribe the current user via the LP API.
 *
 * @method subscribe_current_user
 * @param subscription {Object} A Y.lp.Subscription object.
 */
function subscribe_current_user(subscription) {
    subscription.enable_spinner('Subscribing...');
    var subscription_link = subscription.get('link');
    var subscriber = subscription.get('subscriber');

    var error_handler = new LP.client.ErrorHandler();
    error_handler.clearProgressUI = function () {
        subscription.disable_spinner();
    };
    error_handler.showError = function (error_msg) {
        display_error(subscription_link, error_msg);
    };

    var config = {
        on: {
            success: function(client) {
                subscription.disable_spinner('Unsubscribe');

                if (subscription.has_duplicate_subscriptions()) {
                    set_subscription_link_parent_class(
                        subscription_link, true, true);
                } else {
                    set_subscription_link_parent_class(
                        subscription_link, true, false);
                }

                // Handle the case where the subscriber's list displays "None".
                var empty_subscribers = Y.get("#none-subscribers");
                if (empty_subscribers) {
                    var parent = empty_subscribers.get('parentNode');
                    parent.removeChild(empty_subscribers);
                }

                add_user_name_link(subscription);

                var flash_node = Y.get('.subscriber-' + subscriber.get('name'));
                var anim = Y.lazr.anim.green_flash({ node: flash_node });
                anim.run();
            },

            failure: error_handler.getFailureHandler()
        },

        parameters: {
            person: LP.client.get_absolute_uri(subscriber.get('escaped_uri'))
        }
    };
    lp_client.named_post(bug_repr.self_link, 'subscribe', config);
}

/*
 * Unsubscribe the current user via the LP API.
 *
 * @method unsubscribe_current_user
 * @param subscription {Object} A Y.lp.Subscription object.
 */
function unsubscribe_current_user(subscription) {
    subscription.enable_spinner('Unsubscribing...');
    var subscription_link = subscription.get('link');
    var subscriber = subscription.get('subscriber');

    var error_handler = new LP.client.ErrorHandler();
    error_handler.clearProgressUI = function () {
        subscription.disable_spinner();
    };
    error_handler.showError = function (error_msg) {
        display_error(subscription_link, error_msg);
    };

    var config = {
        on: {
            success: function(client) {
                if (subscription.is_direct_subscription() &&
                    subscription.has_duplicate_subscriptions()) {
                    // Don't change the 'Unsubscribe' text if
                    // dupe subscriptions remain.
                    subscription.disable_spinner();
                    set_subscription_link_parent_class(
                        subscription_link, false, true);
                    subscription.set('is_direct', false);
                } else if (subscription.is_direct_subscription() &&
                          !subscription.has_duplicate_subscriptions()) {
                    // Only unsub'ing a direct subscriber here.
                    subscription.disable_spinner('Subscribe');
                    set_subscription_link_parent_class(
                        subscription_link, false, false);
                    subscription.set('is_direct', false);
                } else {
                    // Only unsub'ing dupes here.
                    subscription.disable_spinner('Subscribe');
                    set_subscription_link_parent_class(
                        subscription_link, false, false);
                    subscription.set('has_dupes', false);
                }

                var flash_node = Y.get('.subscriber-' + subscriber.get('name'));
                var anim = Y.lazr.anim.green_flash({ node: flash_node });
                anim.on('end', function(e) {
                    remove_user_name_link(flash_node);
                    set_none_for_empty_subscribers();
                });
                anim.run();
            },

            failure: error_handler.getFailureHandler()
        }
    };

    if (subscription.is_direct_subscription()) {
        lp_client.named_post(bug_repr.self_link, 'unsubscribe', config);
    } else {
        lp_client.named_post(
            bug_repr.self_link, 'unsubscribeFromDupes', config);
    }
}

var setup_edit_rollover = function(content) {
    var edit_icon = content.query('.editicon');
    content.on('mouseover', function(e) {
        edit_icon.setAttribute('src', '/@@/edit');
    });
    content.on('mouseout', function(e) {
        edit_icon.setAttribute('src', '/@@/edit-transparent');
    });
    content.setStyle('cursor', 'pointer');
};

/**
 * Set up a bug task table row.
 *
 * Called once, on load, to initialize the page.
 *
 * @method setup_bugtasks_row
 */
bugs.setup_bugtask_row = function(conf) {

    if (Y.UA.ie) {
        return;
    }

    var tr = Y.get('#' + conf.row_id);
    var status_content = tr.query('.status-content');
    var importance_content = tr.query('.importance-content');

    // If the bug is a duplicate, don't set the widget up and
    // canel clicks on the edit links. Users most likely don't
    // want to edit the bugtasks.
    if (Y.Lang.isValue(LP.client.cache.bug.duplicate_of_link)) {
        status_content.on('click', function(e) { e.halt(); });
        importance_content.on('click', function(e) { e.halt(); });
        return;
    }

    if ((LP.client.links.me !== undefined) && (LP.client.links.me !== null))  {
        var status_choice_edit = new Y.ChoiceSource({
            contentBox: status_content,
            value: conf.status_value,
            title: 'Change status to',
            items: conf.status_widget_items,
            elementToFlash: status_content.get('parentNode'),
            backgroundColor: tr.hasClass('highlight') ? '#FFFF99' : '#FFFFFF'
        });
        status_choice_edit.showError = function(err) {
          display_error(null, err);
        };
        status_choice_edit.on('save', function(e) {
            var cb = status_choice_edit.get('contentBox');
            Y.Array.each(conf.status_widget_items, function(item) {
                if (item.value == status_choice_edit.get('value')) {
                    cb.addClass(item.css_class);
                } else {
                    cb.removeClass(item.css_class);
                }
            });
            // Set the inline form control's value, so that submitting
            // it won't override the value we just set.
            Y.get(document.getElementById(conf.prefix + '.status')).set(
                'value', status_choice_edit.get('value'));
        });
        status_choice_edit.plug({
            fn: Y.lp.client.plugins.PATCHPlugin, cfg: {
                    patch: 'status',
                    resource: conf.bugtask_path}});
        status_choice_edit.render();
        if (conf.user_can_edit_importance) {
            var importance_choice_edit = new Y.ChoiceSource({
                contentBox: importance_content,
                value: conf.importance_value,
                title: 'Change importance to',
                items: conf.importance_widget_items,
                elementToFlash: importance_content.get('parentNode'),
                backgroundColor: tr.hasClass('highlight') ? '#FFFF99' : '#FFFFFF'
            });
            importance_choice_edit.showError = function(err) {
              display_error(null, err);
            };
            importance_choice_edit.on('save', function(e) {
                var cb = importance_choice_edit.get('contentBox');
                Y.Array.each(conf.importance_widget_items, function(item) {
                    if (item.value == importance_choice_edit.get('value')) {
                        cb.addClass(item.css_class);
                    } else {
                        cb.removeClass(item.css_class);
                    }
                });
                // Set the inline form control's value, so that submitting
                // it won't override the value we just set.
                Y.get(document.getElementById(conf.prefix + '.importance')).set(
                    'value', importance_choice_edit.get('value'));
            });
            importance_choice_edit.plug({
                fn: Y.lp.client.plugins.PATCHPlugin, cfg: {
                        patch: 'importance',
                        resource: conf.bugtask_path}});
            importance_choice_edit.render();
        }
    }
    setup_edit_rollover(status_content);
    if (conf.user_can_edit_importance) {
      setup_edit_rollover(importance_content);
    }
};

/**
 * Set up the "me too" selection.
 *
 * Called once, on load, to initialize the page. Call this function if
 * the "me too" information is displayed on a bug page and the user is
 * logged in.
 *
 * @method setup_me_too
 */
bugs.setup_me_too = function(user_is_affected) {
    var me_too_content = Y.get('#affectsmetoo');
    var me_too_edit = new MeTooChoiceSource({
        contentBox: me_too_content,
        value: user_is_affected ? true : false,
        title: 'Does this bug affect you?',
        items: [
            {name: 'This bug affects me too',
             value: true, disabled: false},
            {name: "This bug doesn't affect me",
             value: false, disabled: false}
        ],
        elementToFlash: me_too_content,
        backgroundColor: '#FFFFFF'
    });
    me_too_edit.render();
};

/**
 * This class is a derivative of ChoiceSource that handles the
 * specifics of editing "me too" option.
 *
 * @class MeTooChoiceSource
 * @extends ChoiceSource
 * @constructor
 */
function MeTooChoiceSource() {
    MeTooChoiceSource.superclass.constructor.apply(this, arguments);
}

Y.mix(MeTooChoiceSource, {
    NAME: 'metoocs',
    NS: 'metoocs'
});

Y.extend(MeTooChoiceSource, Y.ChoiceSource, {
    initializer: function() {
        var widget = this;
        this.error_handler = new LP.client.ErrorHandler();
        this.error_handler.clearProgressUI = function() {
            widget._uiClearWaiting();
        };
        this.error_handler.showError = function(error_msg) {
            widget.showError(error_msg);
        };
    },

    showError: function(err) {
        display_error(null, err);
    },

    syncUI: function() {
        MeTooChoiceSource.superclass.syncUI.apply(this, arguments);
        // Show the flame icon if the user is affected by this bug.
        var content_box = this.get('contentBox');
        var flame = content_box.query('.dynamic img[src=/@@/flame-icon]');
        if (this.get('value')) {
            flame.removeClass('unseen');
        } else {
            flame.addClass('unseen');
        }
    },

    render: function() {
        MeTooChoiceSource.superclass.render.apply(this, arguments);
        // Force the ChoiceSource to be rendered inline.
        this.get('boundingBox').setStyle('display', 'inline');
        // Hide the static content and show the dynamic content.
        this.get('contentBox').query('.static').addClass('unseen');
        this.get('contentBox').query('.dynamic').removeClass('unseen');
    },

    _saveData: function() {
        // Set the widget to the 'waiting' state.
        this._uiSetWaiting();

        var value = this.getInput();
        var client =  new LP.client.Launchpad();
        var widget = this;

        var config = {
            on: {
                success: function(entry) {
                    widget._uiClearWaiting();
                    MeTooChoiceSource.superclass._saveData.call(
                        widget, value);
                },
                failure: this.error_handler.getFailureHandler()
            },
            parameters: {
                affected: value
            }
        };

        client.named_post(
            LP.client.cache.bug.self_link, 'markUserAffected', config);
    }
});

/*
 * Check if the current user can unsubscribe the person
 * being subscribed.
 *
 * This must be done in JavaScript, since the subscription
 * hasn't completed yet, and so, can_be_unsubscribed_by_user
 * cannot be used.
 *
 * @method check_can_be_unsubscribed
 * @param subscription {Object} A Y.lp.Subscription object.
 */
function check_can_be_unsubscribed(subscription) {
    var error_handler = new LP.client.ErrorHandler();
    error_handler.showError = function (error_msg) {
        display_error(Y.get('.menu-link-addsubscriber'), error_msg);
    };

    var config = {
        on: {
            success: function(result) {
                var is_team = result.get('is_team');
                subscription.set('is_team', is_team);
                var final_config = {
                    on: {
                        success: function(result) {
                            var team_member = false;
                            for (var i=0; i<result.entries.length; i++) {
                                 if (result.entries[i].member_link ==
                                    LP.client.get_absolute_uri(
                                        subscription.get(
                                            'subscriber').get('uri'))) {
                                    team_member = true;
                                }
                            }

                            if (team_member) {
                                subscription.set('can_be_unsubscribed', true);
                                add_temp_user_name(subscription);
                            } else {
                                subscription.set('can_be_unsubscribed', false);
                                add_temp_user_name(subscription);
                            }
                        },

                        failure: error_handler.getFailureHandler()
                    }
                };

                if (is_team) {
                    // Get a list of members to see if current user
                    // is a team member.
                    var members = result.get('members_details_collection_link');
                    lp_client.get(members, final_config);
                } else {
                    subscription.set('can_be_unsubscribed', false);
                    add_temp_user_name(subscription);
                }
            },

            failure: error_handler.getFailureHandler()
        }
    };
    lp_client.get(LP.client.get_absolute_uri(
        subscription.get('person').get('escaped_uri')), config);
}

/*
 * Subscribe a person or team other than the current user.
 * This is a callback for the subscribe someone else picker.
 *
 * @method subscribe_someone_else
 * @result {Object} The object representing a person returned by the API.
 */
function subscribe_someone_else(result, subscription) {
    var person = new Y.lp.Subscriber({
        uri: result.api_uri,
        display_name: result.title
    });
    subscription.set('person', person);

    var error_handler = new LP.client.ErrorHandler();
    error_handler.showError = function(error_msg) {
        display_error(Y.get('.menu-link-addsubscriber'), error_msg);
    };

    if (subscription.is_already_subscribed()) {
        error_handler.showError(
             subscription.get('person').get('full_display_name') +
             ' has already been subscribed');
    } else {
        check_can_be_unsubscribed(subscription);
    }
}
}, '0.1', {requires: ['base', 'oop', 'node', 'event', 'io-base', 'substitute',
                      'widget-position-ext', 'lazr.formoverlay', 'lazr.anim',
                      'lazr.base', 'lazr.overlay', 'lazr.choiceedit',
                      'lp.picker', 'lp.client.plugins', 'lp.subscriber']});
