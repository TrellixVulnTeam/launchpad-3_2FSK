# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

from canonical.config import config
from lp.answers.mail.handler import AnswerTrackerHandler
from lp.blueprints.mail.handler import SpecificationHandler
from lp.bugs.mail.handler import MaloneHandler
from lp.code.mail.codehandler import CodeHandler


class MailHandlers:
    """All the registered mail handlers."""

    def __init__(self):
        self._handlers = {
            config.launchpad.bugs_domain: MaloneHandler(),
            config.launchpad.specs_domain: SpecificationHandler(),
            config.answertracker.email_domain: AnswerTrackerHandler(),
            # XXX flacoste 2007-04-23 Backward compatibility for old domain.
            # We probably want to remove it in the future.
            'support.launchpad.net': AnswerTrackerHandler(),
            config.launchpad.code_domain: CodeHandler(),
            }

    def get(self, domain):
        """Return the handler for the given email domain.

        Return None if no such handler exists.
        """
        return self._handlers.get(domain)

    def add(self, domain, handler):
        """Adds a handler for a domain."""
        self._handlers[domain] = handler


mail_handlers = MailHandlers()
