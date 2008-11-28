# Copyright 2008 Canonical Ltd.  All rights reserved.

"""Decorator helpers that simplify class composition."""


__metaclass__ = type


__all__ = ['decorates', 'Passthrough']


import sys
from types import ClassType

from zope.interface.advice import addClassAdvisor
from zope.interface import classImplements


def decorates(interface, context='context'):
    """Make an adapter into a decorator.

    Use like:

        class RosettaProject:
            implements(IRosettaProject)
            decorates(IProject)

            def __init__(self, context):
                self.context = context

            def methodFromRosettaProject(self):
                return self.context.methodFromIProject()

    If you want to use a different name than "context" then you can explicitly
    say so:

        class RosettaProject:
            implements(IRosettaProject)
            decorates(IProject, context='project')

            def __init__(self, project):
                self.project = project

            def methodFromRosettaProject(self):
                return self.project.methodFromIProject()

    The adapter class will implement the interface it is decorating.

    The minimal decorator looks like this:

    class RosettaProject:
        decorates(IProject)

        def __init__(self, context):
            self.context = context

    """
    # pylint: disable-msg=W0212
    frame = sys._getframe(1)
    locals = frame.f_locals

    # Try to make sure we were called from a class def
    if (locals is frame.f_globals) or ('__module__' not in locals):
        raise TypeError("Decorates can be used only from a class definition.")

    locals['__decorates_advice_data__'] = interface, context
    addClassAdvisor(_decorates_advice, depth=2)


def _decorates_advice(cls):
    """Add a Passthrough class for each missing interface attribute.

    This function connects the decorator class to the decoratee class.
    Only new-style classes are supported.
    """
    interface, contextvar = cls.__dict__['__decorates_advice_data__']
    del cls.__decorates_advice_data__
    if type(cls) is ClassType:
        raise TypeError(
            'Cannot use decorates() on a classic class: %s.' % cls)
    classImplements(cls, interface)
    for name in list(interface):
        if not hasattr(cls, name):
            setattr(cls, name, Passthrough(name, contextvar))

    # pylint: disable-msg=W0101
    def __eq__(self, other):
        #return getattr(self, contextvar) == other
        context = getattr(self, contextvar)
        if isinstance(other, type(context)):
            return context == other
        return NotImplemented
    cls.__eq__ = __eq__

    def __ne__(self, other):
        return not self.__eq__(other)
    cls.__ne__ = __ne__

    return cls


class Passthrough:
    """Call the decorated class for the decorator class."""
    def __init__(self, name, contextvar):
        self.name = name
        self.contextvar = contextvar

    def __get__(self, inst, cls=None):
        if inst is None:
            return self
        else:
            return getattr(getattr(inst, self.contextvar), self.name)

    def __set__(self, inst, value):
        setattr(getattr(inst, self.contextvar), self.name, value)

    def __delete__(self, inst):
        raise NotImplementedError
