/* Copyright (c) 2011, Canonical Ltd. All rights reserved. */

YUI({
    base: '../../../../canonical/launchpad/icing/yui/',
    filter: 'raw',
    combine: false,
    fetchCSS: false
    }).use('test', 'console', 'node', 'node-event-simulate', 'lp.client',
        'lp.registry.structural_subscription', function(Y) {

    var suite = new Y.Test.Suite("Structural subscription overlay tests");

    var context;
    var test_case;

    // Local aliases
    var Assert = Y.Assert,
        ArrayAssert = Y.ArrayAssert,
        module = Y.lp.registry.structural_subscription;

    // Expected content box.
    var content_box_name = 'ss-content-box';
    var content_box_id = '#' + content_box_name;

    // Listing node.
    var subscription_listing_name = 'subscription-listing';
    var subscription_listing_id = '#' + subscription_listing_name;

    var target_link_class = '.menu-link-subscribe_to_bug_mail';

    function array_compare(a,b) {
        if (a.length !== b.length) {
            return false;
        }
        a.sort();
        b.sort();
        var i;
        for (i=0; i<a.length; i++) {
            if (a[i] !== b[i]) {
                return false;
            }
        }
        return true;
    }

    function create_test_node(include_listing) {
        var test_node = Y.Node.create('<div id="test-content">')
            .append(Y.Node.create('<div></div>')
                .set('id', content_box_name));
        test_node.append(Y.Node.create(
            '<a href="#" class="menu-link-subscribe_to_bug_mail">'+
            'A link, a link, my kingdom for a link</a>'));

        if (include_listing) {
            test_node.append(Y.Node.create('<div style="width: 50%"></div>')
                .set('id', subscription_listing_name));
        }

        return test_node;
    }

    function remove_test_node() {
        Y.one('body').removeChild(Y.one('#test-content'));
        var error_overlay = Y.one('.yui3-lazr-formoverlay');
        if (Y.Lang.isValue(error_overlay)) {
            Y.one('body').removeChild(error_overlay);
        }
    }

    function test_checked(list, expected) {
        var item, i;
        var length = list.size();
        for (i=0; i < length; i++) {
            item = list.item(i);
            if (item.get('checked') !== expected) {
                return false;
            }
        }
        return true;
    }

    function monkeypatch_LP() {
          // Monkeypatch LP to avoid network traffic and to allow
          // insertion of test data.
          var original_lp = window.LP;
          window.LP = {
            links: {},
            cache: {}
          };

          LP.cache.context = {
            title: 'Test Project',
            self_link: 'https://launchpad.dev/api/test_project'
          };
          LP.cache.administratedTeams = [];
          LP.cache.importances = ['Unknown', 'Critical', 'High', 'Medium',
                                  'Low', 'Wishlist', 'Undecided'];
          LP.cache.statuses = ['New', 'Incomplete', 'Opinion',
                               'Invalid', 'Won\'t Fix', 'Expired',
                               'Confirmed', 'Triaged', 'In Progress',
                               'Fix Committed', 'Fix Released', 'Unknown'];
          LP.links.me = 'https://launchpad.dev/api/~someone';
          return original_lp;
    }

    function LPClient(){
        if (!(this instanceof LPClient)) {
            throw new Error("Constructor called as a function");
        }
        this.received = [];
        // We create new functions every time because we allow them to be
        // configured.
        this.named_post = function(url, func, config) {
            this._call('named_post', config, arguments);
        };
        this.patch = function(bug_filter, data, config) {
            this._call('patch', config, arguments);
        };
    }

    LPClient.prototype._call = function(name, config, args) {
        this.received.push(
            [name, Array.prototype.slice.call(args)]);
        if (!Y.Lang.isValue(args.callee.args)) {
            throw new Error("Set call_args on "+name);
        }
        var do_action = function () {
            if (Y.Lang.isValue(args.callee.fail) && args.callee.fail) {
                config.on.failure.apply(undefined, args.callee.args);
            } else {
                config.on.success.apply(undefined, args.callee.args);
            }
        };
        if (Y.Lang.isValue(args.callee.halt) && args.callee.halt) {
            args.callee.resume = do_action;
        } else {
            do_action();
        }
    };
    // DELETE uses Y.io directly as of this writing, so we cannot stub it
    // here.

    function make_lp_client_stub() {
        return new LPClient();
    }

    suite.add(new Y.Test.Case({
        name: 'Tests for the fake LP client (LPClient) used in these tests.',

        _should: {
            error: {
                test_error_when_used_as_a_function: new Error(
                    'Constructor called as a function')
            }
        },

        test_error_when_used_as_a_function: function() {
            // LPClient has a built-in safety to ensure that it's instantiated
            // correctly.
            LPClient();
        }
    }));

    test_case = new Y.Test.Case({
        name: 'structural_subscription_overlay',

        _should: {
            error: {
                test_setup_config_none: new Error(
                    'Missing config for structural_subscription.'),
                test_setup_config_no_content_box: new Error(
                    'Structural_subscription configuration has undefined '+
                    'properties.')
                }
        },

        setUp: function() {
            // Monkeypatch LP to avoid network traffic and to allow
            // insertion of test data.
            window.LP = {
                links: {},
                cache: {}
            };
            LP.cache.context = {
                title: 'Test Project',
                self_link: 'https://launchpad.dev/api/test_project'
            };
            LP.cache.administratedTeams = [];
            LP.cache.importances = [];
            LP.cache.statuses = [];

            this.configuration = {
                content_box: content_box_id
            };
            this.content_node = create_test_node();
            Y.one('body').appendChild(this.content_node);
        },

        tearDown: function() {
            //delete this.configuration;
            remove_test_node();
            delete this.content_node;
            delete this.configuration.lp_client;
            delete this.content_node;
        },

        test_setup_config_none: function() {
            // The config passed to setup may not be null.
            module.setup();
        },

        test_setup_config_no_content_box: function() {
            // The config passed to setup must contain a content_box.
            module.setup({});
        },

        test_anonymous: function() {
            // The link should not be shown to anonymous users so
            // 'setup' should not do anything in that case.  If it
            // were successful, the lp_client would be defined after
            // setup is called.
            LP.links.me = undefined;
            Assert.isUndefined(module.lp_client);
            module.setup(this.configuration);
            Assert.isUndefined(module.lp_client);
        },

        test_logged_in_user: function() {
            // If there is a logged-in user, setup is successful
            LP.links.me = 'https://launchpad.dev/api/~someone';
            Assert.isUndefined(module.lp_client);
            module.setup(this.configuration);
            Assert.isNotUndefined(module.lp_client);
        },

        test_list_contains: function() {
            // Validate that the list_contains function actually reports
            // whether or not an element is in a list.
            var list = ['a', 'b', 'c'];
            Assert.isTrue(module._list_contains(list, 'b'));
            Assert.isFalse(module._list_contains(list, 'd'));
            Assert.isFalse(module._list_contains([], 'a'));
            Assert.isTrue(module._list_contains(['a', 'a'], 'a'));
            Assert.isFalse(module._list_contains([], ''));
            Assert.isFalse(module._list_contains([], null));
            Assert.isFalse(module._list_contains(['a'], null));
            Assert.isFalse(module._list_contains([]));
        },

        test_make_selector_controls: function() {
            // Verify the creation of select all/none controls.
            var selectors = module.make_selector_controls('sharona');
            Assert.areEqual(
                'Select all', selectors.all_link.get('text'));
            Assert.areEqual(
                'Select none', selectors.none_link.get('text'));
            Assert.areEqual(
                'sharona-selectors', selectors.node.get('id'));
        }
    });
    suite.add(test_case);

    test_case = new Y.Test.Case({
        name: 'Structural Subscription Overlay save_subscription',

        _should: {
            error: {}
        },

        setUp: function() {
            // Monkeypatch LP to avoid network traffic and to allow
            // insertion of test data.
            window.LP = {
                links: {},
                cache: {}
            };
            Y.lp.client.Launchpad = function() {};
            Y.lp.client.Launchpad.prototype.named_post =
                function(url, func, config) {
                    context.url = url;
                    context.func = func;
                    context.config = config;
                    // No need to call the on.success handler.
                };
            LP.cache.context = {
                title: 'Test Project',
                self_link: 'https://launchpad.dev/api/test_project'
            };
            LP.links.me = 'https://launchpad.dev/api/~someone';
            LP.cache.administratedTeams = [];
            LP.cache.importances = [];
            LP.cache.statuses = [];

            this.configuration = {
                content_box: content_box_id
            };
            this.content_node = create_test_node();
            Y.one('body').appendChild(this.content_node);

            this.bug_filter = {
                lp_original_uri:
                    '/api/devel/firefox/+subscription/mark/+filter/28'
            };
            this.form_data = {
                recipient: ['user']
            };
            context = {};

            // Get the save subscription handler with empty success handler.
            this.save_subscription = module._make_add_subscription_handler(
                function() {});
        },

        tearDown: function() {
            delete this.configuration;
            remove_test_node();
            delete this.content_node;
        },

        test_user_recipient: function() {
            // When the user selects themselves as the recipient, the current
            // user's URI is used as the recipient value.
            module.setup(this.configuration);
            module._show_add_overlay(this.configuration);
            this.form_data.recipient = ['user'];
            this.save_subscription(this.form_data);
            Assert.areEqual(
                LP.links.me,
                context.config.parameters.subscriber);
        },

        test_team_recipient: function() {
            // When the user selects a team as the recipient, the selected
            // team's URI is used as the recipient value.
            module.setup(this.configuration);
            module._show_add_overlay(this.configuration);
            this.form_data.recipient = ['team'];
            this.form_data.team = ['https://launchpad.dev/api/~super-team'];
            this.save_subscription(this.form_data);
            Assert.areEqual(
                this.form_data.team[0],
                context.config.parameters.subscriber);
        }
    });
    suite.add(test_case);

    test_case = new Y.Test.Case({
        name: 'Structural Subscription validation tests',

        _should: {
            error: {
                }
        },

        setUp: function() {
            // Monkeypatch LP to avoid network traffic and to allow
            // insertion of test data.
            window.LP = {
                links: {},
                cache: {}
            };

        },

        test_get_error_for_tags_list_valid: function() {
            // Valid tags list is a space-separated list of tags
            // consisting of all lowercase and digits and potentially
            // '+', '-', '.' in non-initial characters.
            var tags = 'tag1 tag+2  tag.3 tag-4 5tag';
            Assert.isNull(module._get_error_for_tags_list(tags));
        },

        assertHasErrorInTagsList: function(tags) {
            var error_text = module._get_error_for_tags_list(tags);
            Assert.isNotNull(error_text);
            Assert.areEqual(
                'Tags can only contain lowercase ASCII letters, ' +
                    'digits 0-9 and symbols "+", "-" or ".", and they ' +
                    'must start with a lowercase letter or a digit.',
                error_text);
        },


        test_get_error_for_tags_list_uppercase: function() {
            // Uppercase is not allowed in tags.
            this.assertHasErrorInTagsList('Tag');
        },

        test_get_error_for_tags_list_invalid_characters: function() {
            // Anything other than lowercase, digits or '+', '-' and '.'
            // is invalid in tags.
            this.assertHasErrorInTagsList('tag#!');
        },

        test_get_error_for_tags_list_special_characters: function() {
            // Even if '+', '-' or '.' are allowed in tags,
            // they must not be at the beginning of a tag.
            this.assertHasErrorInTagsList('tag1 +tag2 -tag3 .tag4');
        }
    });
    suite.add(test_case);

    test_case = new Y.Test.Case({
        name: 'Structural Subscription interaction tests',

        _should: {
            error: {
                test_setup_overlay_missing_content_box: new Error(
                    'Node not found: #sir-not-appearing-in-this-test')
                }
        },

        setUp: function() {
            // Monkeypatch LP to avoid network traffic and to allow
            // insertion of test data.
            window.LP = {
                links: {},
                cache: {}
            };

            LP.cache.context = {
                title: 'Test Project',
                self_link: 'https://launchpad.dev/api/test_project'
            };
            LP.cache.administratedTeams = [];
            LP.cache.importances = [];
            LP.cache.statuses = [];
            LP.links.me = 'https://launchpad.dev/api/~someone';

            var lp_client = function() {};
            this.configuration = {
                content_box: content_box_id,
                lp_client: lp_client
            };

            this.content_node = create_test_node();
            Y.one('body').appendChild(this.content_node);
        },

        tearDown: function() {
            remove_test_node();
            delete this.content_node;
        },

        test_setup_overlay: function() {
            // At the outset there should be no overlay.
            var overlay = Y.one('#accordion-overlay');
            Assert.isNull(overlay);
            module.setup(this.configuration);
            module._show_add_overlay(this.configuration);
            // After the setup the overlay should be in the DOM.
            overlay = Y.one('#accordion-overlay');
            Assert.isNotNull(overlay);
            var header = Y.one(content_box_id).one('h2');
            Assert.areEqual(
                'Add a mail subscription for Test Project bugs',
                header.get('text'));
        },

        test_setup_overlay_missing_content_box: function() {
            // Pass in a content_box with a missing id to trigger an error.
            this.configuration.content_box =
                '#sir-not-appearing-in-this-test';
            module.setup(this.configuration);
            module._setup_overlay(this.configuration.content_box);
        },

        test_initial_state: function() {
            // When initialized the <div> elements for the filter
            // wrapper and the accordion wrapper should be collapsed.
            module.setup(this.configuration);
            // Simulate a click on the link to open the overlay.
            var link = Y.one('.menu-link-subscribe_to_bug_mail');
            link.simulate('click');
            var filter_wrapper = Y.one('#filter-wrapper');
            var accordion_wrapper = Y.one('#accordion-wrapper');
            Assert.isTrue(filter_wrapper.hasClass('lazr-closed'));
            Assert.isTrue(accordion_wrapper.hasClass('lazr-closed'));
        },

        test_added_or_changed_toggles: function() {
            // Test that the filter wrapper opens and closes in
            // response to the added_or_changed radio button.
            module.setup(this.configuration);
            // Simulate a click on the link to open the overlay.
            var link = Y.one('.menu-link-subscribe_to_bug_mail');
            link.simulate('click');
            var added_changed = Y.one('#added-or-changed');
            Assert.isFalse(added_changed.get('checked'));
            var filter_wrapper = Y.one('#filter-wrapper');
            // Initially closed.
            Assert.isTrue(filter_wrapper.hasClass('lazr-closed'));
            // Opens when selected.
            added_changed.simulate('click');
            this.wait(function() {
                Assert.isTrue(filter_wrapper.hasClass('lazr-opened'));
            }, 500);
            // Closes when deselected.
            Y.one('#added-or-closed').simulate('click');
            this.wait(function() {
                Assert.isTrue(filter_wrapper.hasClass('lazr-closed'));
            }, 500);
        },

        test_advanced_filter_toggles: function() {
            // Test that the accordion wrapper opens and closes in
            // response to the advanced filter check box.
            module.setup(this.configuration);
            // Simulate a click on the link to open the overlay.
            var link = Y.one('.menu-link-subscribe_to_bug_mail');
            link.simulate('click');
            var added_changed = Y.one('#added-or-changed');
            added_changed.set('checked', true);

            // Initially closed.
            var advanced_filter = Y.one('#advanced-filter');
            Assert.isFalse(advanced_filter.get('checked'));
            var accordion_wrapper = Y.one('#accordion-wrapper');
            this.wait(function() {
                Assert.isTrue(accordion_wrapper.hasClass('lazr-closed'));
            }, 500);
            // Opens when selected.
            advanced_filter.set('checked', true);
            this.wait(function() {
                Assert.isTrue(accordion_wrapper.hasClass('lazr-opened'));
            }, 500);
            // Closes when deselected.
            advanced_filter.set('checked', false);
            this.wait(function() {
                Assert.isTrue(accordion_wrapper.hasClass('lazr-closed'));
            }, 500);
        },

        test_importances_select_all_none: function() {
            // Test the select all/none functionality for the importances
            // accordion pane.
            module.setup(this.configuration);
            module._show_add_overlay(this.configuration);
            var checkboxes = Y.all('input[name="importances"]');
            var select_all = Y.one('#importances-selectors > a.select-all');
            var select_none = Y.one('#importances-selectors > a.select-none');
            Assert.isTrue(test_checked(checkboxes, true));
            // Simulate a click on the select_none control.
            select_none.simulate('click');
            Assert.isTrue(test_checked(checkboxes, false));
            // Simulate a click on the select_all control.
            select_all.simulate('click');
            Assert.isTrue(test_checked(checkboxes, true));
        },

        test_statuses_select_all_none: function() {
            // Test the select all/none functionality for the statuses
            // accordion pane.
            module.setup(this.configuration);
            module._show_add_overlay(this.configuration);
            var checkboxes = Y.all('input[name="statuses"]');
            var select_all = Y.one('#statuses-selectors > a.select-all');
            var select_none = Y.one('#statuses-selectors > a.select-none');
            Assert.isTrue(test_checked(checkboxes, true));
            // Simulate a click on the select_none control.
            select_none.simulate('click');
            Assert.isTrue(test_checked(checkboxes, false));
            // Simulate a click on the select_all control.
            select_all.simulate('click');
            Assert.isTrue(test_checked(checkboxes, true));
        }

    });
    suite.add(test_case);

    test_case = new Y.Test.Case({
        // Test the setup method.
        name: 'Structural Subscription error handling',

        _should: {
            error: {
                }
        },

        setUp: function() {
          // Monkeypatch LP to avoid network traffic and to allow
          // insertion of test data.
          this.original_lp = monkeypatch_LP();

          this.configuration = {
              content_box: content_box_id,
              lp_client: make_lp_client_stub()
          };

          this.content_node = create_test_node();
          Y.one('body').appendChild(this.content_node);
        },

        tearDown: function() {
            window.LP = this.original_lp;
            remove_test_node();
            delete this.content_node;
        },

        test_overlay_error_handling_adding: function() {
            // Verify that errors generated during adding of a filter are
            // displayed to the user.
            this.configuration.lp_client.named_post.fail = true;
            this.configuration.lp_client.named_post.args = [true, true];
            module.setup(this.configuration);
            module._show_add_overlay(this.configuration);
            // After the setup the overlay should be in the DOM.
            overlay = Y.one('#accordion-overlay');
            Assert.isNotNull(overlay);
            submit_button = Y.one('.yui3-lazr-formoverlay-actions button');
            submit_button.simulate('click');

            var error_box = Y.one('.yui3-lazr-formoverlay-errors');
            Assert.areEqual(
                'The following errors were encountered: ',
                error_box.get('text'));
        },

        test_spinner_removed_on_error: function() {
            // The spinner is removed from the submit button after a failure.
            this.configuration.lp_client.named_post.fail = true;
            this.configuration.lp_client.named_post.halt = true;
            this.configuration.lp_client.named_post.args = [true, true];
            module.setup(this.configuration);
            module._show_add_overlay(this.configuration);
            // After the setup the overlay should be in the DOM.
            overlay = Y.one('#accordion-overlay');
            Assert.isNotNull(overlay);
            submit_button = Y.one('.yui3-lazr-formoverlay-actions button');
            submit_button.simulate('click');
            // We are now looking at the state after the named post has been
            // called, but before it has returned with a failure.
            Assert.isTrue(submit_button.hasClass('spinner'));
            Assert.isFalse(submit_button.hasClass('lazr-pos'));
            // Now we resume the call to trigger the failure.
            this.configuration.lp_client.named_post.resume()

            Assert.isTrue(submit_button.hasClass('lazr-pos'));
            Assert.isFalse(submit_button.hasClass('spinner'));
        },

        test_overlay_error_handling_patching: function() {
            // Verify that errors generated during patching of a filter are
            // displayed to the user.
            var original_delete_filter = module._delete_filter;
            module._delete_filter = function() {};
            this.configuration.lp_client.patch.fail = true;
            this.configuration.lp_client.patch.args = [true, true];
            this.configuration.lp_client.named_post.args = [
                {'getAttrs': function() { return {}; }}];
            module.setup(this.configuration);
            module._show_add_overlay(this.configuration);
            // After the setup the overlay should be in the DOM.
            overlay = Y.one('#accordion-overlay');
            Assert.isNotNull(overlay);
            submit_button = Y.one('.yui3-lazr-formoverlay-actions button');
            submit_button.simulate('click');

            // Put this stubbed function back.
            module._delete_filter = original_delete_filter;

            var error_box = Y.one('.yui3-lazr-formoverlay-errors');
            Assert.areEqual(
                'The following errors were encountered: ',
                error_box.get('text'));
        }

    });
    suite.add(test_case);

    suite.add(new Y.Test.Case({
        name: 'Structural Subscription: deleting failed filters',

        _should: {error: {}},

        setUp: function() {
            // Monkeypatch LP to avoid network traffic and to allow
            // insertion of test data.
            this.original_lp = window.LP;
            window.LP = {
                links: {},
                cache: {}
            };
            LP.cache.context = {
                self_link: 'https://launchpad.dev/api/test_project'
            };
            LP.links.me = 'https://launchpad.dev/api/~someone';
            LP.cache.administratedTeams = [];
        },

        tearDown: function() {
            window.LP = this.original_lp;
        },

        test_delete_on_patch_failure: function() {
            // Creating a filter is a two step process.  First it is created
            // and then patched.  If the PATCH fails, then we should DELETE
            // the undifferentiated filter.

            // First we inject our own delete_filter implementation that just
            // tells us that it was called.
            var original_delete_filter = module._delete_filter;
            var delete_called = false;
            module._delete_filter = function() {
                delete_called = true;
            };
            var patch_failed = false;

            var TestBugFilter = function() {};
            TestBugFilter.prototype = {
                'getAttrs': function () {
                    return {};
                }
            };

            // Now we need an lp_client that will appear to succesfully create
            // the filter but then fail to patch it.
            var TestClient = function() {};
            TestClient.prototype = {
                'named_post': function (uri, operation_name, config) {
                    if (operation_name === 'addBugSubscriptionFilter') {
                        config.on.success(new TestBugFilter());
                    } else {
                        throw new Error('unexpected operation');
                    }
                },
                'patch': function(uri, representation, config, headers) {
                    config.on.failure(true, {'status':400});
                    patch_failed = true;
                }
            };
            module.lp_client = new TestClient();

            // OK, we're ready to add the bug filter and let the various
            // handlers be called.
            module._add_bug_filter(LP.links.me, 'this is a test');
            // Put some functions back.
            module._delete_filter = original_delete_filter;

            // Delete should have been called and the patch has failed.
            Assert.isTrue(delete_called);
            Assert.isTrue(patch_failed);
        }

    }));

    suite.add(new Y.Test.Case({
        name: 'Structural Subscription validate_config',

        _should: {
            error: {
                test_setup_config_none: new Error(
                    'Missing config for structural_subscription.'),
                test_setup_config_no_content_box: new Error(
                    'Structural_subscription configuration has undefined '+
                    'properties.')
                }
        },

        // Included in _should/error above.
        test_setup_config_none: function() {
            // The config passed to setup may not be null.
            module._validate_config();
        },

        // Included in _should/error above.
        test_setup_config_no_content_box: function() {
            // The config passed to setup must contain a content_box.
            module._validate_config({});
        }
    }));

    suite.add(new Y.Test.Case({
        name: 'Structural Subscription extract_form_data',

        // Verify that all the different values of the structural subscription
        // add/edit form are correctly extracted by the extract_form_data
        // function.

        _should: {
            error: {
                }
            },

        test_extract_description: function() {
            var form_data = {
                name: ['filter description'],
                events: [],
                filters: []
            };
            var patch_data = module._extract_form_data(form_data);
            Assert.areEqual(patch_data.description, form_data.name[0]);
        },

        test_extract_description_trim: function() {
            // Any leading or trailing whitespace is stripped from the
            // description.
            var form_data = {
                name: ['  filter description  '],
                events: [],
                filters: []
            };
            var patch_data = module._extract_form_data(form_data);
            Assert.areEqual('filter description', patch_data.description);
        },

        test_extract_chattiness_lifecycle: function() {
            var form_data = {
                name: [],
                events: ['added-or-closed'],
                filters: []
            };
            var patch_data = module._extract_form_data(form_data);
            Assert.areEqual(
                patch_data.bug_notification_level, 'Lifecycle');
        },

        test_extract_chattiness_discussion: function() {
            var form_data = {
                name: [],
                events: [],
                filters: []
            };
            var patch_data = module._extract_form_data(form_data);
            Assert.areEqual(
                patch_data.bug_notification_level, 'Details');
        },

        test_extract_chattiness_details: function() {
            var form_data = {
                name: [],
                events: [],
                filters: ['include-comments']
            };
            var patch_data = module._extract_form_data(form_data);
            Assert.areEqual(
                patch_data.bug_notification_level, 'Discussion');
        },

        test_extract_tags: function() {
            var form_data = {
                name: [],
                events: [],
                filters: ['advanced-filter'],
                tags: ['one two THREE'],
                tag_match: [''],
                importances: [],
                statuses: []
            };
            var patch_data = module._extract_form_data(form_data);
            // Note that the tags are converted to lower case.
            ArrayAssert.itemsAreEqual(
                patch_data.tags, ['one', 'two', 'three']);
        },

        test_extract_find_all_tags_true: function() {
            var form_data = {
                name: [],
                events: [],
                filters: ['advanced-filter'],
                tags: ['tag'],
                tag_match: ['match-all'],
                importances: [],
                statuses: []
            };
            var patch_data = module._extract_form_data(form_data);
            Assert.isTrue(patch_data.find_all_tags);
        },

        test_extract_find_all_tags_false: function() {
            var form_data = {
                name: [],
                events: [],
                filters: ['advanced-filter'],
                tags: ['tag'],
                tag_match: [],
                importances: [],
                statuses: []
            };
            var patch_data = module._extract_form_data(form_data);
            Assert.isFalse(patch_data.find_all_tags);
        },

        test_all_values_set: function() {
            // We need all the values to be set (even if empty) because
            // PATCH expects a set of changes to make and any unspecified
            // attributes will retain the previous value.
            var form_data = {
                name: [],
                events: [],
                filters: [],
                tags: ['tag'],
                tag_match: ['match-all'],
                importances: ['importance1'],
                statuses: ['status1']
            };
            var patch_data = module._extract_form_data(form_data);
            // Since advanced-filter isn't set, all the advanced values should
            // be empty/false despite the form values.
            Assert.isFalse(patch_data.find_all_tags);
            ArrayAssert.isEmpty(patch_data.tags);
            ArrayAssert.isEmpty(patch_data.importances);
            ArrayAssert.isEmpty(patch_data.statuses);
        }

    }));

    suite.add(new Y.Test.Case({
        name: 'Structural Subscription: add subcription workflow',

        _should: {error: {}},

        setUp: function() {
            var TestBugFilter = function() {};
            TestBugFilter.prototype = {
                'getAttrs': function () {
                    return {};
                }
            };
            // We need an lp_client that will appear to succesfully create the
            // bug filter.
            var TestClient = function() {};
            TestClient.prototype = {
                named_post: function (uri, operation_name, config) {
                    config.on.success(new TestBugFilter());
                    this.post_called = true;
                },
                patch: function(uri, representation, config, headers) {
                    config.on.success();
                    this.patch_called = true;
                },
                post_called: false,
                patch_called: false
            };

            this.original_lp = monkeypatch_LP();

            this.configuration = {
                content_box: content_box_id,
                lp_client: new TestClient()
            };
            this.content_node = create_test_node();
            Y.one('body').appendChild(this.content_node);
        },

        tearDown: function() {
            window.LP = this.original_lp;
            remove_test_node();
            delete this.content_node;
        },

        test_simple_add_workflow: function() {
            // Clicking on the "Subscribe to bug mail" link and then clicking
            // on the overlay form's "OK" button results in a filter being
            // created and PATCHed.
            module.setup(this.configuration);
            Y.one('a.menu-link-subscribe_to_bug_mail').simulate('click');
            Assert.isFalse(module.lp_client.post_called);
            Assert.isFalse(module.lp_client.patch_called);
            var button = Y.one('.yui3-lazr-formoverlay-actions button');
            Assert.areEqual(button.get('text'), 'OK');
            button.simulate('click');
            Assert.isTrue(module.lp_client.post_called);
            Assert.isTrue(module.lp_client.patch_called);
        },

        test_simple_add_workflow_canceled: function() {
            // Clicking on the "Subscribe to bug mail" link and then clicking
            // on the overlay form's cancel button results in no filter being
            // created or PATCHed.
            module.setup(this.configuration);
            Y.one('a.menu-link-subscribe_to_bug_mail').simulate('click');
            Assert.isFalse(module.lp_client.post_called);
            Assert.isFalse(module.lp_client.patch_called);
            var button = Y.one(
                '.yui3-lazr-formoverlay-actions button+button');
            Assert.areEqual(button.get('text'), 'Cancel');
            button.simulate('click');
            Assert.isFalse(module.lp_client.post_called);
            Assert.isFalse(module.lp_client.patch_called);
        }

    }));

    suite.add(new Y.Test.Case({
        name: 'Structural Subscription: edit subcription workflow',

        _should: {error: {}},

        setUp: function() {
            var TestBugFilter = function(data) {
                if (data !== undefined) {
                    this._data = data;
                } else {
                    this._data = {};
                }
            };
            TestBugFilter.prototype = {
                'getAttrs': function () {
                    return this._data;
                }
            };
            // We need an lp_client that will appear to succesfully create the
            // bug filter.
            var TestClient = function() {
                this.post_called = false;
                this.patch_called = false;
            };
            TestClient.prototype = {
                named_post: function (uri, operation_name, config) {
                    config.on.success(new TestBugFilter());
                    this.post_called = true;
                },
                patch: function(uri, representation, config, headers) {
                    config.on.success(new TestBugFilter(representation));
                    this.patch_called = true;
                }
            };

            this.original_lp = monkeypatch_LP();

            LP.cache.subscription_info = [{
                target_url: 'http://example.com',
                target_title:'Example project',
                filters: [{
                    filter: {
                        description: 'DESCRIPTION',
                        statuses: [],
                        importances: [],
                        tags: [],
                        find_all_tags: true,
                        bug_notification_level: 'Discussion',
                        self_link: 'http://example.com/a_filter'
                        },
                    can_mute: true,
                    is_muted: false,
                    subscriber_is_team: false,
                    subscriber_url: 'http://example.com/subscriber',
                    subscriber_title: 'Thidwick',
                    user_is_team_admin: false
                }]
            }];


            this.configuration = {
                content_box: content_box_id,
                lp_client: new TestClient()
            };
            this.content_node = create_test_node(true);
            Y.one('body').appendChild(this.content_node);
        },

        tearDown: function() {
            window.LP = this.original_lp;
            remove_test_node();
            delete this.content_node;
        },

        test_simple_edit_workflow: function() {
            module.setup_bug_subscriptions(this.configuration);

            // Editing a value via the edit link and dialog causes the
            // subscription list to reflect the new value.
            var label = Y.one('.filter-name span').get('text');
            Assert.isTrue(label.indexOf('DESCRIPTION') !== -1);

            // No PATCHing has happened yet.
            Assert.isFalse(module.lp_client.patch_called);

            // Click the edit link.
            Y.one('a.edit-subscription').simulate('click');

            // Set a new name (description) and click OK.
            Y.one('input[name="name"]').set('value', 'NEW VALUE');
            var button = Y.one('.yui3-lazr-formoverlay-actions button');
            Assert.areEqual(button.get('text'), 'OK');
            button.simulate('click');

            // Clicking OK resulted in the bug filter being PATCHed.
            Assert.isTrue(module.lp_client.patch_called);
            // And the new value is reflected in the subscription listing.
            label = Y.one('.filter-name span').get('text');
            Assert.isTrue(label.indexOf('NEW VALUE') !== -1);
        }

    }));

    suite.add(new Y.Test.Case({
        name: 'Structural Subscription: unsubscribing',

        _should: {error: {}},

        setUp: function() {
            var TestClient = function() {};
            this.original_lp = monkeypatch_LP();

            LP.cache.subscription_info = [{
                target_url: 'http://example.com',
                target_title:'Example project',
                filters: [{
                    filter: {
                        description: 'DESCRIPTION',
                        statuses: [],
                        importances: [],
                        tags: [],
                        find_all_tags: true,
                        bug_notification_level: 'Discussion',
                        self_link: 'http://example.com/a_filter'
                        },
                    can_mute: true,
                    is_muted: false,
                    subscriber_is_team: false,
                    subscriber_url: 'http://example.com/subscriber',
                    subscriber_title: 'Thidwick',
                    user_is_team_admin: false
                }]
            }];

            this.configuration = {
                content_box: content_box_id,
                lp_client: new TestClient()
            };
            this.content_node = create_test_node(true);
            Y.one('body').appendChild(this.content_node);
        },

        tearDown: function() {
            window.LP = this.original_lp;
            remove_test_node();
            delete this.content_node;
        },

        test_simple_unsubscribe: function() {
            // Clicking on the unsubscribe link will result in a DELETE being
            // sent and the filter description being removed.

            var DELETE_performed = false;
            // Fake a DELETE that succeeds.
            module._Y_io_hook = function (link, config) {
                DELETE_performed = true;
                config.on.success();
            };

            module.setup_bug_subscriptions(this.configuration);
            Y.one('a.delete-subscription').simulate('click');
            Assert.isTrue(DELETE_performed);
        },

        test_unsubscribe_spinner: function () {
            // The delete link shows a spinner while a deletion is requested.
            // if the deletion fails, the spinner is removed.
            var resume;
            module._Y_io_hook = function (link, config) {
                resume = function () {
                    config.on.failure(true, true);
                };
            };

            module.setup_bug_subscriptions(this.configuration);
            var delete_link = Y.one('a.delete-subscription');
            delete_link.simulate('click');
            Assert.isTrue(delete_link.hasClass('spinner'));
            Assert.isFalse(delete_link.hasClass('remove'));
            resume();
            Assert.isTrue(delete_link.hasClass('remove'));
            Assert.isFalse(delete_link.hasClass('spinner'));
        }

    }));

    suite.add(new Y.Test.Case({
        name: 'Add a subscription from +subscriptions page',

        setUp: function() {
            this.config = {
                content_box: content_box_id
            };
            this.content_box = create_test_node();
            Y.one('body').appendChild(this.content_box);
        },

        tearDown: function() {
            //delete this.configuration;
            remove_test_node();
            delete this.content_box;
        },

        _should: {
            error: {
                test_setup_subscription_link_none: new Error(
                    'Link to set as the pop-up link not found.')
            }
        },

        // Setting up a subscription link with no link in the DOM should fail.
        test_setup_subscription_link_none: function() {
            module.setup_subscription_link(this.config, "#link");
        },

        // Setting up a subscription link should unset the 'invisible-link',
        // and set 'visible-link' and 'js-action' CSS classes on the node.
        test_setup_subscription_link_classes: function() {
            var link = this.content_box.appendChild(
                Y.Node.create('<a>Link</a>'));
            link.set('id', 'link');
            link.addClass('invisible-link');
            module.setup_subscription_link(this.config, "#link");
            Assert.isFalse(link.hasClass('invisible-link'));
            Assert.isTrue(link.hasClass('visible-link'));
            Assert.isTrue(link.hasClass('js-action'));
        },

        // Setting up a subscription link creates an on-click handler
        // that calls up show_add_overlay with the passed in configuration.
        test_setup_subscription_link_behaviour: function() {
            var link = this.content_box.appendChild(
                Y.Node.create('<a>Link</a>'));
            link.set('id', 'link');

            // Track if the method was called.
            var called_method = false;

            // Keep the old module's _show_add_overlay, so we can override.
            old_show_add_overlay = module._show_add_overlay;
            var test = this;
            module._show_add_overlay = function(config) {
                module._show_add_overlay = old_show_add_overlay;
                Assert.areEqual(test.config, config);
                called_method = true;
            };
            module.setup_subscription_link(this.config, "#link");
            link.simulate('click');

            this.wait(function() {
                Assert.isTrue(called_method);
            }, 20);
        },

        // Success handler for adding a subscription does nothing in
        // the DOM if config.add_filter_description is not set.
        test_make_add_subscription_success_handler_nothing: function() {
            var success_handler =
                module._make_add_subscription_success_handler(this.config);
            var subs_list = this.content_box.appendChild(
                Y.Node.create('<div id="structural-subscriptions"></div>'));
            success_handler();
            // No sub-nodes have been created in the subs_list node.
            Assert.isTrue(subs_list.all('div.subscription-filter').isEmpty());
        },

        // Success handler for adding a subscription creates
        // a subscription listing if there's none and adds a filter to it.
        test_make_add_subscription_success_handler_empty_list: function() {
            this.config.add_filter_description = true;
            var success_handler =
                module._make_add_subscription_success_handler(this.config);
            var subs_list = this.content_box.appendChild(
                Y.Node.create('<div id="structural-subscriptions"></div>'));

            var form_data = {
                recipient: ["user"]
            };
            var target_info = {
                title: "MY TARGET",
                url: "http://target/" };
            window.LP.cache.target_info = target_info;
            var filter = {
                getAttrs: function() {
                    return {
                        importances: [],
                        statuses: [],
                        tags: [],
                        find_all_tags: true,
                        bug_notification_level: 'Discussion',
                        description: 'Filter name'
                    };
                }};

            success_handler(form_data, filter);
            // No sub-nodes have been created in the subs_list node.
            Assert.areEqual(
                1, subs_list.all('div.subscription-filter').size());
            var target_node = subs_list.one('#subscription-0>span>span');
            Assert.areEqual(
                'Subscriptions to MY TARGET',
                subs_list.one('#subscription-0>span>span').get('text'));
            var filter_node = subs_list.one('#subscription-filter-0');
            Assert.areEqual(
                'Your subscription: "Filter name"',
                filter_node.one('.filter-name').get('text'));
            this.config.add_filter_description = false;
            delete window.LP.cache.target_info;
        },

        // Success handler for adding a subscription adds a filter
        // to the subscription listing which already has filters listed.
        test_make_add_subscription_success_handler_with_filters: function() {
            this.config.add_filter_description = true;
            var success_handler =
                module._make_add_subscription_success_handler(this.config);
            var subs_list = this.content_box.appendChild(
                Y.Node.create('<div id="structural-subscriptions"></div>'));
            subs_list.appendChild('<div id="subscription-0"></div>')
                .appendChild('<div id="subscription-filter-0"'+
                             '     class="subscription-filter"></div>');
            var form_data = {
                recipient: ["user"]
            };
            var target_info = {
                title: "Subscription target",
                url: "http://target/" };
            window.LP.cache.target_info = target_info;
            var filter = {
                getAttrs: function() {
                    return {
                        importances: [],
                        statuses: [],
                        tags: [],
                        find_all_tags: true,
                        bug_notification_level: 'Discussion',
                        description: 'Filter name'
                    };
                }};

            success_handler(form_data, filter);
            // No sub-nodes have been created in the subs_list node.
            Assert.areEqual(
                2, subs_list.all('div.subscription-filter').size());
            this.config.add_filter_description = false;
            delete window.LP.cache.target_info;
        }
    }));

    // Lock, stock, and two smoking barrels.
    var handle_complete = function(data) {
        var status_node = Y.Node.create(
            '<p id="complete">Test status: complete</p>');
        Y.one('body').appendChild(status_node);
        };
    Y.Test.Runner.on('complete', handle_complete);
    Y.Test.Runner.add(suite);

    // The following two lines may be commented out for debugging but
    // must be restored before being checked in or the tests will fail
    // in the test runner.
    var console = new Y.Console({newestOnTop: false});
    console.render('#log');

    Y.on('domready', function() {
        Y.Test.Runner.run();
    });
});
