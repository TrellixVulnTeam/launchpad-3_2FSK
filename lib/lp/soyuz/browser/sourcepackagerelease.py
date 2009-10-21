# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Browser view for a sourcepackagerelease"""

__metaclass__ = type

__all__ = [
    'SourcePackageReleaseView',
    ]

import cgi
import re

from canonical.launchpad.webapp import LaunchpadView
from canonical.launchpad.webapp.tales import FormattersAPI


def extract_bug_numbers(text):
    '''Unique bug numbers matching the "LP: #n(, #n)*" pattern in the text.'''
    # FormattersAPI._linkify_substitution requires a match object
    # that has named groups "bug" and "bugnum".  The matching text for
    # the "bug" group is used as the link text and "bugnum" forms part
    # of the URL for the link to the bug. Example:
    #   >>> bm.groupdict( )
    #   {'bugnum': '400686', 'bug': '#400686'}

    # We need to match bug numbers of the form:
    # LP: #1, #2, #3
    #  #4, #5
    # over multiple lines.
    #
    # Writing a single catch-all regex for this has proved rather hard
    # so I am taking the strategy of matching  LP:(group) first, and
    # feeding the result into another regex to pull out the bug and
    # bugnum groups.
    unique_bug_matches = dict()

    line_matches = re.finditer(
        'LP:\s*(?P<buglist>(.+?[^,]))($|\n)', text,
        re.DOTALL | re.IGNORECASE)

    for line_match in line_matches:
        bug_matches = re.finditer(
            '\s*((?P<bug>#(?P<bugnum>\d+)),?\s*)',
            line_match.group('buglist'))

        for bug_match in bug_matches:
            bugnum = bug_match.group('bugnum')
            if bugnum in unique_bug_matches:
                # We got this bug already, ignore it.
                continue
            unique_bug_matches[bugnum] = bug_match

    return unique_bug_matches


def extract_email_addresses(text):
    '''Unique email adresses in the text.'''
    matches = re.finditer(FormattersAPI._re_email, text)
    return list(set([match.group() for match in matches]))


class SourcePackageReleaseView(LaunchpadView):

    @property
    def changelog_entry(self):
        """Return a linkified changelog entry."""
        return self._linkify_changelog(self.context.changelog_entry)

    @property
    def change_summary(self):
        """Return a linkified change summary."""
        return self._linkify_changelog(self.context.change_summary)

    def _obfuscate_email(self, text):
        """Obfuscate email addresses if the user is not logged in."""
        if not text:
            # If there is nothing to obfuscate, the FormattersAPI
            # will blow up, so just return.
            return text
        formatter = FormattersAPI(text)
        if self.user:
            return text
        else:
            return formatter.obfuscate_email()

    def _linkify_email(self, text):
        """Email addresses are linkified to point to the person's profile."""
        formatter = FormattersAPI(text)
        return formatter.linkify_email()

    def _linkify_bug_numbers(self, changelog):
        """Linkify to a bug if LP: #number appears in the changelog text."""
        unique_bug_matches = extract_bug_numbers(changelog)
        for bug_match in unique_bug_matches.values():
            replace_text = bug_match.group('bug')
            if replace_text is not None:
                # XXX julian 2008-01-10
                # Note that re.sub would be far more efficient to use
                # instead of string.replace() but this requires a regex
                # that matches everything in one go.  We're also at danger
                # of replacing the wrong thing if string.replace() finds
                # other matching substrings.  So for example in the
                # string:
                # "LP: #9, #999"
                # replacing #9 with some HTML would also interfere with
                # #999.  The liklihood of this happening is very, very
                # small, however.
                changelog = changelog.replace(
                    replace_text,
                    FormattersAPI._linkify_substitution(bug_match))
        return changelog

    def _linkify_changelog(self, changelog):
        """Linkify the changelog.

        This obfuscates email addresses to anonymous users, linkifies
        them for non-anonymous and links to the bug page for any bug
        numbers mentioned.
        """
        if changelog is None:
            return ''

        # Remove any email addresses if the user is not logged in.
        changelog = self._obfuscate_email(changelog)

        # CGI Escape the changelog here before further replacements
        # insert HTML. Email obfuscation does not insert HTML but can insert
        # characters that must be escaped.
        changelog = cgi.escape(changelog)

        # Any email addresses remaining in the changelog were not obfuscated,
        # so we linkify them here.
        changelog = self._linkify_email(changelog)

        # Ensure any bug numbers are linkified to the bug page.
        changelog = self._linkify_bug_numbers(changelog)

        return changelog

