"""Identifies files for download.

This module uses the walker and filter modules to identify files for
download.
"""

__metaclass__ = type
__all__ = [
    'Hose',
    ]

from hct.util import log

from canonical.launchpad.scripts.productreleasefinder.filter import Filter
from canonical.launchpad.scripts.productreleasefinder.walker import (
    walk, combine_url)


class Hose:
    """Hose.

    This class should be instantiated with a dictionary of url and glob pairs,
    it will use a walker to recursively decend each URL and map each URL
    to a file.

    It can be used as an iterator to yield (key, url) for each URL where
    key is one of the dictionary keys or None if none matched.
    """

    def __init__(self, filters=(), log_parent=None):
        self.log = log.get_logger("Hose", log_parent)
        self.filter = Filter(filters, log_parent=self.log)
        self.urls = self.reduceWork([pattern.base_url for pattern in filters])

    def reduceWork(self, url_list):
        """Simplify URL list to remove children of other elements.

        Reduces the amount of work we need to do by removing any URL from
        the list whose parent also appears in the list.  Returns the
        reduced list.
        """
        self.log.info("Reducing URL list.")
        urls = []
        url_list = list(url_list)
        while len(url_list):
            url = url_list.pop(0)
            for check_url in urls + url_list:
                if url.startswith(check_url):
                    self.log.debug("Discarding %s as have %s", url, check_url)
                    break
            else:
                urls.append(url)

        return urls

    def run(self):
        """Run over the URL list."""
        self.log.info("Identifying URLs")
        for base_url in self.urls:
            for dirpath, dirnames, filenames in walk(base_url, self.log):
                for filename in filenames:
                    url = combine_url(base_url, dirpath, filename)
                    key = self.filter.check(url)
                    yield (key, url)

    __iter__ = run
