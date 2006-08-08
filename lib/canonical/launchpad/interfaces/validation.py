# Copyright 2004-2006 Canonical Ltd. All rights reserved.

__metaclass__ = type

__all__ = [
    'validate_url',
    'valid_http_url',
    'valid_ftp_url',
    'valid_rsync_url',
    'valid_webref',
    'non_duplicate_bug',
    'non_duplicate_branch',
    'valid_bug_number',
    'valid_cve_sequence',
    'valid_emblem',
    'valid_hackergotchi',
    'valid_unregistered_email',
    'validate_distribution_mirror_schema',
    'valid_distributionmirror_file_list',
    'validate_shipit_recipientdisplayname',
    'validate_shipit_phone',
    'validate_shipit_city',
    'validate_shipit_addressline1',
    'validate_shipit_addressline2',
    'validate_shipit_organization',
    'validate_shipit_postcode',
    'validate_shipit_province',
    'shipit_postcode_required',
    'valid_distrotask',
    'valid_upstreamtask',
    'valid_password',
    'validate_date_interval'
    ]

import urllib
from textwrap import dedent
from StringIO import StringIO

from zope.component import getUtility
from zope.app.content_types import guess_content_type
from zope.app.form.interfaces import WidgetsError

from canonical.launchpad import _
from canonical.launchpad.interfaces import NotFoundError
from canonical.launchpad.interfaces.launchpad import ILaunchBag
from canonical.launchpad.interfaces.bugtask import BugTaskSearchParams
from canonical.launchpad.validators import LaunchpadValidationError
from canonical.launchpad.validators.email import valid_email
from canonical.launchpad.validators.cve import valid_cve
from canonical.launchpad.validators.url import valid_absolute_url


def _validate_ascii_text(text):
    """Check if the given text contains only ASCII characters.
    
    >>> print _validate_ascii_text(u'no non-ascii characters')
    None
    >>> print _validate_ascii_text(u'\N{LATIN SMALL LETTER E WITH ACUTE}')
    Traceback (most recent call last):
    ...
    LaunchpadValidationError: ...
    >>> print _validate_ascii_text('\xc3\xa7')
    Traceback (most recent call last):
    ...
    AssertionError: Expected unicode string, but got <type 'str'>
    """
    assert isinstance(text, unicode), (
        'Expected unicode string, but got %s' % type(text))
    try:
        text.encode('ascii')
    except UnicodeEncodeError, unicode_error:
        first_non_ascii_char = text[unicode_error.start:unicode_error.end]
        e_with_acute = u'\N{LATIN SMALL LETTER E WITH ACUTE}'
        raise LaunchpadValidationError(_(dedent("""
            Sorry, but non-ASCII characters (such as '%s'), aren't accepted
            by our shipping company. Please change these to ASCII
            equivalents. (For instance, '%s' should be changed to 'e')"""
            % (first_non_ascii_char, e_with_acute))))


def shipit_postcode_required(country):
    """Return True if a postcode is required to ship CDs to country.
    
    >>> class MockCountry: pass
    >>> brazil = MockCountry
    >>> brazil.iso3166code2 = 'BR'
    >>> shipit_postcode_required(brazil)
    True
    >>> zimbabwe = MockCountry
    >>> zimbabwe.iso3166code2 = 'ZWE'
    >>> shipit_postcode_required(zimbabwe)
    False
    """
    code = country.iso3166code2
    return code in country_codes_where_postcode_is_required


class ShipItAddressValidator:

    def __init__(self, fieldname, length, msg=""):
        self.fieldname = fieldname
        self.length = length
        self.msg = msg

    def __call__(self, value):
        """Check if value contains only ASCII characters and if len(value) is
        smaller or equal self.length.

        >>> ShipItAddressValidator('somefield', 4)(u'some value')
        Traceback (most recent call last):
        ...
        LaunchpadValidationError: The somefield can't have more than 4 characters. 
        >>> ShipItAddressValidator('somefield', 14)(u'some value')
        True
        >>> custom_msg = "some custom message"
        >>> ShipItAddressValidator('somefield', 4, custom_msg)(u'some value')
        Traceback (most recent call last):
        ...
        LaunchpadValidationError: some custom message
        """
        _validate_ascii_text(value)
        if len(value) > self.length:
            if not self.msg:
                self.msg = ("The %s can't have more than %d characters."
                            % (self.fieldname, self.length))
            raise LaunchpadValidationError(_(self.msg))
        return True
    
validate_shipit_organization = ShipItAddressValidator('organization', 30)

validate_shipit_recipientdisplayname = ShipItAddressValidator(
    "recipient's name", 20)

validate_shipit_city = ShipItAddressValidator('city name', 30)

custom_msg = ("Address (first line) can't have more than 30 characters. "
              "You should use the second line if your address is too long.")
validate_shipit_addressline1 = ShipItAddressValidator('address', 30, custom_msg)

custom_msg = ("Address (second line) can't have more than 30 characters. "
              "You should use the first line if your address is too long.")
validate_shipit_addressline2 = ShipItAddressValidator('address', 30, custom_msg)

validate_shipit_phone = ShipItAddressValidator('phone number', 16)

validate_shipit_province = ShipItAddressValidator('province', 30)

# XXX: For now we only check if the postcode is valid ascii, as we haven't
# heard back from MediaMotion on the length constraint.
# -- Guilherme Salgado, 2006-05-22
def validate_shipit_postcode(value):
    _validate_ascii_text(value)
    return True


# XXX matsubara 2006-03-15: The validations functions that deals with URLs
# should be in validators/ and we should have them as separete constraints in
# trusted.sql.
# https://launchpad.net/products/launchpad/+bug/35077
def validate_url(url, valid_schemes):
    """Returns a boolean stating whether 'url' is a valid URL.

       A URL is valid if:
           - its URL scheme is in the provided 'valid_schemes' list, and
           - it has a non-empty host name.

       None and an empty string are not valid URLs::

           >>> validate_url(None, [])
           False
           >>> validate_url('', [])
           False

       The valid_schemes list is checked::

           >>> validate_url('http://example.com', ['http'])
           True
           >>> validate_url('http://example.com', ['https', 'ftp'])
           False

       A URL without a host name is not valid:

           >>> validate_url('http://', ['http'])
           False

      """
    if not url:
        return False
    scheme, host = urllib.splittype(url)
    if not scheme in valid_schemes:
        return False
    if not valid_absolute_url(url):
        return False
    return True


def valid_webref(web_ref):
    """Returns True if web_ref is not a valid download URL, or raises a
    LaunchpadValidationError.

    >>> valid_webref('http://example.com')
    True
    >>> valid_webref('https://example.com/foo/bar')
    True
    >>> valid_webref('ftp://example.com/~ming')
    True
    >>> valid_webref('sftp://example.com//absolute/path/maybe')
    True
    >>> valid_webref('other://example.com/moo')
    Traceback (most recent call last):
    ...
    LaunchpadValidationError: ...
    """
    if validate_url(web_ref, ['http', 'https', 'ftp', 'sftp']):
        # Allow ftp so valid_webref can be used for download_url, and so
        # it doesn't lock out weird projects where the site or
        # screenshots are kept on ftp.
        return True
    else:
        raise LaunchpadValidationError(_(dedent("""
            Not a valid URL. Please enter the full URL, including the
            scheme (for instance, http:// for a web URL), and ensure the
            URL uses either http, https or ftp.""")))

def valid_ftp_url(url):
    if validate_url(url, ['ftp']):
        return True
    else:
        raise LaunchpadValidationError(_(dedent("""
            Not a valid FTP URL. Please enter the full URL, including the
            ftp:// part.""")))

def valid_rsync_url(url):
    if validate_url(url, ['rsync']):
        return True
    else:
        raise LaunchpadValidationError(_(dedent("""
            Not a valid Rsync URL. Please enter the full URL, including the
            rsync:// part.""")))

def valid_http_url(url):
    if validate_url(url, ['http']):
        return True
    else:
        raise LaunchpadValidationError(_(dedent("""
            Not a valid HTTP URL. Please enter the full URL, including the
            http:// part.""")))

def non_duplicate_bug(value):
    """Prevent dups of dups.

    Returns True if the dup target is not a duplicate /and/ if the
    current bug doesn't have any duplicates referencing it /and/ if the
    bug isn't a duplicate of itself, otherwise
    return False.
    """

    from canonical.launchpad.interfaces.bug import IBugSet
    bugset = getUtility(IBugSet)
    current_bug = getUtility(ILaunchBag).bug
    dup_target = value
    current_bug_has_dup_refs = bool(bugset.searchAsUser(
        user=getUtility(ILaunchBag).user,
        duplicateof=current_bug))
    if current_bug == dup_target:
        raise LaunchpadValidationError(_(dedent("""
            You can't mark a bug as a duplicate of itself.""")))
    elif dup_target.duplicateof is not None:
        raise LaunchpadValidationError(_(dedent("""
            Bug %i is already a duplicate of bug %i. You can only
            duplicate to bugs that are not duplicates themselves.
            """% (dup_target.id, dup_target.duplicateof.id))))
    elif current_bug_has_dup_refs:
        raise LaunchpadValidationError(_(dedent("""
            There are other bugs already marked as duplicates of Bug %i.
            These bugs should be changed to be duplicates of another bug
            if you are certain you would like to perform this change."""
            % current_bug.id)))
    else:
        return True


def non_duplicate_branch(value):
    """Ensure that this branch hasn't already been linked to this bug."""
    current_bug = getUtility(ILaunchBag).bug
    if current_bug.hasBranch(value):
        raise LaunchpadValidationError(_(dedent("""
            This branch is already registered on this bug.
            """)))

    return True


def valid_bug_number(value):
    from canonical.launchpad.interfaces.bug import IBugSet
    bugset = getUtility(IBugSet)
    try:
        bugset.get(value)
    except NotFoundError:
        raise LaunchpadValidationError(_(
            "Bug %i doesn't exist." % value))
    return True


def valid_cve_sequence(value):
    """Check if the given value is a valid CVE otherwise raise an exception."""
    if valid_cve(value):
        return True
    else:
        raise LaunchpadValidationError(_(
            "%s is not a valid CVE number" % value))


def _valid_image(image, max_size, max_dimensions):
    """Check that the given image is under the given constraints.

    :length: is the maximum size of the image, in bytes.
    :dimensions: is a tuple of the form (width, height).
    """
    # No global import to avoid hard dependency on PIL being installed
    import PIL.Image
    if len(image) > max_size:
        raise LaunchpadValidationError(_(dedent("""
            This file exceeds the maximum allowed size in bytes.""")))
    try:
        image = PIL.Image.open(StringIO(image))
    except IOError:
        # cannot identify image type
        raise LaunchpadValidationError(_(dedent("""
            The file uploaded was not recognized as an image; please
            check the file and retry.""")))
    if image.size > max_dimensions:
        raise LaunchpadValidationError(_(dedent("""
            This image exceeds the maximum allowed width or height in
            pixels.""")))
    return True

def valid_emblem(emblem):
    return _valid_image(emblem, 9000, (16,16))

def valid_hackergotchi(hackergotchi):
    return _valid_image(hackergotchi, 54000, (150,150))

# XXX: matsubara 2005-12-08 This validator shouldn't be used in an editform,
# because editing an already registered e-mail would fail if this constraint
# is used.
def valid_unregistered_email(email):
    """Check that the given email is valid and that isn't registered to
    another user."""

    from canonical.launchpad.interfaces import IEmailAddressSet
    if valid_email(email):
        emailset = getUtility(IEmailAddressSet)
        if emailset.getByEmail(email) is not None:
            raise LaunchpadValidationError(_(dedent("""
                %s is already taken.""" % email)))
        else:
            return True
    else:
        raise LaunchpadValidationError(_(dedent("""
            %s isn't a valid email address.""" % email)))

def valid_distributionmirror_file_list(file_list=None):
    if file_list is not None:
        content_type, dummy = guess_content_type(body=file_list)
        if content_type != 'text/plain':
            raise LaunchpadValidationError(
                "The given file is not in plain text format.")
    return True

def validate_distribution_mirror_schema(form_values):
    """Perform schema validation according to IDistributionMirror constraints.

    This validation will take place after the values of individual widgets
    are validated. It's necessary because we have some constraints where we
    need to take into account the value of multiple widgets.

    :form_values: A dictionary mapping IDistributionMirror attributes to the
                  values suplied by the user.
    """
    errors = []
    if not (form_values['http_base_url'] or form_values['ftp_base_url']
            or form_values['rsync_base_url']):
        errors.append(LaunchpadValidationError(_(
            "All mirrors require at least one URL (HTTP, FTP or "
            "Rsync) to be specified.")))

    if errors:
        raise WidgetsError(errors)


def valid_distrotask(bug, distribution, sourcepackagename=None,
                     on_create=False):
    """Check if a distribution bugtask already exists for a given bug.

    :on_create: A boolean set to True if the task is being added, otherwise
    False.

    If validation fails, a WidgetsError will be raised.
    """
    from canonical.launchpad.helpers import shortlist

    distribution_tasks_for_bug = distribution.searchTasks(
        BugTaskSearchParams(user=getUtility(ILaunchBag).user, bug=bug))
    distribution_tasks_for_bug = shortlist(
        distribution_tasks_for_bug, longest_expected=5)

    if sourcepackagename:
        # Ensure this distribution/sourcepackage task is unique, and that there
        # isn't already a generic task open on the distribution for this bug,
        # because if there were, that task should be reassigned to the
        # sourcepackage, rather than a new task opened.
        for task in distribution_tasks_for_bug:
            if task.sourcepackagename is None and on_create:
                raise WidgetsError([
                    LaunchpadValidationError(_(
                        'This bug is already open on %s with no package '
                        'specified. You should fill in a package name for the '
                        'existing bug.') % (distribution.displayname))
                    ])
            elif task.sourcepackagename == sourcepackagename:
                raise WidgetsError([
                    LaunchpadValidationError(_(
                        'This bug has already been reported on %s (%s).') % (
                        sourcepackagename.name, distribution.name))
                    ])
    else:
        # Prevent having a task on only the distribution if there's at least one
        # task already on the distribution, whether or not that task also has a
        # source package.
        if distribution_tasks_for_bug:
            if on_create:
                raise WidgetsError([
                    LaunchpadValidationError(_(
                        'This bug is already open on %s or packages in %s. '
                        'Please specify an affected package in which the bug '
                        'has not yet been reported.') % (
                        distribution.displayname, distribution.displayname))
                    ])


def valid_upstreamtask(bug, product):
    """Check if a product bugtask already exists for a given bug.

    If it exists, WidgetsError will be raised.
    """
    errors = []
    user = getUtility(ILaunchBag).user
    params = BugTaskSearchParams(user, bug=bug)
    if product.searchTasks(params):
        errors.append(LaunchpadValidationError(_(
            'A fix for this bug has already been requested for %s' %
            product.displayname)))

    if errors:
        raise WidgetsError(errors)


# XXX: Not sure if this is the best place for this, but it'll sit here for
# now, as it's not used anywhere else.
# Guilherme Salgado, 2006-04-25
_countries_where_postcode_is_required = """
    AT Austria
    DZ Algeria
    AR Argentina
    AM Armenia
    AU Australia
    AZ Azerbaijan
    BH Bahrain
    BD Bangladesh
    BY Belarus
    BE Belgium
    BA Bosnia and Herzegovina
    BR Brazil
    BN Brunei Darussalam
    BG Bulgaria
    CA Canada
    CN China
    CR Costa Rica
    HR Croatia
    CU Cuba
    CY Cyprus
    CZ Czech Republic
    DK Denmark
    DO Dominican Republic
    EC Ecuador
    EG Egypt
    SV El Salvador
    EE Estonia
    FI Finland
    FR France
    GE Georgia
    DE Germany
    GR Greece
    GT Guatemala
    GW Guinea-Bissa
    HT Haiti
    VA Holy See (Vatican City State)
    HN Honduras
    HU Hungary
    IS Iceland
    IN India
    ID Indonesia
    IR Iran, Islamic Republic of
    IL Israel
    IT Italy
    JP Japan
    JO Jordan
    KZ Kazakhstan
    KE Kenya
    KW Kuwait
    KG Kyrgyzstan
    LA Lao People's Democratic Republic
    LV Latvia
    LI Liechtenstein
    LT Lithuania
    LU Luxembourg
    MK Macedonia, Republic of
    MG Madagascar
    MY Malaysia
    MV Maldives
    MT Malta
    MX Mexico
    MD Moldova, Republic of
    MC Monaco
    MN Mongolia
    MA Morocco
    MZ Mozambique
    NP Nepal
    NL Netherlands
    NI Nicaragua
    NO Norway
    OM Oman
    PK Pakistan
    PH Philippines
    PL Poland
    PT Portugal
    RO Romania
    RU Russian Federation
    SA Saudi Arabia
    CS Serbia and Montenegro
    SG Singapore
    SK Slovakia
    SI Slovenia
    ZA South Africa
    KR Korea, Republic of
    ES Spain
    LK Sri Lanka
    SD Sudan
    SZ Swaziland
    SE Sweden
    CH Switzerland
    TJ Tajikistan
    TH Thailand
    TN Tunisia
    TM Turkmenistan
    UA Ukraine
    GB United Kingdom
    US United States
    UY Uruguay
    UZ Uzbekistan
    VE Venezuela
    VN Viet Nam
    ZM Zambia
    """
country_codes_where_postcode_is_required = set(
    line.strip().split(' ', 1)[0] 
    for line in _countries_where_postcode_is_required.strip().splitlines())


def valid_password(password):
    """Return True if the argument is a valid password.

    A valid password contains only ASCII characters in range(32,127).
    No ASCII control characters are allowed.

    password that contains only valid ASCII characters
    >>> valid_password(u"All ascii password with spaces.:\\&/")
    True

    password that contains some non-ASCII character (value > 127)
    >>> valid_password(u"password with some non-ascii" + unichr(195))
    False

    password that contains ASCII control characters (0 >= value >= 31)
    >>> valid_password(u"password with control chars" + chr(20))
    False

    empty password.
    >>> valid_password(u"")
    True

    """
    assert isinstance(password, unicode)
    valid_chars = [chr(x) for x in range(32,127)]
    invalid = set(password) - set(valid_chars)
    if invalid:
        return False
    else:
        return True


def validate_date_interval(start_date, end_date, error_msg=None):
    """Check if start_date precedes end_date.

    >>> from datetime import datetime
    >>> start = datetime(2006, 7, 18)
    >>> end = datetime(2006, 8, 18)
    >>> validate_date_interval(start, end)
    >>> validate_date_interval(end, start)
    Traceback (most recent call last):
    ...
    WidgetsError: LaunchpadValidationError: This event can't start after it
    ends.
    >>> validate_date_interval(end, start, error_msg="A custom error msg")
    Traceback (most recent call last):
    ...
    WidgetsError: LaunchpadValidationError: A custom error msg

    """
    if error_msg is None:
        error_msg = _("This event can't start after it ends.")
    errors = []
    if start_date >= end_date:
        errors.append(LaunchpadValidationError(error_msg))
    if errors:
        raise WidgetsError(errors)
