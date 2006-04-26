#!/usr/bin/python
#
# Remove all translations from upstream. This script is useful to recover from
# breakages after importing bad .po files like the one reported at #32610
#
# Copyright 2006 Canonical Ltd.  All rights reserved.
#

import sys
import logging
from optparse import OptionParser
from zope.component import getUtility

from canonical.database.sqlbase import flush_database_updates
from canonical.config import config
from canonical.lp import initZopeless
from canonical.lp.dbschema import RosettaTranslationOrigin
from canonical.launchpad.scripts import (
    execute_zcml_for_scripts, logger, logger_options)
from canonical.launchpad.interfaces import (
    IProductSet, IDistributionSet, IDistroReleaseSet, ISourcePackageNameSet,
    IPOTemplateSet)

logger_name = 'remove-upstream-translations'

def parse_options(args):
    """Parse a set of command line options.

    Return an optparse.Values object.
    """
    parser = OptionParser()

    parser.add_option("-p", "--product", dest="product",
        help="The product where we should look for translations.")
    parser.add_option("-s", "--series", dest="series",
        help="The product series where we should look for translations.")
    parser.add_option("-d", "--distro", dest="distro",
        help="The distribution where we should look for translations.")
    parser.add_option("-r", "--distrorelease", dest="distrorelease",
        help="The distribution release where we should look for translations."
        )
    parser.add_option("-n", "--sourcepackagename", dest="sourcepackagename",
        help="The distribution where we should look for translations.")
    parser.add_option("-t", "--potemplatename", dest="potemplatename",
        help="The PO Template name where we should look for translations.")
    parser.add_option("-l", "--language-code", dest="languagecode",
        help="The language code where we should look for translations.")

    # Add the verbose/quiet options.
    logger_options(parser)

    (options, args) = parser.parse_args(args)

    return options

def remove_upstream_entries(ztm, potemplates, lang_code=None, variant=None):
    """Remove all translations that came from upstream.

    :arg ztm: Zope transaction manager.
    :arg potemplates: A set of potemplates that we should process.
    :arg lang_code: A string with a language code where we should do the
        removal.
    :arg variant: A language variant that we should use with the lang_code to
        locate the translations to remove.

    If lang_code is None, we process all available languages.
    """
    assert ((lang_code is None and variant is None) or
            (lang_code is not None)), (
                'variant cannot be != None if lang_code is None')

    logger_object = logging.getLogger(logger_name)

    items_deleted = 0
    for potemplate in potemplates:
        if lang_code is None:
            pofiles = sorted(
                list(potemplate.pofiles),
                key=lambda p: (p.language.code, p.variant))
        else:
            pofiles = [potemplate.getPOFileByLang(lang_code, variant)]

        for pofile in pofiles:
            logger_object.debug('Processing %s...' % pofile.title)
            if pofile.latestsubmission is not None:
                logger_object.debug(
                    'Before the removal, latest submission came from: %s' %
                        pofile.latestsubmission.person.displayname)
            pofile_items_deleted = 0
            pofile.latestsubmission = None
            for pomsgset in pofile.pomsgsets:
                for poselection in pomsgset.selections:
                    if (poselection.activesubmission is not None and
                        poselection.activesubmission.origin ==
                            RosettaTranslationOrigin.SCM):
                        poselection.activesubmission = None
                        # We removed at least one translation, we cannot have
                        # this pomsgset as iscomplete anymore, we are missing
                        # one translation!.
                        pomsgset.iscomplete = False
                    if (poselection.publishedsubmission is not None and
                        poselection.publishedsubmission.origin ==
                            RosettaTranslationOrigin.SCM):
                        poselection.publishedsubmission = None
                        # We removed at least one translation, we cannot have
                        # this pomsgset as iscomplete anymore, we are missing
                        # one translation!.
                        pomsgset.publishedcomplete = False
                # We are going to delete POSubmissions here, and we need that
                # the database has all changes we did to remove the references
                # to the removed object.
                flush_database_updates()
                for posubmission in pomsgset.submissions:
                    if (not posubmission.active_selections and
                        not posubmission.published_selections and
                        posubmission.origin == RosettaTranslationOrigin.SCM):
                        posubmission.destroySelf()
                        pofile_items_deleted += 1
                # Let's fix the flags that depend on translations, we modified
                # the IPOMsgSet and we should leave it in a consistent status.
                pomsgset.updateFlags()
            items_deleted += pofile_items_deleted
            logger_object.debug(
                 'Removed %d submissions' % pofile_items_deleted)
            pofile.updateStatistics()
            pofile.recalculateLatestSubmission()
            ztm.commit()
            if pofile.latestsubmission is not None:
                logger_object.debug(
                    'After the removal, latest submission came from: %s' %
                        pofile.latestsubmission.person.displayname)

    # We finished the removal process, is time to notify the amount of entries
    # that we removed.
    logger_object.debug(
        'Removed %d submissions in total.' % items_deleted)

def main(argv):
    options = parse_options(argv[1:])
    logger_object = logger(options, logger_name)

    execute_zcml_for_scripts()
    ztm = initZopeless(dbuser=config.rosetta.rosettaadmin.dbuser)

    product = None
    series = None
    distro = None
    distrorelease = None
    sourcepackagename = None
    potemplatename = None
    language_code = None
    if options.product is not None:
        productset = getUtility(IProductSet)
        product = productset.getByName(options.product)
        if product is None:
            logger_object.error(
                'The %s product does not exist.' % options.product)
            return 1

    if options.series is not None:
        if product is None:
            logger_object.error(
                'You need to specify a product if you want to select a'
                ' productseries.')
            return 1

        series = product.getSeries(options.series)
        if series is None:
            logger_object.error(
                'The %s series does not exist inside %s product.' % (
                    options.series, options.product))
            return 1

    if options.distro is not None:
        if product is not None:
            logger_object.error(
                'You cannot mix distributions and products.')
            return 1
        distroset = getUtility(IDistributionSet)
        distro = distroset.getByName(options.distro)
        if distro is None:
            logger_object.error(
                'The %s distribution does not exist.' % options.distro)
            return 1

    if options.distrorelease is not None:
        if distro is None:
            logger_object.error(
                'You need to specify a distribution if you want to select a'
                ' sourcepackagename.')
        distroreleaseset = getUtility(IDistroReleaseSet)
        distrorelease = distroreleaseset.queryByName(
            distro, options.distrorelease)
        if distrorelease is None:
            logger_object.error(
                'The %s distribution does not exist.' % options.distrorelease)
            return 1

    if options.sourcepackagename is not None:
        if distrorelease is None:
            logger_object.error(
                'You need to specify a distribution release if you want to'
                ' select a sourcepackagename.')
            return 1
        sourcepackagenameset = getUtility(ISourcePackageNameSet)
        sourcepackagename = sourcepackagenameset.queryByName(
            options.sourcepackagename)
        if sourcepackagename is None:
            logger_object.error(
                'The %s sourcepackagename does not exist.' % (
                    options.sourcepackagename))
            return 1

    potemplateset = getUtility(IPOTemplateSet)
    if series is None and distrorelease is None:
        if options.potemplatename is None:
            logger_object.warning('Nothing to do. Exiting...')
            return 0
        else:
            potemplates = potemplateset.getAllByName(
                options.potemplatename)
    else:
        potemplate_subset = potemplateset.getSubset(
            distrorelease=distrorelease, sourcepackagename=sourcepackagename,
            productseries=series)
        if options.potemplatename is not None:
            potemplate = potemplate_subset.getPOTemplateByName(
                options.potemplatename)
            potemplates = [potemplate]
        else:
            # Get a list from the subset of potemplates to be able to do
            # transaction commits.
            potemplates = list(potemplate_subset)

    lang_code = None
    variant = None
    if options.languagecode is not None:
        if '@' in options.languagecode:
            lang_code, variant = options.languagecode.split('@')
        else:
            lang_code = options.languagecode

    remove_upstream_entries(ztm, potemplates, lang_code, variant)

if __name__ == '__main__':
    sys.exit(main(sys.argv))
