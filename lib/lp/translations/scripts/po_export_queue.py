# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'ExportResult',
    'process_queue',
    ]

import os
import psycopg2
import traceback
from StringIO import StringIO
from zope.component import getAdapter, getUtility

from canonical.config import config
from canonical.launchpad import helpers
from canonical.launchpad.interfaces.librarian import ILibraryFileAliasSet
from canonical.launchpad.webapp import canonical_url
from lp.registry.interfaces.productseries import IProductSeries
from lp.registry.interfaces.sourcepackage import ISourcePackage
from lp.translations.interfaces.poexportrequest import (
    IPOExportRequestSet)
from lp.translations.interfaces.potemplate import IPOTemplate
from lp.translations.interfaces.pofile import IPOFile
from lp.translations.interfaces.translationcommonformat import (
    ITranslationFileData)
from lp.translations.interfaces.translationexporter import (
    ITranslationExporter)
from lp.translations.interfaces.translationfileformat import (
    TranslationFileFormat)
from canonical.launchpad.mail import simple_sendmail


class ExportResult:
    """The results of a translation export request.

    This class has three main attributes:

     - person: A person requesting this export.
     - url: The Librarian URL for any successfully exported files.
     - failure: Failure gotten while exporting.
    """

    def __init__(self, person, requested_exports, logger):
        self.person = person
        self.url = None
        self.failure = None
        self.logger = logger

        self.requested_exports = list(requested_exports)
        export_requested_at = self._getExportRequestOrigin()
        self.name = self._getShortRequestName(export_requested_at)

        self.request_url = canonical_url(
            export_requested_at,
            rootsite='translations') + '/+export'

    def _getShortRequestName(self, request):
        """Return a short request name for use in email subjects."""
        if IPOFile.providedBy(request):
            title = '%s translation of %s' % (
                request.language.englishname,
                request.potemplate.name)
            productseries = request.potemplate.productseries
            distroseries = request.potemplate.distroseries
            sourcepackagename = request.potemplate.sourcepackagename
        elif IPOTemplate.providedBy(request):
            title = '%s template' % (request.name)
            productseries = request.productseries
            distroseries = request.distroseries
            sourcepackagename = request.sourcepackagename
        elif IProductSeries.providedBy(request):
            title = None
            productseries = request
            distroseries = None
            sourcepackagename = None
        elif ISourcePackage.providedBy(request):
            title = None
            productseries = None
            distroseries = request.distroseries
            sourcepackagename = request.sourcepackagename
        else:
            raise AssertionError(
                "We can not figure out short name for this translation "
                "export origin.")

        if productseries is not None:
            root = '%s %s' % (
                productseries.product.displayname,
                productseries.name)
        else:
            root = '%s %s %s' % (
                distroseries.distribution.displayname,
                distroseries.displayname,
                sourcepackagename.name)
        if title is not None:
            return '%s - %s' % (root, title)
        else:
            return root

    def _getExportRequestOrigin(self):
        """Figure out where an export request was made."""
        # Determine all objects that export request could have
        # originated on.
        export_requested_at = None
        pofiles = set()
        implicit_potemplates = set()
        direct_potemplates = set()
        productseries = set()
        sourcepackages = set()

        last_template_name = None
        for request in self.requested_exports:
            if IPOTemplate.providedBy(request):
                # If we are exporting a template, add it to
                # the list of directly requested potemplates.
                potemplate = request
                direct_potemplates.add(potemplate)
            else:
                # Otherwise, we are exporting a POFile.
                potemplate = request.potemplate
                implicit_potemplates.add(potemplate)
                pofiles.add(request)
            if potemplate.displayname != last_template_name:
                self.logger.debug(
                    'Exporting objects for %s, related to template %s'
                    % (self.person.displayname, potemplate.displayname))
                last_template_name = potemplate.displayname

            # Determine productseries or sourcepackage for any
            # productseries/sourcepackage an export was requested at.
            if potemplate.productseries is not None:
                productseries.add(potemplate.productseries)
            elif potemplate.sourcepackagename is not None:
                sourcepackage = potemplate.distroseries.getSourcePackage(
                    potemplate.sourcepackagename)
                sourcepackages.add(sourcepackage)
            else:
                pass

        if len(pofiles) == 1 and len(direct_potemplates) == 0:
            # One POFile was requested.
            export_requested_at = pofiles.pop()
        elif len(pofiles) == 0 and len(direct_potemplates) == 1:
            # A POTemplate was requested.
            export_requested_at = direct_potemplates.pop()
        elif len(pofiles) + len(direct_potemplates) >= 2:
            # More than one file was requested.
            all_potemplates = implicit_potemplates.union(direct_potemplates)
            if len(all_potemplates) == 1:
                # It's all part of a single POTemplate.
                export_requested_at = all_potemplates.pop()
            else:
                # More than one POTemplate: request was made on
                # either ProductSeries or SourcePackage.
                if len(sourcepackages) > 0:
                    export_requested_at = sourcepackages.pop()
                elif len(productseries) > 0:
                    export_requested_at = productseries.pop()

        if IPOTemplate.providedBy(export_requested_at):
            if len(sourcepackages) > 0:
                sp = sourcepackages.pop()
                if sp.getCurrentTranslationTemplates().count() == 1:
                    export_requested_at = sp
            elif len(productseries) > 0:
                ps = productseries.pop()
                if ps.getCurrentTranslationTemplates().count() == 1:
                    export_requested_at = ps

        return export_requested_at


    def _getRequestedExportsNames(self):
        requested_names = []
        for translation_object in self.requested_exports:
            if IPOTemplate.providedBy(translation_object):
                request_name = translation_object.displayname
            else:
                request_name = translation_object.title
            requested_names.append(request_name)

        return requested_names

    def _getFailureEmailBody(self):
        """Send an email notification about the export failing."""
        template = helpers.get_email_template(
            'poexport-failure.txt', 'translations').decode('utf-8')
        return template % {
            'person' : self.person.displayname,
            'request_url' : self.request_url,
            }

    def _getFailedRequestsDescription(self):
        """Return a printable description of failed export requests."""
        failed_requests = self._getRequestedExportsNames()
        if len(failed_requests) > 0:
            failed_requests_text = 'Failed export request included:\n'
            failed_requests_text += '\n'.join(
                ['  * ' + request for request in failed_requests])
        else:
            failed_requests_text = 'There were no export requests.'
        return failed_requests_text

    def _getAdminFailureNotificationEmailBody(self):
        """Send an email notification about failed export to admins."""
        template = helpers.get_email_template(
            'poexport-failure-admin-notification.txt',
            'translations').decode('utf-8')
        failed_requests = self._getFailedRequestsDescription()
        return template % {
            'person' : self.person.displayname,
            'person_id' : self.person.name,
            'request_url' : self.request_url,
            'failure_message' : self.failure,
            'failed_requests' : failed_requests,
            }

    def _getUnicodeDecodeErrorEmailBody(self):
        """Send an email notification to admins about UnicodeDecodeError."""
        template = helpers.get_email_template(
            'poexport-failure-unicodedecodeerror.txt',
            'translations').decode('utf-8')
        failed_requests = self._getFailedRequestsDescription()
        return template % {
            'person' : self.person.displayname,
            'person_id' : self.person.name,
            'request_url' : self.request_url,
            'failed_requests' : failed_requests,
            }

    def _getSuccessEmailBody(self):
        """Send an email notification about the export working."""
        template = helpers.get_email_template(
            'poexport-success.txt', 'translations').decode('utf-8')
        return template % {
            'person' : self.person.displayname,
            'download_url' : self.url,
            'request_url' : self.request_url,
            }

    def notify(self):
        """Send a notification email to the given person about the export.

        If there is a failure, a copy of the email is also sent to the
        Launchpad error mailing list for debugging purposes.
        """
        if self.failure is None and self.url is not None:
            # There is no failure, so we have a full export without
            # problems.
            body = self._getSuccessEmailBody()
        elif self.failure is not None and self.url is None:
            body = self._getFailureEmailBody()
        elif self.failure is not None and self.url is not None:
            raise AssertionError(
                'We cannot have a URL for the export and a failure.')
        else:
            raise AssertionError('On success, an exported URL is expected.')

        recipients = list(helpers.get_contact_email_addresses(self.person))

        for recipient in [str(recipient) for recipient in recipients]:
            simple_sendmail(
                from_addr=config.rosetta.admin_email,
                to_addrs=[recipient],
                subject='Launchpad translation download: %s' % self.name,
                body=body)

        if self.failure is None:
            # There are no errors, so nothing else to do here.
            return

        # The export process had errors that we should notify admins about.
        try:
            admins_email_body = self._getAdminFailureNotificationEmailBody()
        except UnicodeDecodeError:
            # Unfortunately this happens sometimes: invalidly-encoded data
            # makes it into the exception description, possibly from error
            # messages printed by msgfmt.  Before we can fix that, we need to
            # know what exports suffer from this problem.
            admins_email_body = self._getUnicodeDecodeErrorEmailBody()

        simple_sendmail(
            from_addr=config.rosetta.admin_email,
            to_addrs=[config.launchpad.errors_address],
            subject=(
                'Launchpad translation download errors: %s' % self.name),
            body=admins_email_body)

    def addFailure(self):
        """Store an exception that broke the export."""
        # Get the trace back that produced this failure.
        exception = StringIO()
        traceback.print_exc(file=exception)
        exception.seek(0)
        # And store it.
        self.failure = exception.read()


def generate_translationfiledata(file_list, format):
    """Generate `TranslationFileData` objects for POFiles/templates in list.

    This builds each `TranslationFileData` in memory only when it's needed, so
    the memory usage for an export doesn't accumulate.
    """
    if format == TranslationFileFormat.POCHANGED:
        adaptername = 'changed_messages'
    else:
        adaptername = 'all_messages'

    for file in file_list:
        yield getAdapter(file, ITranslationFileData, adaptername)


def process_request(person, objects, format, logger):
    """Process a request for an export of Launchpad translation files.

    After processing the request a notification email is sent to the requester
    with the URL to retrieve the file (or the tarball, in case of a request of
    multiple files) and information about files that we failed to export (if
    any).
    """
    translation_exporter = getUtility(ITranslationExporter)
    translation_format_exporter = (
        translation_exporter.getExporterProducingTargetFileFormat(format))

    result = ExportResult(person, objects, logger)

    try:
        exported_file = translation_format_exporter.exportTranslationFiles(
            generate_translationfiledata(list(objects), format))
    except (KeyboardInterrupt, SystemExit):
        # We should never catch KeyboardInterrupt or SystemExit.
        raise
    except psycopg2.Error:
        # It's a DB exception, we don't catch it either, the export
        # should be done again in a new transaction.
        raise
    except:
        # The export for the current entry failed with an unexpected
        # error, we add the entry to the list of errors.
        result.addFailure()
    else:
        if exported_file.path is None:
            # The exported path is unknown, use translation domain as its
            # filename.
            assert exported_file.file_extension, (
                'File extension must have a value!.')
            exported_path = 'launchpad-export.%s' % (
                exported_file.file_extension)
        else:
            # Convert the path to a single file name so it's noted in
            # librarian.
            exported_path = exported_file.path.replace(os.sep, '_')

        alias_set = getUtility(ILibraryFileAliasSet)
        alias = alias_set.create(
            name=exported_path,
            size=exported_file.size,
            file=exported_file,
            contentType=exported_file.content_type)
        result.url = alias.http_url
        logger.info("Stored file at %s" % result.url)

    result.notify()


def process_queue(transaction_manager, logger):
    """Process each request in the translation export queue.

    Each item is removed from the queue as it is processed, we only handle
    one request with each function call.
    """
    request_set = getUtility(IPOExportRequestSet)

    request = request_set.popRequest()

    if None in request:
        # Any value is None and we must have all values as not None to have
        # something to process...
        return

    person, objects, format = request

    try:
        process_request(person, objects, format, logger)
    except psycopg2.Error:
        # We had a DB error, we don't try to recover it here, just exit
        # from the script and next run will retry the export.
        logger.error(
            "A DB exception was raised when exporting files for %s" % (
                person.displayname),
            exc_info=True)
        transaction_manager.abort()
    else:
        # Apply all changes.
        transaction_manager.commit()
