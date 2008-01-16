# Copyright 2004-2007 Canonical Ltd.  All rights reserved.

"""IBugMessage-related browser view classes."""

__metaclass__ = type
__all__ = [
    'BugMessageAddFormView',
    ]

from StringIO import StringIO

from canonical.launchpad.interfaces import IBugMessageAddForm
from canonical.launchpad.webapp import action, canonical_url
from canonical.launchpad.webapp import LaunchpadFormView


class BugMessageAddFormView(LaunchpadFormView):
    """Browser view class for adding a bug comment/attachment."""

    schema = IBugMessageAddForm
    initial_focus_widget = None

    @property
    def initial_values(self):
        return dict(subject=self.context.bug.followup_subject())

    @property
    def action_url(self):
        # override the default form action url to to go the addcomment
        # page for processing instead of the default which would be the
        # bug index page.
        return "%s/+addcomment" % canonical_url(self.context)

    def validate(self, data):

        # Ensure either a comment or filecontent was provide, but only
        # if no errors have already been noted.
        if len(self.errors) == 0:
            comment = data.get('comment', None)
            filecontent = data.get('filecontent', None)
            if not comment and not filecontent:
                self.addError("Either a comment or attachment "
                              "must be provided.")

    @action(u"Save Changes", name='save')
    def save_action(self, action, data):
        """Add the comment and/or attachment."""

        bug = self.context.bug

        # Subscribe to this bug if the checkbox exists and was selected
        if data.get('email_me'):
            bug.subscribe(self.user, self.user)

        # XXX: Bjorn Tillenius 2005-06-16:
        # Write proper FileUpload field and widget instead of this hack.
        file_ = self.request.form.get(self.widgets['filecontent'].name)

        message = None
        if data['comment'] or file_:
            message = bug.newMessage(subject=data['subject'],
                                     content=data['comment'],
                                     owner=self.user)

            # A blank comment with only a subect line is always added
            # when the user attaches a file, so show the add comment
            # feedback message only when the user actually added a
            # comment.
            if data['comment']:
                self.request.response.addNotification(
                    "Thank you for your comment.")

        if file_:

            # Slashes in filenames cause problems, convert them to dashes
            # instead.
            filename = file_.filename.replace('/', '-')

            # if no description was given use the converted filename
            file_description = None
            if 'attachment_description' in data:
                file_description = data['attachment_description']
            if not file_description:
                file_description = filename

            # Process the attachment.
            bug.addAttachment(
                owner=self.user, file_=StringIO(data['filecontent']),
                filename=filename, description=file_description,
                comment=message, is_patch=data['patch'])

            self.request.response.addNotification(
                "Attachment %(filename)s added to bug.", filename=filename)

        self.next_url = canonical_url(self.context)

    def shouldShowEmailMeWidget(self):
        """Should the subscribe checkbox be shown?"""
        return not self.context.bug.isSubscribed(self.user)
