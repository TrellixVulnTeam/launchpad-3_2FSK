# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Hardware database related table classes."""

__all__ = ['HWSubmission',
           'HWSubmissionSet',
           'HWSystemFingerprint',
           'HWSystemFingerprintSet'
          ]

from zope.component import getUtility
from zope.interface import implements

from sqlobject import BoolCol, ForeignKey, StringCol

from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase, sqlvalues
from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.launchpad.interfaces import (
    HWSubmissionFormat, HWSubmissionInvalidEmailAddress,
    HWSubmissionKeyNotUnique, HWSubmissionProcessingStatus, IHWSubmission,
    IHWSubmissionSet, IHWSystemFingerprint, IHWSystemFingerprintSet,
    ILaunchpadCelebrities, ILibraryFileAliasSet, IPersonSet,
    PersonCreationRationale)

class HWSubmission(SQLBase):
    """See `IHWSubmission`."""

    implements(IHWSubmission)
    _table = 'HWSubmission'
    
    date_created = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    date_submitted = UtcDateTimeCol(notNull=True, default=UTC_NOW)
    format = EnumCol(enum=HWSubmissionFormat, notNull=True)
    status = EnumCol(enum=HWSubmissionProcessingStatus, notNull=True)
    private = BoolCol(notNull=True)
    contactable = BoolCol(notNull=True)
    submission_key = StringCol(notNull=True)
    owner = ForeignKey(dbName='owner', foreignKey='Person')
    distroarchrelease = ForeignKey(dbName='distroarchseries',
                                   foreignKey='Distroarchrelease',
                                   notNull=True)
    raw_submission = ForeignKey(dbName='raw_submission',
                                foreignKey='LibraryFileAlias',
                                notNull=True)
    system_fingerprint = ForeignKey(dbName='system_fingerprint',
                                    foreignKey='HWSystemFingerprint',
                                    notNull=True)


class HWSubmissionSet:
    """See `IHWSubmissionSet`."""

    implements(IHWSubmissionSet)

    def createSubmission(self, date_created, format, private, contactable,
                         submission_key, emailaddress, distroarchseries,
                         raw_submission, filename, filesize,
                         system_fingerprint):
        """See `IHWSubmissionSet`."""
        
        submission_exists = HWSubmission.selectOneBy(
            submission_key=submission_key)
        if submission_exists is not None:
            raise HWSubmissionKeyNotUnique(
                'A submission with this ID already exists')
        
        personset = getUtility(IPersonSet)
        owner = personset.getByEmail(emailaddress)
        if owner is None:
            owner, email = personset.createPersonAndEmail(
                emailaddress,
                PersonCreationRationale.OWNER_SUBMITTED_HARDWARE_TEST)
            if owner is None:
                raise HWSubmissionInvalidEmailAddress, 'invalid email address'

        fingerprint = HWSystemFingerprint.selectOneBy(
            fingerprint=system_fingerprint)
        if fingerprint is None:
            fingerprint = HWSystemFingerprint(fingerprint=system_fingerprint)

        libraryfileset = getUtility(ILibraryFileAliasSet)
        libraryfile = libraryfileset.create(
            name=filename,
            size=filesize,
            file=raw_submission,
            # We expect submissions only from the HWDB client, which should
            # know that it is supposed to send XML data. Other programs
            # might submit other data (or at least claim to be sending some
            # other content type), but the content type as sent by the
            # client can be checked in the browser class which manages the
            # submissions. A real check, if we have indeed an XML file,
            # cannot be done without parsing, and this will be done later,
            # in a cron job.
            contentType='text/xml',
            expires=None)

        return HWSubmission(
            date_created=date_created,
            format=format,
            status=HWSubmissionProcessingStatus.SUBMITTED,
            private=private,
            contactable=contactable,
            submission_key=submission_key,
            owner=owner,
            distroarchrelease=distroarchseries,
            raw_submission=libraryfile,
            system_fingerprint=fingerprint)

    def getBySubmissionID(self, submission_key, user=None):
        """See `IHWSubmissionSet`."""
        admins = getUtility(ILaunchpadCelebrities).admin
        query = "submission_key=%s" % sqlvalues(submission_key)
        if user is None:
            query = query + " AND not private"
        elif not user.inTeam(admins):
            query = query + " AND (not private OR owner=%i)" % user.id
        else:
            # the user is an admin and may see every submission, hence
            # no need to add any restriction.
            pass
        return HWSubmission.selectOne(query)

    def getByFingerprintName(self, name, user=None):
        """See `IHWSubmissionSet`."""
        admins = getUtility(ILaunchpadCelebrities).admin
        fp = HWSystemFingerprintSet().getByName(name)
        query = """
            system_fingerprint=%s
            AND HWSystemFingerprint.id = HWSubmission.system_fingerprint
            """ % sqlvalues(fp)
        if user is None:
            query = query + " AND not private"
        elif not user.inTeam(admins):
            query = query + " AND (NOT private OR owner=%i)" % user.id
        else:
            # the user is an admin and may see every submission, hence
            # no need to add any restriction.
            pass
            
        return HWSubmission.select(
            query,
            clauseTables=['HWSystemFingerprint'],
            prejoinClauseTables=['HWSystemFingerprint'],
            orderBy=['HWSystemFingerprint.fingerprint',
                     'date_submitted',
                     'submission_key'])

    def getByOwner(self, owner, user=None):
        """See `IHWSubmissionSet`."""
        admins = getUtility(ILaunchpadCelebrities).admin
        query = """
            owner=%i
            AND HWSystemFingerprint.id = HWSubmission.system_fingerprint
            """ % owner.id
        if user is None:
            query = query + " AND NOT private"
        elif not user.inTeam(admins):
            query = query + " AND (NOT private OR owner=%s)" % user.id
        else:
            # the user is an admin and may see every submission, hence
            # no need to add any restriction.
            pass

        return HWSubmission.select(
            query,
            clauseTables=['HWSystemFingerprint'],
            prejoinClauseTables=['HWSystemFingerprint'],
            orderBy=['HWSystemFingerprint.fingerprint',
                     'date_submitted',
                     'submission_key'])

class HWSystemFingerprint(SQLBase):
    """Identifiers of a computer system."""

    implements(IHWSystemFingerprint)
    _table = 'HWSystemFingerprint'

    fingerprint = StringCol(notNull=True)


class HWSystemFingerprintSet:
    """A set of identifiers of a computer system."""

    implements(IHWSystemFingerprintSet)

    def getByName(self, fingerprint):
        """See `IHWSystemFingerprintSet`."""
        return HWSystemFingerprint.selectOneBy(fingerprint=fingerprint)

    def createFingerprint(self, fingerprint):
        """See `IHWSystemFingerprintSet`."""
        return HWSystemFingerprint(fingerprint=fingerprint)
