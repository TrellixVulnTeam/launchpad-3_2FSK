/* Copyright 2010 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Handling of the bug subscription form overlay widget.
 *
 * @module bugs
 * @submodule bug_subscription_wizard
 */
YUI.add('lp.bugs.bug_subscription_wizard', function(Y) {

var namespace = Y.namespace('lp.bugs.bug_subscription_wizard');

var submit_button_html =
    '<button type="submit" name="field.actions.subscribe" ' +
    'value="Subscribe"' +
    'class="lazr-pos lazr-btn" >OK</button>';
var cancel_button_html =
    '<button type="button" name="field.actions.cancel" ' +
    'class="lazr-neg lazr-btn" >Cancel</button>';

namespace.subscription_wizard = null;
namespace.subscribe_form_body = null;

namespace.create_subscription_wizard = function() {
    // Create the do-you-want-to-subscribe FormOverlay.
    var wizard_steps = [
        new Y.lazr.wizard.Step({
            form_content: namespace.subscribe_form_body,
            form_submit_button: Y.Node.create(submit_button_html),
            form_cancel_button: Y.Node.create(cancel_button_html),
            funcLoad: function() {},
            funcCleanUp: function() {}
            })
        ];
    namespace.subscription_wizard = new Y.lazr.wizard.Wizard({
        headerContent: '<h2>Subscribe to this bug</h2>',
        centered: true,
        visible: false,
        steps: wizard_steps
    });
    namespace.subscription_wizard.render('#subscribe-wizard');
    Y.fire('subscriptionwizard:ready');
};

/**
 * Load the subscription form from a remote source.
 *
 * @method load_subscription_form
 * @param {string} url the URL to load the form from.
 * @param {Object} io_provider an Object providing a .io() method. This
 *     will only be used for testing purposes; if io_provider is not
 *     passed we'll just use Y.io for everything.
 */
namespace.load_subscription_form = function(url, io_provider) {
    if (io_provider === undefined) {
        io_provider = Y;
    }
    function on_success(id, response) {
        namespace.subscribe_form_body = response.responseText;
        Y.fire('subscriptionform:loaded');
    }
    function on_failure(id, response) {
        namespace.subscribe_form_body =
            "Sorry, an error occurred while loading the form.";
        Y.fire('subscriptionform:loaded');
    }
    var cfg = {
        on: {
            success: on_success,
            failure: on_failure
            },
        }
    io_provider.io(url, cfg);
};

/**
 * Initialize the subscription wizard and set up event handlers.
 *
 * @method initialize_subscription_wizard
 * @param {Node} target_node The node to which to link the wizard.
 * @param {string} url the URL to load the form from.
 * @param {Object} io_provider an Object providing a .io() method.
 *      This is only used for testing.
 */
namespace.initialize_subscription_wizard = function(
    target_node, url, io_provider)
{
    // Set up the event handlers.
    Y.on(
        'subscriptionform:loaded',
        Y.bind(function(e) { namespace.create_subscription_wizard() }));
    Y.on(
        'subscriptionwizard:ready', 
        Y.bind(function(e) { namespace.subscription_wizard.show() }));
    namespace.load_subscription_form(url, io_provider);
};

}, "0.1", {"requires": [
    "base", "io", "oop", "node", "event", "lazr.formoverlay",
    "lazr.effects", "lazr.wizard"]});
