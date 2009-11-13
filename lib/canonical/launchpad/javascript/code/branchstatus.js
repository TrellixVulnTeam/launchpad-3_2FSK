/* Copyright 2009 Canonical Ltd.  This software is licensed under the
 * GNU Affero General Public License version 3 (see the file LICENSE).
 *
 * Code for handling the update of the branch status.
 *
 * @module branchstatus
 * @requires node, lazr.choiceedit, lp.client.plugins
 */

YUI.add('code.branchstatus', function(Y) {

Y.branchstatus = Y.namespace('code.branchstatus');

/*
 * Connect the branch status to the javascript events.
 */
Y.branchstatus.connect_status = function(conf) {

    var status_content = Y.get('#branch-details-status-value');

    if
        (conf.user_can_edit_status) {
        var status_choice_edit = new Y.ChoiceSource({
            contentBox: status_content,
            value: conf.status_value,
            title: 'Change status to',
            items: conf.status_widget_items});
        status_choice_edit.showError = function(err) {
            display_error(null, err);
        };
        status_choice_edit.on('save', function(e) {
            var cb = status_choice_edit.get('contentBox');
            Y.Array.each(conf.status_widget_items, function(item) {
                if (item.value == status_choice_edit.get('value')) {
                    cb.query('span').addClass(item.css_class);
                } else {
                    cb.query('span').removeClass(item.css_class);
                }
            });
        });
        status_choice_edit.plug({
            fn: Y.lp.client.plugins.PATCHPlugin, cfg: {
                patch: 'lifecycle_status',
                resource: conf.branch_path}});
        status_choice_edit.render();
    }
};

}, '0.1', {requires: ['node', 'lazr.choiceedit', 'lp.client.plugins']});
