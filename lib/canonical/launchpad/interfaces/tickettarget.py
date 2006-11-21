# Copyright 2005-2006 Canonical Ltd.  All rights reserved.

"""Interfaces for things which have Tickets."""

__metaclass__ = type

__all__ = [
    'ITicketTarget',
    'IManageSupportContacts',
    'ISearchTicketsForm',
    'TICKET_STATUS_DEFAULT_SEARCH',
    'get_supported_languages',
    ]

import sets

from zope.component import getUtility
from zope.interface import Interface
from zope.schema import Bool, Choice, List, Object, Set, TextLine

from canonical.launchpad import _
from canonical.launchpad.interfaces.language import ILanguageSet, ILanguage
from canonical.lp.dbschema import TicketSort, TicketStatus


TICKET_STATUS_DEFAULT_SEARCH = (
    TicketStatus.OPEN, TicketStatus.NEEDSINFO, TicketStatus.ANSWERED,
    TicketStatus.SOLVED)


def get_supported_languages(ticket_target):
    """Common implementation for ITicketTarget.getSupportedLanguages()."""
    assert ITicketTarget.providedBy(ticket_target)
    langs = set()
    for contact in ticket_target.support_contacts:
        for lang in contact.languages:
            # Ignore English and all its variants since we assume English is
            # supported (and thus we'll include it later) and we don't want to
            # confuse people by displayng a bunch of entries named English.
            if not lang.code.startswith('en'):
                langs.add(lang)
    langs.add(getUtility(ILanguageSet)['en'])
    return langs


class ITicketTarget(Interface):
    """An object that can have a new ticket created for  it."""

    def newTicket(owner, title, description, language=None, datecreated=None):
        """Create a new support request, or trouble ticket.

         A new ticket is created with status OPEN.

        The owner and all of the target support contacts will be subscribed
        to the ticket.

        :owner: An IPerson.
        :title: A string.
        :description: A string.
        :language: An ILanguage. If that parameter is omitted, the support
                request is assumed to be created in English.
        :datecreated:  A datetime object that will be used for the datecreated
                attribute. Defaults to canonical.database.constants.UTC_NOW.
        """

    def getTicket(ticket_id):
        """Return the ticket number, if it is applicable to this target.

        :ticket_id: A ticket id.

        If there is no such ticket number for this target, return None
        """

    def searchTickets(search_text=None, status=TICKET_STATUS_DEFAULT_SEARCH,
                      language=None, owner=None, sort=None):
        """Search the object's tickets.

        :search_text: A string that is matched against the ticket
        title and description. If None, the search_text is not included as
        a filter criteria.

        :status: One or a sequence of TicketStatus Items. If None or an empty
        sequence, the status is not included as a filter criteria.

        :language: An ILanguage or a sequence of ILanguage objects to match
        against the ticket's language. If None or an empty sequence,
        the language is not included as a filter criteria.

        :owner: The IPerson that created the ticket.

        :sort:  An attribute of TicketSort. If None, a default value is used.
        When there is a search_text value, the default is to sort by RELEVANCY,
        otherwise results are sorted NEWEST_FIRST.
        """

    def findSimilarTickets(title):
        """Return tickets similar to title.

        Return a list of ticket similar to the title provided. These tickets
        should be found using a fuzzy search. The list should be ordered
        from the most similar ticket to the least similar ticket.

        :title: A phrase
        """

    def addSupportContact(person):
        """Adds a new support contact.

        :person: An IPerson.

        Returns True if the person was added, False if he already was a
        support contact.
        """

    def removeSupportContact(person):
        """Removes a support contact.

        :person: An IPerson.

        Returns True if the person was removed, False if he isn't a
        support contact.
        """

    def getSupportedLanguages():
        """Return the set of languages spoken by at least one of this object's
        support contacts.

        A support contact is considered to speak a given language if that
        language is listed as one of his preferred languages.
        """

    support_contacts = List(
        title=_("Support Contacts"),
        description=_(
            "Persons that will be automatically subscribed to new support"
            " requests."),
        value_type=Choice(vocabulary="ValidPersonOrTeam"))

    ticket_languages = Set(
        title=_("Ticket Languages"),
        description=_( "The ILanguage used by all of this target's tickets."),
        value_type=Object(schema=ILanguage))



# These schemas are only used by browser/tickettarget.py and should really
# live there. See Bug #66950.
class IManageSupportContacts(Interface):
    """Schema for managing support contacts."""

    want_to_be_support_contact = Bool(
        title=_("Subscribe me automatically to new suppport request"),
        required=False)
    support_contact_teams = List(
        title=_("Team support contacts"),
        value_type=Choice(vocabulary="PersonActiveMembership"),
        required=False)


class ISearchTicketsForm(Interface):
    """Schema for the search ticket form."""

    search_text = TextLine(title=_('Search text:'), required=False)

    sort = Choice(title=_('Sort order:'), required=True,
                  vocabulary='TicketSort',
                  default=TicketSort.RELEVANCY)

    status = Set(title=_('Status:'), required=False,
                 value_type=Choice(vocabulary='TicketStatus'),
                 default=sets.Set(TICKET_STATUS_DEFAULT_SEARCH))
