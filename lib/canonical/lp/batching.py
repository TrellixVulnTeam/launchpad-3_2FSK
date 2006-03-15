# Copyright 2004-2005 Canonical Ltd.  All rights reserved.

__metaclass__ = type

import cgi, urllib

from zope.interface import implements
from canonical.lp.z3batching import _Batch
from canonical.lp.interfaces import IBatchNavigator, ITableBatchNavigator

class BatchNavigator:

    implements(IBatchNavigator)

    def __init__(self, results, request, size=None):
        start = request.get('batch_start', 0)
        try:
            start = int(start)
        except ValueError:
            # We ignore invalid request variables since it probably
            # means the user finger-fumbled it
            start = 0
        self.batch = _Batch(results, size=size, start=start)
        self.request = request

    def cleanQueryString(self, query_string):
        """Removes batch_start and batch_end params from a query string."""
        query_parts = cgi.parse_qsl(query_string, keep_blank_values=True,
                                    strict_parsing=False)
        return urllib.urlencode(
            [(key, value) for (key, value) in query_parts
             if key not in ['batch_start', 'batch_end']])

    def generateBatchURL(self, batch):
        qs = self.request.environment.get('QUERY_STRING', '')
        qs = self.cleanQueryString(qs)
        if qs:
            qs += "&"

        url = ""
        if not batch:
            return url

        url = "%s?%sbatch_start=%d&batch_end=%d" % \
            (str(self.request.URL), qs, batch.startNumber() - 1,
             batch.endNumber())
        return url

    def getBatches(self):
        batch = _Batch(self.batch.list, size = self.batch.size)
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
                urls.append({ '['+str(start + 1)+']' : url })
            else:
                urls.append({ start + 1 : url })
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

