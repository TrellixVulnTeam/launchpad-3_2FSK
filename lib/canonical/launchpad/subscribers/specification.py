# Copyright 2006 Canonical Ltd.  All rights reserved.

__metaclass__ = type


from canonical.lp.dbschema import SpecificationGoalStatus


def specification_goalstatus(spec, event):
    """Update goalstatus if productseries or distrorelease is changed."""
    delta = spec.getDelta(event.object_before_modification, event.user)
    if delta is None:
        return
    if delta.productseries is not None or delta.distrorelease is not None:
        spec.goalstatus = SpecificationGoalStatus.PROPOSED
