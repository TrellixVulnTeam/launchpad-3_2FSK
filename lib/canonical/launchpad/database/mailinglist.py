# Copyright 2007-2008 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0611,W0212

__metaclass__ = type

__all__ = [
    'HeldMessageDetails',
    'MailingList',
    'MailingListSet',
    'MailingListSubscription',
    'MessageApproval',
    'MessageApprovalSet',
    ]


from email import message_from_string
from email.Header import decode_header, make_header
from itertools import repeat
from socket import getfqdn
from string import Template

from storm.expr import And, LeftJoin
from storm.store import Store

from sqlobject import ForeignKey, StringCol
from zope.component import getUtility, queryAdapter
from zope.event import notify
from zope.interface import implements, providedBy
from zope.security.proxy import removeSecurityProxy

from canonical.cachedproperty import cachedproperty
from canonical.config import config
from canonical.database.constants import DEFAULT, UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.launchpad import _
from canonical.launchpad.database.account import Account
from canonical.launchpad.database.emailaddress import EmailAddress
from canonical.launchpad.database.person import Person
from canonical.launchpad.database.teammembership import TeamParticipation
from canonical.launchpad.event import (
    SQLObjectCreatedEvent, SQLObjectModifiedEvent)
from canonical.launchpad.interfaces.emailaddress import (
    EmailAddressStatus, IEmailAddressSet)
from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from canonical.launchpad.interfaces.mailinglist import (
    CannotChangeSubscription, CannotSubscribe, CannotUnsubscribe,
    IHeldMessageDetails, IMailingList, IMailingListSet,
    IMailingListSubscription, IMessageApproval, IMessageApprovalSet,
    MailingListStatus, PURGE_STATES, PostedMessageStatus, UnsafeToPurge)
from canonical.launchpad.interfaces.account import AccountStatus
from canonical.launchpad.validators.person import validate_public_person
from canonical.launchpad.webapp.snapshot import Snapshot
from canonical.lazr.interfaces.objectprivacy import IObjectPrivacy


class MessageApproval(SQLBase):
    """A held message."""

    implements(IMessageApproval)

    message = ForeignKey(
        dbName='message', foreignKey='Message',
        notNull=True)

    posted_by = ForeignKey(
        dbName='posted_by', foreignKey='Person',
        storm_validator=validate_public_person,
        notNull=True)

    posted_message = ForeignKey(
        dbName='posted_message', foreignKey='LibraryFileAlias',
        notNull=True)

    posted_date = UtcDateTimeCol(notNull=True, default=UTC_NOW)

    mailing_list = ForeignKey(
        dbName='mailing_list', foreignKey='MailingList',
        notNull=True)

    status = EnumCol(enum=PostedMessageStatus,
                     default=PostedMessageStatus.NEW,
                     notNull=True)

    disposed_by = ForeignKey(
        dbName='disposed_by', foreignKey='Person',
        storm_validator=validate_public_person,
        default=None)

    disposal_date = UtcDateTimeCol(default=None)

    @property
    def message_id(self):
        """See `IMessageApproval`."""
        return self.message.rfc822msgid

    def approve(self, reviewer):
        """See `IMessageApproval`."""
        self.disposed_by = reviewer
        self.disposal_date = UTC_NOW
        self.status = PostedMessageStatus.APPROVAL_PENDING

    def reject(self, reviewer):
        """See `IMessageApproval`."""
        self.disposed_by = reviewer
        self.disposal_date = UTC_NOW
        self.status = PostedMessageStatus.REJECTION_PENDING

    def discard(self, reviewer):
        """See `IMessageApproval`."""
        self.disposed_by = reviewer
        self.disposal_date = UTC_NOW
        self.status = PostedMessageStatus.DISCARD_PENDING

    def acknowledge(self):
        """See `IMessageApproval`."""
        if self.status == PostedMessageStatus.APPROVAL_PENDING:
            self.status = PostedMessageStatus.APPROVED
        elif self.status == PostedMessageStatus.REJECTION_PENDING:
            self.status = PostedMessageStatus.REJECTED
        elif self.status == PostedMessageStatus.DISCARD_PENDING:
            self.status = PostedMessageStatus.DISCARDED
        else:
            raise AssertionError('Not an acknowledgeable state: %s' %
                                 self.status)


class MailingList(SQLBase):
    """The mailing list for a team.

    Teams may have at most one mailing list, and a mailing list is associated
    with exactly one team.  This table manages the state changes that a team
    mailing list can go through, and it contains information that will be used
    to instruct Mailman how to create, delete, and modify mailing lists (via
    XMLRPC).
    """

    implements(IMailingList)

    team = ForeignKey(
        dbName='team', foreignKey='Person',
        notNull=True)

    registrant = ForeignKey(
        dbName='registrant', foreignKey='Person',
        storm_validator=validate_public_person, notNull=True)

    date_registered = UtcDateTimeCol(notNull=True, default=DEFAULT)

    reviewer = ForeignKey(
        dbName='reviewer', foreignKey='Person',
        storm_validator=validate_public_person, default=None)

    date_reviewed = UtcDateTimeCol(notNull=False, default=None)

    date_activated = UtcDateTimeCol(notNull=False, default=None)

    status = EnumCol(enum=MailingListStatus,
                     default=MailingListStatus.REGISTERED,
                     notNull=True)

    # Use a trailing underscore because SQLObject/importfascist doesn't like
    # the typical leading underscore.
    welcome_message_ = StringCol(default=None, dbName='welcome_message')

    @property
    def address(self):
        """See `IMailingList`."""
        if config.mailman.build_host_name:
            host_name = config.mailman.build_host_name
        else:
            host_name = getfqdn()
        return '%s@%s' % (self.team.name, host_name)

    @property
    def archive_url(self):
        """See `IMailingList`."""
        # These represent states that can occur at or after a mailing list has
        # been activated.  Once it's been activated, a mailing list could have
        # an archive.
        if self.status not in [MailingListStatus.ACTIVE,
                               MailingListStatus.INACTIVE,
                               MailingListStatus.MODIFIED,
                               MailingListStatus.UPDATING,
                               MailingListStatus.DEACTIVATING,
                               MailingListStatus.MOD_FAILED]:
            return None
        # There could be an archive, return its url.
        template = Template(config.mailman.archive_url_template)
        return template.safe_substitute(team_name=self.team.name)

    def __repr__(self):
        return '<MailingList for team "%s"; status=%s at %#x>' % (
            self.team.name, self.status.name, id(self))

    def review(self, reviewer, status):
        """See `IMailingList`."""
        # Only mailing lists which are in the REGISTERED state may be
        # reviewed.  This is the state for newly requested mailing lists.
        assert self.status == MailingListStatus.REGISTERED, (
            'Only unreviewed mailing lists may be reviewed')
        # A registered mailing list may only transition to either APPROVED or
        # DECLINED state.
        assert status in (MailingListStatus.APPROVED,
                          MailingListStatus.DECLINED), (
            'Reviewed lists may only be approved or declined')
        # The reviewer must be a Launchpad administrator.
        assert reviewer is not None and reviewer.hasParticipationEntryFor(
            getUtility(ILaunchpadCelebrities).mailing_list_experts), (
            'Reviewer must be a member of the Mailing List Experts team')
        self.reviewer = reviewer
        self.status = status
        self.date_reviewed = UTC_NOW

    def startConstructing(self):
        """See `IMailingList`."""
        assert self.status == MailingListStatus.APPROVED, (
            'Only approved mailing lists may be constructed')
        self.status = MailingListStatus.CONSTRUCTING

    def startUpdating(self):
        """See `IMailingList`."""
        assert self.status == MailingListStatus.MODIFIED, (
            'Only modified mailing lists may be updated')
        self.status = MailingListStatus.UPDATING

    def transitionToStatus(self, target_state):
        """See `IMailingList`."""
        # State: From CONSTRUCTING to either ACTIVE or FAILED
        if self.status == MailingListStatus.CONSTRUCTING:
            assert target_state in (MailingListStatus.ACTIVE,
                                    MailingListStatus.FAILED), (
                'target_state result must be active or failed')
        # State: From UPDATING to either ACTIVE or MOD_FAILED
        elif self.status == MailingListStatus.UPDATING:
            assert target_state in (MailingListStatus.ACTIVE,
                                    MailingListStatus.MOD_FAILED), (
                'target_state result must be active or mod_failed')
        # State: From DEACTIVATING to INACTIVE or MOD_FAILED
        elif self.status == MailingListStatus.DEACTIVATING:
            assert target_state in (MailingListStatus.INACTIVE,
                                    MailingListStatus.MOD_FAILED), (
                'target_state result must be inactive or mod_failed')
        else:
            raise AssertionError(
                'Not a valid state transition: %s -> %s'
                % (self.status, target_state))
        self.status = target_state
        if target_state == MailingListStatus.ACTIVE:
            self._setAndNotifyDateActivated()
            email_set = getUtility(IEmailAddressSet)
            email = email_set.getByEmail(self.address)
            if email is None:
                email = email_set.new(self.address, self.team)
            if email.status in [EmailAddressStatus.NEW,
                                EmailAddressStatus.OLD]:
                # Without this conditional, if the mailing list is the
                # contact method
                # (email.status==EmailAddressStatus.PREFERRED), and a
                # user changes the mailing list configuration, then
                # when the list status goes back to ACTIVE the email
                # will go from PREFERRED to VALIDATED and the list
                # will stop being the contact method.
                # We also need to remove the email's security proxy because
                # this method will be called via the internal XMLRPC rather
                # than as a response to a user action.
                removeSecurityProxy(email).status = (
                    EmailAddressStatus.VALIDATED)
            assert email.personID == self.teamID, (
                "Email already associated with another team.")

    def _setAndNotifyDateActivated(self):
        """Set the date_activated field and fire a
        SQLObjectModified event.

        The date_activated field is only set once - repeated calls
        will not change the field's value.

        Similarly, the modification event only fires the first time
        that the field is set.
        """
        if self.date_activated is not None:
            return

        old_mailinglist = Snapshot(self, providing=providedBy(self))
        self.date_activated = UTC_NOW
        notify(SQLObjectModifiedEvent(
                self,
                object_before_modification=old_mailinglist,
                edited_fields=['date_activated']))

    def deactivate(self):
        """See `IMailingList`."""
        assert self.status == MailingListStatus.ACTIVE, (
            'Only active mailing lists may be deactivated')
        self.status = MailingListStatus.DEACTIVATING
        email = getUtility(IEmailAddressSet).getByEmail(self.address)
        if email == self.team.preferredemail:
            self.team.setContactAddress(None)
        email.status = EmailAddressStatus.NEW

    def reactivate(self):
        """See `IMailingList`."""
        assert self.status == MailingListStatus.INACTIVE, (
            'Only inactive mailing lists may be reactivated')
        self.status = MailingListStatus.APPROVED

    def cancelRegistration(self):
        """See `IMailingList`."""
        assert self.status == MailingListStatus.REGISTERED, (
            "Only mailing lists in the REGISTERED state can be canceled.")
        self.destroySelf()

    @property
    def is_public(self):
        """See `IMailingList`."""
        return not queryAdapter(self.team, IObjectPrivacy).is_private

    @property
    def is_usable(self):
        """See `IMailingList`."""
        return self.status in [MailingListStatus.ACTIVE,
                               MailingListStatus.MODIFIED,
                               MailingListStatus.UPDATING,
                               MailingListStatus.MOD_FAILED]

    def _get_welcome_message(self):
        return self.welcome_message_

    def _set_welcome_message(self, text):
        if self.status == MailingListStatus.REGISTERED:
            # Do nothing because the status does not change.  When setting the
            # welcome_message on a newly registered mailing list the XMLRPC
            # layer will essentially tell Mailman to initialize this attribute
            # at list construction time.  It is enough to just set the
            # database attribute to properly notify Mailman what to do.
            pass
        elif self.is_usable:
            # Transition the status to MODIFIED so that the XMLRPC layer knows
            # that it has to inform Mailman that a mailing list attribute has
            # been changed on an active list.
            self.status = MailingListStatus.MODIFIED
        else:
            raise AssertionError(
                'Only registered or usable mailing lists may be modified')
        self.welcome_message_ = text

    welcome_message = property(_get_welcome_message, _set_welcome_message)

    def getSubscription(self, person):
        """See `IMailingList`."""
        return MailingListSubscription.selectOneBy(person=person,
                                                   mailing_list=self)

    def getSubscribers(self):
        """See `IMailingList`."""
        store = Store.of(self)
        results = store.find(Person,
                             MailingListSubscription.person == Person.id,
                             MailingListSubscription.mailing_list == self)
        return results.order_by(Person.displayname)

    def subscribe(self, person, address=None):
        """See `IMailingList`."""
        if not self.is_usable:
            raise CannotSubscribe('Mailing list is not usable: %s' %
                                  self.team.displayname)
        if person.isTeam():
            raise CannotSubscribe('Teams cannot be mailing list members: %s' %
                                  person.displayname)
        if address is not None and address.personID != person.id:
            raise CannotSubscribe('%s does not own the email address: %s' %
                                  (person.displayname, address.email))
        subscription = self.getSubscription(person)
        if subscription is not None:
            raise CannotSubscribe('%s is already subscribed to list %s' %
                                  (person.displayname, self.team.displayname))
        # Add the subscription for this person to this mailing list.
        MailingListSubscription(
            person=person,
            mailing_list=self,
            email_address=address)

    def unsubscribe(self, person):
        """See `IMailingList`."""
        subscription = self.getSubscription(person)
        if subscription is None:
            raise CannotUnsubscribe(
                '%s is not a member of the mailing list: %s' %
                (person.displayname, self.team.displayname))
        subscription.destroySelf()

    def changeAddress(self, person, address):
        """See `IMailingList`."""
        subscription = self.getSubscription(person)
        if subscription is None:
            raise CannotChangeSubscription(
                '%s is not a member of the mailing list: %s' %
                (person.displayname, self.team.displayname))
        if address is not None and address.person != person:
            raise CannotChangeSubscription(
                '%s does not own the email address: %s' %
                (person.displayname, address.email))
        subscription.email_address = address

    def getSubscribedAddresses(self):
        """See `IMailingList`."""
        store = Store.of(self)
        # In order to handle the case where the preferred email address is
        # used (i.e. where MailingListSubscription.email_address is NULL), we
        # need to UNION, those using a specific address and those using the
        # preferred address.
        tables = (
            EmailAddress,
            LeftJoin(Account, Account.id == EmailAddress.accountID),
            LeftJoin(MailingListSubscription,
                     MailingListSubscription.personID
                     == EmailAddress.personID),
            # pylint: disable-msg=C0301
            LeftJoin(MailingList,
                     MailingList.id == MailingListSubscription.mailing_listID),
            LeftJoin(TeamParticipation,
                     TeamParticipation.personID
                     == MailingListSubscription.personID),
            )
        preferred = store.using(*tables).find(
            EmailAddress,
            And(MailingListSubscription.mailing_list == self,
                TeamParticipation.team == self.team,
                MailingList.status != MailingListStatus.INACTIVE,
                MailingListSubscription.email_addressID == None,
                EmailAddress.status == EmailAddressStatus.PREFERRED,
                Account.status == AccountStatus.ACTIVE))
        tables = (
            EmailAddress,
            LeftJoin(Account, Account.id == EmailAddress.accountID),
            LeftJoin(MailingListSubscription,
                     MailingListSubscription.email_addressID
                     == EmailAddress.id),
            # pylint: disable-msg=C0301
            LeftJoin(MailingList,
                     MailingList.id == MailingListSubscription.mailing_listID),
            LeftJoin(TeamParticipation,
                     TeamParticipation.personID
                     == MailingListSubscription.personID),
            )
        explicit = store.using(*tables).find(
            EmailAddress,
            And(MailingListSubscription.mailing_list == self,
                TeamParticipation.team == self.team,
                MailingList.status != MailingListStatus.INACTIVE,
                Account.status == AccountStatus.ACTIVE))
        # Union the two queries together to give us the complete list of email
        # addresses allowed to post.  Note that while we're retrieving both
        # the EmailAddress and Person records, this method is defined as only
        # returning EmailAddresses.  The reason why we include the Person in
        # the query is because the consumer of this method will access
        # email_address.person.displayname, so the prejoin to Person is
        # critical to acceptable performance.  Indeed, without the prejoin, we
        # were getting tons of timeout OOPSes.  See bug 259440.
        for email_address in preferred.union(explicit):
            yield email_address

    def getSenderAddresses(self):
        """See `IMailingList`."""
        store = Store.of(self)
        # Here are two useful conveniences for the queries below.
        email_address_statuses = (
            EmailAddressStatus.VALIDATED,
            EmailAddressStatus.PREFERRED)
        message_approval_statuses = (
            PostedMessageStatus.APPROVED,
            PostedMessageStatus.APPROVAL_PENDING)
        # First, we need to find all the members of the team this mailing list
        # is associated with.  Find all of their validated and preferred email
        # addresses of those team members.  Every one of those email addresses
        # are allowed to post to the mailing list.
        tables = (
            Person,
            LeftJoin(Account, Account.id == Person.accountID),
            LeftJoin(EmailAddress, EmailAddress.personID == Person.id),
            LeftJoin(TeamParticipation,
                     TeamParticipation.personID == Person.id),
            LeftJoin(MailingList,
                     MailingList.teamID == TeamParticipation.teamID),
            )
        team_members = store.using(*tables).find(
            (EmailAddress, Person),
            And(TeamParticipation.team == self.team,
                MailingList.status != MailingListStatus.INACTIVE,
                Person.teamowner == None,
                EmailAddress.status.is_in(email_address_statuses),
                Account.status == AccountStatus.ACTIVE,
                ))
        # Second, find all of the email addresses for all of the people who
        # have been explicitly approved for posting to this mailing list.
        # This occurs as part of first post moderation, but since they've
        # already been approved for this list, we don't need to wait for three
        # global approvals.
        tables = (
            Person,
            LeftJoin(Account, Account.id == Person.accountID),
            LeftJoin(EmailAddress, EmailAddress.personID == Person.id),
            LeftJoin(MessageApproval,
                     MessageApproval.posted_byID == Person.id),
            )
        approved_posters = store.using(*tables).find(
            (EmailAddress, Person),
            And(MessageApproval.mailing_list == self,
                MessageApproval.status.is_in(message_approval_statuses),
                EmailAddress.status.is_in(email_address_statuses),
                Account.status == AccountStatus.ACTIVE,
                ))
        # Union the two queries together to give us the complete list of email
        # addresses allowed to post.  Note that while we're retrieving both
        # the EmailAddress and Person records, this method is defined as only
        # returning EmailAddresses.  The reason why we include the Person in
        # the query is because the consumer of this method will access
        # email_address.person.displayname, so the prejoin to Person is
        # critical to acceptable performance.  Indeed, without the prejoin, we
        # were getting tons of timeout OOPSes.  See bug 259440.
        for email_address, person in team_members.union(approved_posters):
            yield email_address

    def holdMessage(self, message):
        """See `IMailingList`."""
        held_message = MessageApproval(message=message,
                                       posted_by=message.owner,
                                       posted_message=message.raw,
                                       posted_date=message.datecreated,
                                       mailing_list=self)
        notify(SQLObjectCreatedEvent(held_message))
        return held_message

    def getReviewableMessages(self):
        """See `IMailingList`."""
        return MessageApproval.select("""
            MessageApproval.mailing_list = %s AND
            MessageApproval.status = %s AND
            MessageApproval.message = Message.id
            """ % sqlvalues(self, PostedMessageStatus.NEW),
            clauseTables=['Message'],
            orderBy=['posted_date', 'Message.rfc822msgid'])

    def purge(self):
        """See `IMailingList`."""
        # At first glance, it would seem that we could use
        # transitionToStatus(), but it actually doesn't quite match the
        # semantics we want.  For example, if we try to purge an active
        # mailing list we really want an UnsafeToPurge exception instead of an
        # AssertionError.  Fitting that in to transitionToStatus()'s logic is
        # a bit tortured, so just do it here.
        if self.status in PURGE_STATES:
            self.status = MailingListStatus.PURGED
        else:
            assert self.status != MailingListStatus.PURGED, 'Already purged'
            raise UnsafeToPurge(self)


class MailingListSet:
    implements(IMailingListSet)

    title = _('Team mailing lists')

    def new(self, team, registrant=None):
        """See `IMailingListSet`."""
        assert team.isTeam(), (
            'Cannot register a list for a person who is not a team')
        if registrant is None:
            registrant = team.teamowner
        else:
            # Check to make sure that registrant is a team owner or admin.
            # This gets tricky because an admin can be a team, and if the
            # registrant is a member of that team, they are by definition an
            # administrator of the team we're creating the mailing list for.
            # So you can't just do "registrant in
            # team.getDirectAdministrators()".  It's okay to use .inTeam() for
            # all cases because a person is always a member of himself.
            for admin in team.getDirectAdministrators():
                if registrant.inTeam(admin):
                    break
            else:
                raise AssertionError(
                    'registrant is not a team owner or administrator')
        # See if the mailing list already exists.  If so, it must be in the
        # purged state for us to be able to recreate it.
        existing_list = self.get(team.name)
        if existing_list is None:
            # We have no record for the mailing list, so just create it.
            return MailingList(team=team, registrant=registrant,
                               date_registered=UTC_NOW)
        else:
            assert existing_list.status == MailingListStatus.PURGED, (
                'Mailing list for team "%s" already exists' % team.name)
            assert existing_list.team == team, 'Team mismatch'
            # It's in the PURGED state, so just tweak the existing record.
            existing_list.registrant = registrant
            existing_list.date_registered = UTC_NOW
            existing_list.reviewer = None
            existing_list.date_reviewed = None
            existing_list.date_activated = None
            existing_list.status = MailingListStatus.REGISTERED
            existing_list.welcome_message = None
            return existing_list

    def get(self, team_name):
        """See `IMailingListSet`."""
        assert isinstance(team_name, basestring), (
            'team_name must be a string, not %s' % type(team_name))
        return MailingList.selectOne("""
            MailingList.team = Person.id
            AND Person.name = %s
            AND Person.teamowner IS NOT NULL
            """ % sqlvalues(team_name),
            clauseTables=['Person'])

    @property
    def registered_lists(self):
        """See `IMailingListSet`."""
        return MailingList.selectBy(status=MailingListStatus.REGISTERED)

    @property
    def approved_lists(self):
        """See `IMailingListSet`."""
        return MailingList.selectBy(status=MailingListStatus.APPROVED)

    @property
    def active_lists(self):
        """See `IMailingListSet`."""
        return MailingList.selectBy(status=MailingListStatus.ACTIVE)

    @property
    def modified_lists(self):
        """See `IMailingListSet`."""
        return MailingList.selectBy(status=MailingListStatus.MODIFIED)

    @property
    def deactivated_lists(self):
        """See `IMailingListSet`."""
        return MailingList.selectBy(status=MailingListStatus.DEACTIVATING)

    @property
    def unsynchronized_lists(self):
        """See `IMailingListSet`."""
        return MailingList.select('status IN %s' % sqlvalues(
            (MailingListStatus.CONSTRUCTING, MailingListStatus.UPDATING)))


class MailingListSubscription(SQLBase):
    """A mailing list subscription."""

    implements(IMailingListSubscription)

    person = ForeignKey(
        dbName='person', foreignKey='Person',
        storm_validator=validate_public_person,
        notNull=True)

    mailing_list = ForeignKey(
        dbName='mailing_list', foreignKey='MailingList',
        notNull=True)

    date_joined = UtcDateTimeCol(notNull=True, default=UTC_NOW)

    email_address = ForeignKey(dbName='email_address',
                               foreignKey='EmailAddress')

    @property
    def subscribed_address(self):
        """See `IMailingListSubscription`."""
        if self.email_address is None:
            # Use the person's preferred email address.
            return self.person.preferredemail
        else:
            # Use the subscribed email address.
            return self.email_address


class MessageApprovalSet:
    """Sets of held messages."""

    implements(IMessageApprovalSet)

    def getMessageByMessageID(self, message_id):
        """See `IMessageApprovalSet`."""
        return MessageApproval.selectOne("""
            MessageApproval.message = Message.id AND
            Message.rfc822msgid = %s
            """ % sqlvalues(message_id),
            distinct=True, clauseTables=['Message'])

    def getHeldMessagesWithStatus(self, status):
        """See `IMessageApprovalSet`."""
        return MessageApproval.selectBy(status=status)


class HeldMessageDetails:
    """Details about a held message."""

    implements(IHeldMessageDetails)

    def __init__(self, message_approval):
        self.message_approval = message_approval
        self.message = message_approval.message
        self.message_id = message_approval.message_id
        self.subject = self.message.subject
        self.date = self.message.datecreated
        self.author = self.message.owner

    @cachedproperty
    def email_message(self):
        self.message.raw.open()
        try:
            return message_from_string(self.message.raw.read())
        finally:
            self.message.raw.close()

    @cachedproperty
    def sender(self):
        """See `IHeldMessageDetails`."""
        originators = self.email_message.get_all('from', [])
        originators.extend(self.email_message.get_all('reply-to', []))
        if len(originators) == 0:
            return 'n/a'
        unicode_parts = []
        for bytes, charset in decode_header(originators[0]):
            if charset is None:
                charset = 'us-ascii'
            unicode_parts.append(
                bytes.decode(charset, 'replace').encode('utf-8'))
        header = make_header(zip(unicode_parts, repeat('utf-8')))
        return unicode(header)

    @cachedproperty
    def body(self):
        """See `IHeldMessageDetails`."""
        return self.message.text_contents
