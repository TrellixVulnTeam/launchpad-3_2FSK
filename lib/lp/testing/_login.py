# Copyright 2009-2010 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# We like global statements!
# pylint: disable-msg=W0602,W0603
__metaclass__ = type

__all__ = [
    'celebrity_logged_in',
    'login',
    'login_as',
    'login_celebrity',
    'login_person',
    'login_team',
    'logout',
    'is_logged_in',
    'person_logged_in',
    'run_with_login',
    'with_anonymous_login',
    'with_celebrity_logged_in',
    ]

from contextlib import contextmanager
import random

from zope.component import getUtility
from zope.security.management import endInteraction

from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.webapp.interaction import (
    ANONYMOUS, get_current_principal, setupInteractionByEmail,
    setupInteractionForPerson)
from canonical.launchpad.webapp.interfaces import ILaunchBag
from canonical.launchpad.webapp.servers import LaunchpadTestRequest
from canonical.launchpad.webapp.vhosts import allvhosts

from lp.services.utils import decorate_with


_logged_in = False

def is_logged_in():
    global _logged_in
    return _logged_in


def _test_login_impl(participation):
    # Common implementation of the test login wrappers.
    # It sets the global _logged_in flag and create a default
    # participation if None was specified.
    global _logged_in
    _logged_in = True

    if participation is None:
        # we use the main site as the host name.  This is a guess, to make
        # canonical_url produce a real-looking host name rather than
        # 127.0.0.1.
        participation = LaunchpadTestRequest(
            environ={'HTTP_HOST': allvhosts.configs['mainsite'].hostname,
                     'SERVER_URL': allvhosts.configs['mainsite'].rooturl})
    return participation


def login(email, participation=None):
    """Simulates a login, using the specified email.

    If the canonical.launchpad.ftests.ANONYMOUS constant is supplied
    as the email, you'll be logged in as the anonymous user.

    You can optionally pass in a participation to be used.  If no
    participation is given, a LaunchpadTestRequest is used.

    If the participation provides IPublicationRequest, it must implement
    setPrincipal(), otherwise it must allow setting its principal attribute.
    """

    participation = _test_login_impl(participation)
    setupInteractionByEmail(email, participation)


def login_person(person, participation=None):
    """Login the person with their preferred email."""
    if person is not None:
        # The login will fail even without this check, but this gives us a
        # nice error message, which can save time when debugging.
        if getattr(person, 'is_team', None):
            raise ValueError("Got team, expected person: %r" % (person,))
    participation = _test_login_impl(participation)
    setupInteractionForPerson(person, participation)


def _get_arbitrary_team_member(team):
    """Get an arbitrary member of 'team'.

    :param team: An `ITeam`.
    """
    # Set up the interaction.
    login(ANONYMOUS)
    return random.choice(list(team.allmembers))


def login_team(team, participation=None):
    """Login as a member of 'team'."""
    # This check isn't strictly necessary (it depends on the implementation of
    # _get_arbitrary_team_member), but this gives us a nice error message,
    # which can save time when debugging.
    if not team.is_team:
        raise ValueError("Got person, expected team: %r" % (team,))
    person = _get_arbitrary_team_member(team)
    login_person(person, participation=participation)
    return person


def login_as(person_or_team, participation=None):
    """Login as a person or a team.

    :param person_or_team: A person, a team, ANONYMOUS or None. None and
        ANONYMOUS are equivalent, and will log the person in as the anonymous
        user.
    """
    if person_or_team == ANONYMOUS:
        login_method = login
    elif person_or_team is None:
        login_method = login_person
    elif person_or_team.is_team:
        login_method = login_team
    else:
        login_method = login_person
    return login_method(person_or_team, participation=participation)


def login_celebrity(celebrity_name, participation=None):
    """Login as a celebrity."""
    login(ANONYMOUS)
    celebs = getUtility(ILaunchpadCelebrities)
    celeb = getattr(celebs, celebrity_name, None)
    if celeb is None:
        raise ValueError("No such celebrity: %r" % (celebrity_name,))
    return login_as(celeb, participation=participation)


def logout():
    """Tear down after login(...), ending the current interaction.

    Note that this is done automatically in
    canonical.launchpad.ftest.LaunchpadFunctionalTestCase's tearDown method so
    you generally won't need to call this.
    """
    global _logged_in
    _logged_in = False
    endInteraction()


def _with_login(login_method, identifier):
    """Make a context manager that runs with a particular log in."""
    current_person = getUtility(ILaunchBag).user
    current_principal = get_current_principal()
    login_method(identifier)
    try:
        yield
    finally:
        if current_principal is None:
            logout()
        else:
            login_person(current_person)


@contextmanager
def person_logged_in(person):
    """Make a context manager for running logged in as 'person'.

    :param person: A person, an account, a team or ANONYMOUS. If a team,
        will log in as an arbitrary member of that team.
    """
    return _with_login(login_as, person)


@contextmanager
def celebrity_logged_in(celebrity_name):
    """Make a context manager for running logged in as a celebrity."""
    return _with_login(login_celebrity, celebrity_name)


with_anonymous_login = decorate_with(person_logged_in, None)


def with_celebrity_logged_in(celebrity_name):
    """Decorate a function so that it's run with a celebrity logged in."""
    return decorate_with(celebrity_logged_in, celebrity_name)


def run_with_login(person, function, *args, **kwargs):
    """Run 'function' with 'person' logged in."""
    with person_logged_in(person):
        return function(*args, **kwargs)
