# Copyright 2009 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

import re
import gettext
from lp.translations.interfaces.translations import (
    TranslationConstants)


class BadPluralExpression(Exception):
    """Local "escape hatch" exception for unusable plural expressions."""

def make_friendly_plural_forms(expression, pluralforms_count):
    """Return a dict's list of plural forms' examples from an expression."""
    expression_ = make_plural_function(expression)
    forms = {}

    for n in range(1, 200):
        forms.setdefault(expression_(n), [])
        # Giving a limit of 6 examples per plural form. If all the forms were
        # contemplated, it stops.
        if (len(forms[expression_(n)]) == 6 and
                len(forms) == pluralforms_count):
            break
        if len(forms[expression_(n)]) == 6:
            continue
        forms[expression_(n)].append(n)

    return [{'form' : k, 'examples' : v} for (k, v) in forms.iteritems()]


def make_plural_function(expression):
    """Create a lambda function for C-like plural expression."""
    # Largest expressions we could find in practice were 113 characters
    # long.  500 is a reasonable value which is still 4 times more than
    # that, yet not incredibly long.
    if expression is None or len(expression) > 500:
        raise BadPluralExpression

    # Guard against '**' usage: it's not useful in evaluating
    # plural forms, yet can be used to introduce a DoS.
    if expression.find('**') != -1:
        raise BadPluralExpression

    # We allow digits, whitespace [ \t], parentheses, "n", and operators
    # as allowed by GNU gettext implementation as well.
    if not re.match('^[0-9 \t()n|&?:!=<>+%*/-]*$', expression):
        raise BadPluralExpression

    try:
        function = gettext.c2py(expression)
    except (ValueError, SyntaxError):
        raise BadPluralExpression

    return function


def make_plurals_identity_map():
    """Return a dict mapping each plural form number onto itself."""
    return dict(enumerate(xrange(TranslationConstants.MAX_PLURAL_FORMS)))


def plural_form_mapper(first_expression, second_expression):
    """Maps plural forms from one plural formula to the other.

    Returns a dict indexed by indices in the `first_formula`
    pointing to corresponding indices in the `second_formula`.
    """
    identity_map = make_plurals_identity_map()
    try:
        first_func = make_plural_function(first_expression)
        second_func = make_plural_function(second_expression)
    except BadPluralExpression:
        return identity_map

    # Can we create a mapping from one expression to the other?
    mapping = {}
    for n in range(1000):
        try:
            first_form = first_func(n)
            second_form = second_func(n)
        except (ArithmeticError, TypeError):
            return identity_map

        # Is either result out of range?
        valid_forms = range(TranslationConstants.MAX_PLURAL_FORMS)
        if first_form not in valid_forms or second_form not in valid_forms:
            return identity_map

        if first_form in mapping:
            if mapping[first_form] != second_form:
                return identity_map
        else:
            mapping[first_form] = second_form

    # The mapping must be an isomorphism.
    if sorted(mapping.keys()) != sorted(mapping.values()):
        return identity_map

    # Fill in the remaining inputs from the identity map:
    result = identity_map.copy()
    result.update(mapping)
    return result

