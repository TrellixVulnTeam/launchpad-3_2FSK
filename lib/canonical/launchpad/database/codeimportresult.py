# Copyright 2007 Canonical Ltd.  All rights reserved.

"""Database classes for the CodeImportResult table."""

__metaclass__ = type
__all__ = ['CodeImportResult', 'CodeImportResultSet']

from sqlobject import ForeignKey, StringCol

from zope.interface import implements

from canonical.database.constants import UTC_NOW
from canonical.database.datetimecol import UtcDateTimeCol
from canonical.database.enumcol import EnumCol
from canonical.database.sqlbase import SQLBase
from canonical.launchpad.interfaces import (
    CodeImportResultStatus, ICodeImportResult, ICodeImportResultSet)
from canonical.launchpad.validators.person import public_person_validator

class CodeImportResult(SQLBase):
    """See `ICodeImportResult`."""

    implements(ICodeImportResult)

    date_created = UtcDateTimeCol(notNull=True, default=UTC_NOW)

    code_import = ForeignKey(
        dbName='code_import', foreignKey='CodeImport', notNull=True)

    machine = ForeignKey(
        dbName='machine', foreignKey='CodeImportMachine', notNull=True)

    requesting_user = ForeignKey(
        dbName='requesting_user', foreignKey='Person',
        validator=public_person_validator, default=None)

    log_excerpt = StringCol(default=None)

    log_file = ForeignKey(
        dbName='log_file', foreignKey='LibraryFileAlias', default=None)

    status = EnumCol(
        enum=CodeImportResultStatus, notNull=True)

    date_job_started = UtcDateTimeCol(notNull=True)

    @property
    def date_job_finished(self):
        """See `ICodeImportResult`."""
        return self.date_created


class CodeImportResultSet(object):
    """See `ICodeImportResultSet`."""

    implements(ICodeImportResultSet)

    def new(self, code_import, machine, requesting_user, log_excerpt,
            log_file, status, date_job_started):
        """See `ICodeImportResultSet`."""
        return CodeImportResult(
            code_import=code_import, machine=machine,
            requesting_user=requesting_user, log_excerpt=log_excerpt,
            log_file=log_file, status=status,
            date_job_started=date_job_started)

    def getResultsForImport(self, code_import):
        """See `ICodeImportResultSet`."""
        return CodeImportResult.selectBy(
            code_import=code_import, orderBy=['-date_job_started'])
