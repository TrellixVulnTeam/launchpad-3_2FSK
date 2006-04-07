# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import cgi, urllib

from zope.interface import implements

from canonical.config import config
from canonical.launchpad.webapp.z3batching.batch import _Batch
from canonical.launchpad.webapp.interfaces import (
    IBatchNavigator, ITableBatchNavigator,
    )

class BatchNavigator:

    implements(IBatchNavigator)

    def __init__(self, results, request, size=None):
        """Constructs a BatchNavigator instance.

        results is an iterable of results. request is the web request
        being processed. size is a default batch size which the callsite
        can choose to provide.

        The request will be inspected for a start variable; if set, it
        indicates which point we are currently displaying at. It will
        also be inspected for a batch variable; if set, it will be used
        instead of the size supplied in the callsite.
        """
        # In this code we ignore invalid request variables since it
        # probably means the user finger-fumbled it in the request.
        start = request.get('start', 0)
        try:
            start = int(start)
        except ValueError:
            start = 0

        user_size = request.get('batch', None)
        if user_size:
            try:
                size = int(user_size)
            except ValueError:
                pass

        self.batch = _Batch(results, start=start, size=size)
        self.request = request

    def cleanQueryString(self, query_string):
        """Removes start and batch params from a query string."""
        query_parts = cgi.parse_qsl(query_string, keep_blank_values=True,
                                    strict_parsing=False)
        return urllib.urlencode(
            [(key, value) for (key, value) in query_parts
             if key not in ['start', 'batch']])

    def generateBatchURL(self, batch):
        url = ""
        if not batch:
            return url

        qs = self.request.environment.get('QUERY_STRING', '')
        qs = self.cleanQueryString(qs)
        if qs:
            qs += "&"

        start = batch.startNumber() - 1
        size = batch.size
        base_url = str(self.request.URL)
        url = "%s?%sstart=%d&batch=%d" % (base_url, qs, start, size)
        return url

    def getBatches(self):
        batch = self.batch.firstBatch()
        batches = [batch]
        while 1:
            batch = batch.nextBatch()
            if not batch:
                break
            batches.append(batch)
        return batches

    def prevBatchURL(self):
        return self.generateBatchURL(self.batch.prevBatch())

    def nextBatchURL(self):
        return self.generateBatchURL(self.batch.nextBatch())

    def batchPageURLs(self):
        batches = self.getBatches()
        urls = []
        size = len(batches)

        nextb = self.batch.nextBatch()

        # Find the current page
        if nextb:
            current = nextb.start/nextb.size
        else:
            current = size

        self.current = current
        # Find the start page to show
        if (current - 5) > 0:
            start = current-5
        else:
            start = 0

        # Find the last page to show
        if (start + 10) < size:
            stop = start + 10
        else:
            stop = size

        initial = start
        while start < stop:
            this_batch = batches[start]
            url = self.generateBatchURL(this_batch)
            if (start+1) == current:
                urls.append({'['+str(start + 1)+']' : url})
            else:
                urls.append({start + 1 : url})
            start += 1

        if current != 1:
            url = self.generateBatchURL(batches[0])
            urls.insert(0, {'_first_' : url})
        if current != size:
            url = self.generateBatchURL(batches[size-1])
            urls.append({'_last_':url})

        return urls

    def currentBatch(self):
        return self.batch


class TableBatchNavigator(BatchNavigator):
    """See canonical.launchpad.interfaces.ITableBatchNavigator."""
    implements(ITableBatchNavigator)

    def __init__(self, results, request, size=None, columns_to_show=None):
        BatchNavigator.__init__(self, results, request, size)

        self.show_column = {}
        if columns_to_show:
            for column_to_show in columns_to_show:
                self.show_column[column_to_show] = True

