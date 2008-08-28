# Copyright 2004-2007 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213

from zope.interface import Interface, Attribute

__all__ = [
    'IGeoIP',
    'IGeoIPRecord',
    'IRequestLocalLanguages',
    'IRequestPreferredLanguages',
    ]


class IGeoIP(Interface):
    """The GeoIP utility, which represents the GeoIP database."""

    def getRecordByAddress(ip_address):
        """Return the IGeoIPRecord for the given IP address, or None."""

    def getCountryByAddr(ip_address):
        """Find and return an ICountry based on the given IP address.

        :param ip_address: Must be text in the dotted-address notation,
            for example '196.131.31.25'
        """


class IGeoIPRecord(Interface):
    """A single record in the GeoIP database.

    A GeoIP record gathers together all of the relevant information for a
    single IP address or machine name in the DNS.
    """

    latitude = Attribute("The geographic latitude, in real degrees.")
    latitude = Attribute("The geographic longitude, in real degrees.")
    time_zone = Attribute("The time zone.")


class IRequestLocalLanguages(Interface):

    def getLocalLanguages():
        """Return a list of the Language objects which represent languages
        spoken in the country from which that IP address is likely to be
        coming."""


class IRequestPreferredLanguages(Interface):

    def getPreferredLanguages():
        """Return a list of the Language objects which represent languages
        listed in the HTTP_ACCEPT_LANGUAGE header."""
