# Copyright 2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version (see the file LICENSE).

"""Common classes to support bug roles."""

__metaclass__ = type

__all__ = [
    'BugRoleMixin',
    ]

from canonical.launchpad.webapp.menu import structured
from canonical.launchpad.webapp.publisher import canonical_url


class BugRoleMixin:

    INVALID_PERSON = object()
    OTHER_USER = object()
    OTHER_TEAM = object()
    OK = object()

    def _getFieldState(self, field_name, data):
        """Return the enum that summarises the field state."""
        # The field_name will not be in the data if the user did not enter
        # a person in the ValidPersonOrTeam vocabulary.
        if field_name not in data:
            return self.INVALID_PERSON
        role = data[field_name]
        user = self.user
        # The user may assign the role to None, himself, or a team he admins.
        if role is None or self.context.userCanAlterSubscription(role, user):
            return self.OK
        # The user is not an admin of the team, or he entered another user.
        if role.isTeam():
            return self.OTHER_TEAM
        else:
            return self.OTHER_USER

    def validateBugSupervisor(self, data):
        """Validates the new bug supervisor.

        Verify that the value is None, the user, or a team he administers,
        otherwise, set a field error.
        """
        field_state = self._getFieldState('bug_supervisor', data)
        if field_state is self.INVALID_PERSON:
            error = (
                'You must choose a valid person or team to be the '
                'bug supervisor for %s.' % self.context.displayname)
        elif field_state is self.OTHER_TEAM:
            supervisor = data['bug_supervisor']
            team_url = canonical_url(
                supervisor, rootsite='mainsite', view_name='+members')
            error = structured(
                'You cannot set %(team)s as the bug supervisor for '
                '%(target)s because you are not an administrator of that '
                'team.<br />If you believe that %(team)s should be the '
                'bug supervisor for %(target)s, notify one of the '
                '<a href="%(url)s">%(team)s administrators</a>. See '
                '<a href="https://help.launchpad.net/BugSupervisors">'
                'the help wiki</a> for information about setting a bug '
                'supervisor.',
                team=supervisor.displayname,
                target=self.context.displayname,
                url=team_url)
        elif field_state is self.OTHER_USER:
            error = structured(
                'You cannot set another person as the bug supervisor for '
                '%(target)s.<br />See '
                '<a href="https://help.launchpad.net/BugSupervisors">'
                'the help wiki</a> for information about setting a bug '
                'supervisor.',
                target=self.context.displayname)
        else:
            # field_state is self.OK.
            return
        self.setFieldError('bug_supervisor', error)

    def changeBugSupervisor(self, bug_supervisor):
        self.context.setBugSupervisor(bug_supervisor, self.user)
        if bug_supervisor is not None:
            self.request.response.addNotification(structured(
                'Successfully changed the bug supervisor to '
                '<a href="%(supervisor_url)s">%(displayname)s</a>.'
                '<br /><a href="%(supervisor_url)s">%(displayname)s</a> '
                'has also been subscribed to bug notifications for '
                '%(targetname)s.<br />You can '
                '<a href="%(targeturl)s/+subscribe">change the '
                'subscriptions</a> for %(targetname)s at any time.',
                supervisor_url=canonical_url(bug_supervisor),
                displayname=bug_supervisor.displayname,
                targetname=self.context.displayname,
                targeturl=canonical_url(self.context)))

    def validateSecurityContact(self, data):
        """Validates the new security contact.

        Verify that the value is None, the user, or a team he administers,
        otherwise, set a field error.
        """
        field_state = self._getFieldState('security_contact', data)
        if field_state is self.INVALID_PERSON:
            error = (
                'You must choose a valid person or team to be the '
                'security contact for %s.' % self.context.displayname)
        elif field_state is self.OTHER_TEAM:
            supervisor = data['security_contact']
            team_url = canonical_url(
                supervisor, rootsite='mainsite', view_name='+members')
            error = structured(
                'You cannot set %(team)s as the security contact for '
                '%(target)s because you are not an administrator of that '
                'team.<br />If you believe that %(team)s should be the '
                'security contact for %(target)s, notify one of the '
                '<a href="%(url)s">%(team)s administrators</a>.',
                team=supervisor.displayname,
                target=self.context.displayname,
                url=team_url)
        elif field_state is self.OTHER_USER:
            error = structured(
                'You cannot set another person as the security contact for '
                '%(target)s.', target=self.context.displayname)
        else:
            # field_state is self.OK.
            return
        self.setFieldError('security_contact', error)
