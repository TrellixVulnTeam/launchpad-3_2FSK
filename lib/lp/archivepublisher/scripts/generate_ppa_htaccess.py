#!/usr/bin/python2.4
#
# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

# pylint: disable-msg=C0103,W0403

import crypt, filecmp, os, pytz, tempfile
from datetime import datetime
from operator import attrgetter

from zope.component import getUtility

from canonical.config import config
from canonical.launchpad.helpers import get_email_template
from canonical.launchpad.mail import format_address, simple_sendmail
from canonical.launchpad.webapp import canonical_url

from lp.archivepublisher.config import getPubConfig
from lp.soyuz.interfaces.archive import IArchiveSet
from lp.soyuz.interfaces.archiveauthtoken import (
    IArchiveAuthTokenSet)
from lp.soyuz.interfaces.archivesubscriber import (
    ArchiveSubscriberStatus, IArchiveSubscriberSet)
from lp.services.mail.mailwrapper import MailWrapper
from lp.services.scripts.base import LaunchpadCronScript


# These PPAs should never have their htaccess/pwd files touched.
BLACKLISTED_PPAS = {
    'ubuntuone': ['ppa'],
    }

HTACCESS_TEMPLATE = """
AuthType           Basic
AuthName           "Token Required"
AuthUserFile       %(path)s/.htpasswd
Require            valid-user
"""

BUILDD_USER_NAME = "buildd"


class HtaccessTokenGenerator(LaunchpadCronScript):
    """Helper class for generating .htaccess files for private PPAs."""
    blacklist = BLACKLISTED_PPAS

    def add_my_options(self):
        """Add script command line options."""
        self.parser.add_option(
            "-n", "--dry-run", action="store_true",
            dest="dryrun", default=False,
            help="If set, no files are changed and no tokens are "
                 "deactivated.")
        self.parser.add_option(
            "-d", "--no-deactivation", action="store_true",
            dest="no_deactivation", default=False,
            help="If set, tokens are not deactivated.")

    def writeHtpasswd(self, filename, list_of_users):
        """Write out a new htpasswd file.

        :param filename: The file to create.
        :param list_of_users: A list of (user, password, salt) tuples.
        """
        if os.path.isfile(filename):
            os.remove(filename)

        file = open(filename, "a")
        for entry in list_of_users:
            user, password, salt = entry
            encrypted = crypt.crypt(password, salt)
            file.write("%s:%s\n" % (user, encrypted))

        file.close()

    def ensureHtaccess(self, ppa):
        """Generate a .htaccess for `ppa`."""
        if self.options.dryrun:
            return

        # The publisher Config object does not have an
        # interface, so we need to remove the security wrapper.
        pub_config = getPubConfig(ppa)
        htaccess_filename = os.path.join(pub_config.htaccessroot, ".htaccess")
        if not os.path.exists(htaccess_filename):
            # It's not there, so create it.
            if not os.path.exists(pub_config.htaccessroot):
                os.makedirs(pub_config.htaccessroot)
            interpolations = {"path" : pub_config.htaccessroot}
            file = open(htaccess_filename, "w")
            file.write(HTACCESS_TEMPLATE % interpolations)
            file.close()
            self.logger.debug("Created .htaccess for %s" % ppa.displayname)

    def generateHtpasswd(self, ppa, tokens):
        """Generate a htpasswd file for `ppa`s `tokens`.

        :param ppa: The context PPA (an `IArchive`).
        :param tokens: A iterable containing `IArchiveAuthToken`s.
        :return: The filename of the htpasswd file that was generated.
        """
        # Create a temporary file that will be a new .htpasswd.
        pub_config = getPubConfig(ppa)
        fd, temp_filename = tempfile.mkstemp(dir=pub_config.htaccessroot)
        os.close(fd)

        # The first .htpasswd entry is the buildd_secret.
        list_of_users = [
            (BUILDD_USER_NAME, ppa.buildd_secret, BUILDD_USER_NAME[:2])]

        # Iterate over tokens and write the appropriate htpasswd
        # entries for them.  Use a consistent sort order so that the
        # generated file can be compared to an existing one later.
        for token in sorted(tokens, key=attrgetter("id")):
            entry = (token.person.name, token.token, token.person.name[:2])
            list_of_users.append(entry)

        self.writeHtpasswd(temp_filename, list_of_users)

        return temp_filename

    def replaceUpdatedHtpasswd(self, ppa, temp_htpasswd_file):
        """Compare the new and the old htpasswd and replace if changed.

        :return: True if the file was replaced.
        """
        if self.options.dryrun:
            return False

        # The publisher Config object does not have an
        # interface, so we need to remove the security wrapper.
        pub_config = getPubConfig(ppa)
        htpasswd_filename = os.path.join(pub_config.htaccessroot, ".htpasswd")

        if (not os.path.isfile(htpasswd_filename) or
            not filecmp.cmp(htpasswd_filename, temp_htpasswd_file)):
            # Atomically replace the old file or create a new file.
            os.rename(temp_htpasswd_file, htpasswd_filename)
            self.logger.debug("Replaced htpasswd for %s" % ppa.displayname)
            return True

        return False

    def sendCancellationEmail(self, token):
        """Send an email to the person whose subscription was cancelled."""
        send_to_person = token.person
        ppa_name = token.archive.displayname
        ppa_owner_url = canonical_url(token.archive.owner)
        subject = "PPA access cancelled for %s" % ppa_name
        template = get_email_template("ppa-subscription-cancelled.txt")

        assert not send_to_person.isTeam(), (
            "Token.person is a team, it should always be individuals.")

        if send_to_person.preferredemail is None:
            # The person has no preferred email set, so we don't
            # email them.
            return

        to_address = [send_to_person.preferredemail.email]
        replacements = {
            'recipient_name' : send_to_person.displayname,
            'ppa_name' : ppa_name,
            'ppa_owner_url' : ppa_owner_url,
            }
        body = MailWrapper(72).format(
            template % replacements, force_wrap=True)

        from_address = format_address(
            ppa_name,
            config.canonical.noreply_from_address)

        headers = {
            'Sender' : config.canonical.bounce_address,
            }

        simple_sendmail(from_address, to_address, subject, body, headers)

    def deactivateTokens(self, ppa, send_email=False):
        """Deactivate tokens as necessary.

        If a subscriber no longer has an active token for the PPA, we
        deactivate it.

        :param ppa: The PPA to check tokens for.
        :param send_email: Whether to send a cancellation email to the owner
            of the token.  This defaults to False to speed up the test
            suite.
        :return: a list of valid tokens.
        """
        tokens = getUtility(IArchiveAuthTokenSet).getByArchive(ppa)
        valid_tokens = []
        for token in tokens:
            result = getUtility(
                IArchiveSubscriberSet).getBySubscriberWithActiveToken(
                    token.person, ppa)
            if result.count() == 0:
                # The subscriber's token is no longer active,
                # deactivate it.
                if send_email:
                    self.sendCancellationEmail(token)
                token.deactivate()
            else:
                valid_tokens.append(token)
        return valid_tokens

    def expireSubscriptions(self, ppa):
        """Expire subscriptions as necessary.

        If an `ArchiveSubscriber`'s date_expires has passed, then
        set its status to EXPIRED.

        :param ppa: The PPA to expire subscriptons for.
        """
        now = datetime.now(pytz.UTC)
        subscribers = getUtility(IArchiveSubscriberSet).getByArchive(ppa)
        for subscriber in subscribers:
            date_expires = subscriber.date_expires
            if date_expires is not None and date_expires <= now:
                self.logger.info(
                    "Expiring subscription: %s" % subscriber.displayname)
                subscriber.status = ArchiveSubscriberStatus.EXPIRED

    def main(self):
        """Script entry point."""
        self.logger.info('Starting the PPA .htaccess generation')
        ppas = getUtility(IArchiveSet).getPrivatePPAs()
        for ppa in ppas:
            self.expireSubscriptions(ppa)
            valid_tokens = self.deactivateTokens(ppa, send_email=True)

            # If this PPA is blacklisted, do not touch it's htaccess/pwd
            # files.
            blacklisted_ppa_names_for_owner = self.blacklist.get(
                ppa.owner.name, [])
            if ppa.name in blacklisted_ppa_names_for_owner:
                self.logger.info(
                    "Skipping htacess updates for blacklisted PPA "
                    " '%s' owned by %s.",
                        ppa.name,
                        ppa.owner.displayname)
                continue

            self.ensureHtaccess(ppa)
            temp_htpasswd = self.generateHtpasswd(ppa, valid_tokens)
            if not self.replaceUpdatedHtpasswd(ppa, temp_htpasswd):
                os.remove(temp_htpasswd)

        if self.options.no_deactivation or self.options.dryrun:
            self.logger.info('Dry run, so not committing transaction.')
            self.txn.abort()
        else:
            self.logger.info('Committing transaction...')
            self.txn.commit()

        self.logger.info('Finished PPA .htaccess generation')

