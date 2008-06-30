# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Miscelaneous functions for publisher."""

__metaclass__ = type

__all__ = [
    'PublishingTunableLoop',
    'process_in_batches',
    ]


import gc
from operator import itemgetter

from storm.zope.interfaces import IZStorm

from zope.interface import implements
from zope.component import getUtility

from canonical.launchpad.interfaces.looptuner import ITunableLoop
from canonical.launchpad.utilities.looptuner import LoopTuner
from canonical.mem import resident


def count_alive(store, logger):
    """Print counts of how many alive objects the store knows about."""
    counts = {}
    for obj_info in store._iter_alive():
        name = obj_info.cls_info.cls.__name__
        counts[name] = counts.get(name, 0) + 1

    sorted_items = sorted(counts.items(), key=itemgetter(0), reverse=True)
    for (name, count) in sorted_items:
        logger.debug('%-20s %d' % (name, count))


# Here begins the hack. Storm + StupidCache are not helping us iterating
# huge sets of records. The best result was produced by performing the
# task in small batches with StupidCache enabled and clearing caches with
# gc and clear_current_connection_cache. All other tested variations were
# slower and consumed more memory.
#
# 1 StupidCache + clear_current_connection_caches() [this];
# 2 storm.Cache + clear_current_connection_caches() [no difference];
# 3 StupidCache + store.invalidate(obj) [references left behind];
# 4 stormCache + store.invlaidate(obj)  [references left behind];
# 5 No batches [memory exhausted].

# XXX cprov 20080630: If we decide to keep this code/functionality, which
# I think we should, independently of the need to cleanup the cache after
# processing each batch. We should generalize and test it as suggested in
# bug #244328.

class PublishingTunableLoop(object):
    """An `ITunableLoop` for dealing with huge publishing result sets."""

    implements(ITunableLoop)

    def __init__(self, input, task, logger):
        self.input = input
        self.task = task
        self.logger = logger
        self.total_updated = 0
        self.total_size = input.count()
        self.offset = 0

    def isDone(self):
        """See `ITunableLoop`."""
        return self.offset == self.total_size

    def __call__(self, chunk_size):
        """Run the initialized 'task' with a limited batch of 'input'.

        See `ITunableLoop`.
        """
        chunk_size = int(chunk_size)
        start = self.offset
        end = self.offset + chunk_size

        mem_size = resident() / (2 ** 20)
        self.logger.debug("Batch (%d..%d) [%d MiB]" % (start, end, mem_size))

        batch = self.input[start:end]
        for pub in batch:
            start += 1
            self.offset = start
            self.task(pub)
            self.total_updated += 1

        # Invalidate the whole cache for the main store, this we we will also
        # get rid of all the foreign keys referred by the publishing records.
        main_store = getUtility(IZStorm).get("main")
        main_store.invalidate()
        gc.collect()

        # Extra debug not necessary (unwanted, in fact) in production.
        # Print the number of 'alive' cache items.
        # count_alive(getUtility(IZStorm).get('main'), self.logger)


def process_in_batches(input, task, logger, goal_seconds=60,
                       minimum_chunk_size=10000):
    """Use `LoopTuner` to run the given task in smaller batches.

    Run callable 'task' for item of 'input', but do it in small batches
    cleaning up the cache after each one is processed.

    See `PublishingTunableLoop` for further details.

    :param input: `SelectResult` to be treated;
    :param task: callable to be executed for each batch;
    :param logger: `Logger` intance used to print information
        (debug level);
    :param goal_seconds: ideal time to spend processing each batch,
        defaults to 60 s;
    :param minimum_chunk_size: minimum number of items to be processed in
        each batch, defaults to 10000
    """
    loop = PublishingTunableLoop(input, task, logger)
    loop_tuner = LoopTuner(loop, goal_seconds=goal_seconds,
                           minimum_chunk_size=minimum_chunk_size)
    loop_tuner.run()
