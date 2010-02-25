/* Copyright 2009 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Code for handling the popup diffs in the pretty overlays.
 *
 * @module popupdiff
 * @requires node
 */

YUI.add('code.branchmergeproposal.popupdiff', function(Y) {

// The launchpad js client used.
var lp_client;

/*
 * The DiffOverlay object inherits from the lazr-js PerttyOverlay.
 *
 * By sub-classing the DiffOverlay gets its own CSS class that is applied to
 * the various HTML objeccts that are created.  This allows styling of the
 * overlay in a different way to any other PrettyOverlays.
 */
var DiffOverlay = function() {
    DiffOverlay.superclass.constructor.apply(this, arguments);
};

Y.extend(DiffOverlay, Y.lazr.PrettyOverlay, {
        bindUI: function() {
            // call PrettyOverlay's bindUI
            this.constructor.superclass.bindUI.call(this);
        }
    });

// The NAME gets appended to 'yui-' to give the class name 'yui-diff-overlay'.
DiffOverlay.NAME = 'diff-overlay';

// A local page cache of the diff overlays that have been rendered.
// This makes subsequent views of an already loaded diff instantaneous.
var rendered_overlays = {};

/*
 * Display the diff for the specified api_url.
 *
 * If the specified api_url has already been rendered in an overlay, show it
 * again.  If it hasn't been loaded, show the spinner, and load the diff using
 * the LP API.
 *
 * If the diff fails to load, the user is taken to the librarian url just as
 * if Javascript was not enabled.
 */
function display_diff(node, api_url, librarian_url) {

    // Look to see if we have rendered one already.
    if (rendered_overlays[api_url] !== undefined) {
        rendered_overlays[api_url].show();
        return;
    }

    // Show a spinner.
    var html = [
        '<img src="/@@/spinner" alt="loading..." ',
        '     style="padding-left: 0.5em"/>'].join('');
    var spinner = Y.Node.create(html);
    node.appendChild(spinner);

    // Load the diff.
    var config = {
        on: {
            success: function(formatted_diff) {
                node.removeChild(spinner);
                var diff_overlay = new DiffOverlay({
                        bodyContent: Y.Node.create(formatted_diff),
                        align: {
                            points: [Y.WidgetPositionExt.CC,
                                     Y.WidgetPositionExt.CC]
                        },
                        progressbar: false
                    });
                rendered_overlays[api_url] = diff_overlay;
                diff_overlay.render();
            },
            failure: function() {
                node.removeChild(spinner);
                // Fail over to loading the librarian link.
                document.location = librarian_url;
            }
        },
        accept: LP.client.XHTML
    };
    lp_client.get(api_url, config);
}


// Grab the namespace in order to be able to expose the connect method.
var namespace = Y.namespace('code.branchmergeproposal.popupdiff');

/*
 * Link up the onclick handler for the a.diff-link in the node to the function
 * that will popup the diff in the pretty overlay.
 */
function link_popup_diff_onclick(node) {
    var a = node.query('a.diff-link');
    if (Y.Lang.isValue(a)) {
        a.addClass('js-action');
        var librarian_url = a.getAttribute('href');
        var api_url = node.query('a.api-ref').getAttribute('href');
        a.on('click', function(e) {
                e.preventDefault();
                display_diff(a, api_url, librarian_url);
            });
    }
}

/*
 * Connect the diff links to their pretty overlay function.
 */
namespace.connect_diff_links = function() {
    // IE doesn't like pretty overlays.
    if (Y.UA.ie) {
        return;
    }

    // Setup the LP client.
    lp_client = new LP.client.Launchpad();

    // Listen for the branch-linked custom event.
    Y.on('lp:branch-linked', link_popup_diff_onclick);
    // var status_content = Y.get('#branch-details-status-value');
    var nl = Y.all('.popup-diff');
    if (nl) {
        nl.each(link_popup_diff_onclick);
    }
};

    }, '0.1', {requires: ['event', 'io', 'node', 'lazr.overlay', 'lp.client']});
