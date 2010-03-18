# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

__metaclass__ = type

__all__ = [
    'TranslationBranchApprover',
    'TranslationBuildApprover',
    ]

import os.path

from zope.component import getUtility

from canonical.launchpad.interfaces.launchpad import ILaunchpadCelebrities
from lp.translations.interfaces.potemplate import IPOTemplateSet
from lp.translations.interfaces.translationimportqueue import (
    RosettaImportStatus)
from lp.translations.utilities.template import (
    make_domain, make_name, make_name_from_path)
from lp.translations.utilities.translation_import import (
    TranslationImporter)


class TranslationBranchApprover(object):
    """Automatic approval of translation import files."""

    def __init__(self, files, productseries=None,
                 distroseries=None, sourcepackagename=None):
        """Create the approver and build the approval list by comparing
        the given files as found in the source tree to the database entries.

        Either productseries or distroseries/sourcepackagename must be given
        but not all.

        :param files: A list of paths to the translation files.
        :param productseries: The productseries that this upload is for.
        :param distroseries: The distroseries that this upload is for.
        :param sourcepackagename: The sourcepackagename that this upload
            is for.
        """
        assert((productseries is not None and
                distroseries is None and sourcepackagename is None) or
               (productseries is None and
                distroseries is not None and sourcepackagename is not None))

        self._potemplates = {}
        self._n_matched = 0
        self.is_approval_possible = True

        potemplate_names = set()

        importer = TranslationImporter()
        self._potemplateset = getUtility(IPOTemplateSet).getSubset(
            iscurrent=True, productseries=productseries,
            distroseries=distroseries, sourcepackagename=sourcepackagename)
        for path in files:
            if importer.isTemplateName(path):
                potemplate = self._potemplateset.getPOTemplateByPath(path)
                if potemplate is None:
                    name = make_name_from_path(path)
                    potemplate = self._potemplateset.getPOTemplateByName(name)
                else:
                    name = potemplate.name
                # Template names must occur only once.
                if name in potemplate_names:
                    self.is_approval_possible = False
                else:
                    potemplate_names.add(name)
                if potemplate is not None:
                    self._n_matched += 1
                self._potemplates[path] = potemplate
        # The simplest case of exactly one file and one POTemplate object is
        # always approved.
        if len(self._potemplateset) == len(self._potemplates) == 1:
            self._potemplates[self._potemplates.keys()[0]] = (
                list(self._potemplateset)[0])
            self.is_approval_possible = True

    @property
    def unmatched_objects(self):
        """The number of IPOTemplate objects that are not matched by path
        to a file being imported.
        """
        return len(self._potemplateset) - self._n_matched

    @property
    def unmatched_files(self):
        """The number of files being imported that are not matched by path
        to an IPOTemplate object.
        """
        return len(self._potemplates) - self._n_matched

    def approve(self, entry):
        """Check the given ImportQueueEntry against the internal approval
        list and set its values accordingly.

        :param entry: The queue entry that needs to be approved.
        """
        if not self.is_approval_possible:
            return entry
        potemplate = None
        # Path must be a template path.
        if not self._potemplates.has_key(entry.path):
            return entry

        domain = make_domain(entry.path)
        if self._potemplates[entry.path] is None:
            if self.unmatched_objects > 0:
                # Unmatched entries in database, do not approve.
                return entry
            # Path must provide a translation domain.
            if domain == '':
                return entry
            # No (possibly) matching entry found: create one.
            name = make_name(domain)
            potemplate = self._potemplateset.new(
                name, domain, entry.path, entry.importer)
            self._potemplates[entry.path] = potemplate
            self._n_matched += 1
        else:
            # A matching entry is found, the import can be approved.
            potemplate = self._potemplates[entry.path]
            potemplate.path = entry.path
            if domain != '':
                potemplate.translation_domain = domain

        # Approve the entry
        entry.potemplate = potemplate
        if entry.status == RosettaImportStatus.NEEDS_REVIEW:
            entry.setStatus(RosettaImportStatus.APPROVED,
                            getUtility(ILaunchpadCelebrities).rosetta_experts)
        return entry


class TranslationBuildApprover(object):
    """Automatic approval of automatically build translation files."""

    def __init__(
        self, filenames,
        productseries=None, distroseries=None, sourcepackagename=None):
        """Bind the new approver to a productseries or sourcepackagename."""
        assert((productseries is not None and
                distroseries is None and sourcepackagename is None) or
               (productseries is None and
                distroseries is not None and sourcepackagename is not None))

        self._potemplateset = getUtility(IPOTemplateSet).getSubset(
            productseries=productseries,
            distroseries=distroseries,
            sourcepackagename=sourcepackagename)
        if productseries is not None:
            self.owner = productseries.product.owner
        else:
            self.owner = distroseries.distribution.owner

    def _makeGenericPOTemplate(self, path):
        """Create a potemplate when the path is generic."""
        if self._potemplateset.productseries is not None:
            domain = self._potemplateset.productseries.product.name
        else:
            domain = self._potemplateset.sourcepackagename.name
        name = domain
        return self._potemplateset.new(name, domain, path, self.owner)

    def approve(self, entry):
        """Approve a queue entry."""
        assert (
            entry.productseries == self._potemplateset.productseries and
            entry.distroseries == self._potemplateset.distroseries and
            entry.sourcepackagename == self._potemplateset.sourcepackagename
            ),("Entry must be for same target as approver.")
        potemplate = self._potemplateset.getPOTemplateByPath(entry.path)
        if potemplate is None:
            domain = make_domain(entry.path)
            name = make_name(domain)
            if name == '':
                # A generic name, check if this is the first template.
                if len(self._potemplateset) == 0:
                    # Create template from product or sourcepackagename name.
                    potemplate = self._makeGenericPOTemplate(entry.path)
                else:
                    # No approval possible.
                    return entry
            else:
                potemplate = self._potemplateset.getPOTemplateByName(name)
            if potemplate is None:
                # Still no template found, create a new one.
                potemplate = self._potemplateset.new(
                    name, domain, entry.path, self.owner)

        # Approve the entry
        entry.potemplate = potemplate
        if entry.status == RosettaImportStatus.NEEDS_REVIEW:
            entry.setStatus(RosettaImportStatus.APPROVED,
                            getUtility(ILaunchpadCelebrities).rosetta_experts)
        return entry

