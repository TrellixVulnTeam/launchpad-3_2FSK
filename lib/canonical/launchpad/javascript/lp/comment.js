YUI.add('lp.comment', function(Y) {

Y.lp = Y.namespace('lp');

var Comment = function () {
        Comment.superclass.constructor.apply(this, arguments);
};


Comment.NAME = 'comment';

Comment.ATTRS = {
};
Y.extend(Comment, Y.Widget, {

    /**
     * Initialize the Comment
     *
     * @method initializer
     */
    initializer: function() {
        this.submit_button = this.get_submit();
        this.comment_input = Y.get('[id="field.comment"]');
        this.lp_client = new LP.client.Launchpad();
        this.error_handler = new LP.client.ErrorHandler();
        this.error_handler.clearProgressUI = bind(this.clearProgressUI, this);
        this.error_handler.showError = bind(function (error_msg) {
            Y.lp.display_error(this.submit_button, error_msg);
        }, this);
        this.progress_message = Y.Node.create(
            '<span class="update-in-progress-message">Saving...</span>');
    },

    /**
     * Return the Submit button.
     *
     * This is provided so that it can be overridden in subclasses.
     *
     * @method get_submit
     */
    get_submit: function(){
        return Y.get('[id="field.actions.save"]');
    },
    /**
     * Implementation of Widget.renderUI.
     *
     * This redisplays the submit button, in case it has been hidden by
     * the web page.
     *
     * @method renderUI
     */
    renderUI: function() {
        this.submit_button.addClass('js-action');
        this.submit_button.setStyle('display', 'inline');
    },
    /**
     * Ensure that the widget's values are suitable for submission.
     *
     * The contents of the comment field must contain at least one
     * non-whitespace character.
     *
     * @method validate
     */
    validate: function() {
        return trim(this.comment_input.get('value')) !== '';
    },
    /**
     * Make the widget enabled or disabled.
     *
     * @method set_disabled
     * @param disabled A boolean, true if the widget is disabled.
     */
    set_disabled: function(disabled){
        this.comment_input.set('disabled', disabled);
    },
    /**
     * Add the widget's comment as a new comment, updating the display.
     *
     * @method add_comment
     * @param e An event
     */
    add_comment: function(e){
        e.halt();
        /* Don't try to add an empty comment. */
        if (!this.validate()) {
            return;
        }
        this.activateProgressUI('Saving...')
        this.post_comment(bind(function(message_entry) {
            this.get_comment_HTML(
                message_entry, bind(this.insert_comment_HTML, this));
        }, this));
    },
    /**
     * Post the comment to the Launchpad API
     *
     * @method post_comment
     * @param callback A callable to call if the post is successful.
     */
    post_comment: function(callback) {
        var config = {
            on: {
                success: callback,
                failure: this.error_handler.getFailureHandler()
            },
            parameters: {content: this.comment_input.get('value')}
        };
        this.lp_client.named_post(
            LP.client.cache.bug.self_link, 'newMessage', config);
    },
    /**
     * Retrieve the HTML of the specified message entry.
     *
     * @method get_comment_HTML
     * @param message_entry The comment to get the HTML for.
     * @param callback On success, call this with the HTML of the comment.
     */
    get_comment_HTML: function(message_entry, callback){
        var config = {
            on: {
                success: callback
            },
            accept: LP.client.XHTML
        };
        this.lp_client.get(message_entry.get('self_link'), config);
    },
    /**
     * Insert the specified HTML into the page.
     *
     * @method insert_comment_HTML
     * @param message_html The HTML of the comment to insert.
     */
    insert_comment_HTML: function(message_html) {
        var fieldset = Y.get('#add-comment-form');
        var comment = Y.Node.create(message_html);
        fieldset.get('parentNode').insertBefore(comment, fieldset);
        this.reset_contents();
        Y.lazr.anim.green_flash({node: comment}).run();
    },
    /**
     * Reset the widget to a blank state.
     *
     * @method reset_contents
     */
    reset_contents: function() {
          this.clearProgressUI();
          this.comment_input.set('value', '');
          this.syncUI();
    },
    activateProgressUI: function(message){
        this.progress_message.set('innerHTML', message)
        this.set_disabled(true);
        this.submit_button.get('parentNode').replaceChild(
            this.progress_message, this.submit_button);
    },
    /**
     * Stop indicating that a submission is in progress.
     *
     * @method clearProgressUI
     */
    clearProgressUI: function(){
          this.progress_message.get('parentNode').replaceChild(
              this.submit_button, this.progress_message);
          this.set_disabled(false);
    },
    /**
     * Implementation of Widget.bindUI: Bind events to methods.
     *
     * Key and mouse presses (e.g. mouse paste) call syncUI, in case the submit
     * button needs to be updated.  Clicking on the submit button invokes
     * add_comment.
     *
     * @method bindUI
     */
    bindUI: function(){
        this.comment_input.on('keyup', bind(this.syncUI, this));
        this.comment_input.on('mouseup', bind(this.syncUI, this));
        this.submit_button.on('click', bind(this.add_comment, this));
    },
    /**
     * Implementation of Widget.syncUI: Update appearance according to state.
     *
     * This just updates the submit button.
     *
     * @method syncUI
     */
    syncUI: function(){
        this.submit_button.set('disabled', !this.validate());
    }
});

Y.lp.Comment = Comment;

var CodeReviewComment = function(){
        CodeReviewComment.superclass.constructor.apply(this, arguments);
};
CodeReviewComment.NAME = 'codereviewcomment';


Y.extend(CodeReviewComment, Comment, {
    /**
     * Initialize the CodeReviewComment
     *
     * @method initializer
     */
    initializer: function() {
        this.vote_input = Y.get('[id="field.vote"]');
        this.review_type = Y.get('[id="field.review_type"]');
        this.in_reply_to = null;
    },
    /**
     * Return the Submit button.
     *
     * @method get_submit
     */
    get_submit: function(){
        return Y.get('[id="field.actions.add"]');
    },
    /**
     * Return the vote value selected, or null if none is selected.
     *
     * @method get_vote
     */
    get_vote: function() {
        var selected_idx = this.vote_input.get('selectedIndex');
        var selected = this.vote_input.get('options').item(selected_idx);
        if (selected.get('value') === ''){
            return null;
        }
        return selected.get('innerHTML');
    },
    /**
     * Ensure that the widget's values are suitable for submission.
     *
     * This allows the vote to be submitted, even when no text is specified
     * for the comment.
     *
     * @method validate
     */
    validate: function(){
        if (this.get_vote() !== null) {
            return true;
        }
        return CodeReviewComment.superclass.validate.apply(this);
    },
    /**
     * Make the widget enabled or disabled.
     *
     * @method set_disabled
     * @param disabled A boolean, true if the widget is disabled.
     */
    set_disabled: function(disabled){
        CodeReviewComment.superclass.set_disabled.call(this, disabled);
        this.vote_input.set('disabled', disabled);
        this.review_type.set('disabled', disabled);
    },
    /**
     * Post the comment to the Launchpad API
     *
     * @method post_comment
     * @param callback A callable to call if the post is successful.
     */
    post_comment: function(callback) {
        var config = {
            on: {
                success: callback,
                failure: this.error_handler.getFailureHandler()
            },
            parameters: {
                content: this.comment_input.get('value'),
                subject: '',
                review_type: this.review_type.get('value'),
                vote: this.get_vote(),
                parent: this.in_reply_to.get('self_link')
            }
        };
        this.lp_client.named_post(
            LP.client.cache.context.self_link, 'createComment', config);
    },
    /**
     * Retrieve the HTML of the specified message entry.
     *
     * @method get_comment_HTML
     * @param message_entry The comment to get the HTML for.
     * @param callback On success, call this with the HTML of the comment.
     */
    get_comment_HTML: function(comment_entry, callback) {
        fragment_url = 'comments/' + comment_entry.get('id') + '/+fragment';
        Y.io(fragment_url, {
            on: {
                success: function(id, response){
                    callback(response.responseText);
                },
                failure: this.error_handler.getFailureHandler()
            }
        });
    },
    reply_clicked: function(e){
        e.halt();
        reply_link = e.target.get('href')
        root_url = reply_link.substr(0, reply_link.length - '+reply'.length)
        object_url = root_url.replace('code.launchpad.dev', 'code.launchpad.dev/api/beta')
        this.activateProgressUI('Loading...')
        window.scrollTo(0, Y.get('label [for=field.vote]').getY());
        this.lp_client.get(object_url, {
            on: {
                success: bind(function(comment){
                    this.set_in_reply_to(comment)
                    this.clearProgressUI();
                    this.syncUI();
                }, this),
                failure: this.error_handler.getFailureHandler()
            }
        });

    },
    set_in_reply_to: function(comment) {
        this.in_reply_to = comment
        this.comment_input.set('value', comment.get('as_quoted_email'));
    },
    /**
     * Reset the widget to a blank state.
     *
     * @method reset_contents
     */
    reset_contents: function() {
          this.review_type.set('value', '');
          this.vote_input.set('selectedIndex', 0);
          this.in_reply_to = null;
          CodeReviewComment.superclass.reset_contents.apply(this);
    },
    /**
     * Insert the specified HTML into the page.
     *
     * @method insert_comment_HTML
     * @param message_html The HTML of the comment to insert.
     */
    insert_comment_HTML: function(message_html){
        var conversation = Y.get('[id=conversation]');
        var comment = Y.Node.create(message_html);
        conversation.appendChild(comment);
        this.reset_contents();
        Y.lazr.anim.green_flash({node: comment}).run();
    },
    renderUI: function() {
        CodeReviewComment.superclass.renderUI.apply(this);
        Y.get('#inline-add-comment').setStyle('display', 'block');
    },
    /**
     * Implementation of Widget.bindUI: Bind events to methods.
     *
     * In addition to Comment behaviour, mouseups and keyups on the vote and
     * review type cause a sync.
     *
     * @method bindUI
     */
    bindUI: function() {
        CodeReviewComment.superclass.bindUI.apply(this);
        this.vote_input.on('mouseup', bind(this.syncUI, this));
        this.review_type.on('keyup', bind(this.syncUI, this));
        this.review_type.on('mouseup', bind(this.syncUI, this));
        Y.all('a.menu-link-reply').on('click', bind(this.reply_clicked, this))
    },
    /**
     * Implementation of Widget.syncUI: Update appearance according to state.
     *
     * This enables and disables the review type, in addition to Comment
     * behaviour.
     *
     * @method syncUI
     */
    syncUI: function() {
        CodeReviewComment.superclass.syncUI.apply(this);
        var review_type_disabled = (this.get_vote() === null);
        this.review_type.set('disabled', review_type_disabled);
    }
});
Y.lp.CodeReviewComment = CodeReviewComment;

}, '0.1' ,{requires:['oop', 'io', 'widget', 'node', 'lp.client.plugins', 'lp.errors']});
