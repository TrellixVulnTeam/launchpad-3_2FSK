# Copyright 2008 Canonical Ltd.  All rights reserved.

__metaclass__ = type

__all__ = [
    'PackageSearchViewBase'
    ]

from canonical.cachedproperty import cachedproperty
from canonical.launchpad.webapp.batching import BatchNavigator
from canonical.launchpad.webapp.publisher import LaunchpadView

class PackageSearchViewBase(LaunchpadView):
    """A common package search interface"""

    def initialize(self):
        """Save the search text set by the user."""
        self.text = self.request.get("text", None)

    @property
    def search_requested(self):
        """Return whether the current view included a search request."""
        return self.text is not None

    @property
    def matches(self):
        """Return the number of matched search results."""
        return self.search_results.count()

    @property
    def detailed(self):
        """Return whether detailed results should be provided."""
        return self.matches <= 5

    @property
    def batchnav(self):
        """Return the batch navigator for the search results."""
        return BatchNavigator(self.search_results, self.request)

    @cachedproperty
    def search_results(self):
        """Search for packages matching the request text.
        
        Try to find the packages that match the given text, then present
        those as a list. Cache previous results so the search is only done
        once.
        """
        return self.contextSpecificSearch()

    def contextSpecificSearch(self):
        """Call the context specific search."""
        raise NotImplementedError(
            "do_context_specific_search needs to be implemented in sub-class"
            )
