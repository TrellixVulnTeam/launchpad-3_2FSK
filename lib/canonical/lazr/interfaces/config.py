# Copyright 2007 Canonical Ltd.  All rights reserved.
# pylint: disable-msg=E0211,E0213
"""Interfaces for process configuration.."""

__metaclass__ = type

__all__ = [
    'ConfigErrors',
    'ConfigSchemaError',
    'IConfigData',
    'NoConfigError',
    'IConfigLoader',
    'IConfigSchema',
    'InvalidSectionNameError',
    'ISection',
    'ISectionSchema',
    'IStackableConfig',
    'NoCategoryError',
    'RedefinedKeyError',
    'RedefinedSectionError',
    'UnknownKeyError',
    'UnknownSectionError']

from zope.interface import Interface, Attribute


class ConfigSchemaError(Exception):
    """A base class of all `IConfigSchema` errors."""


class RedefinedKeyError(ConfigSchemaError):
    """A key in a section cannot be redefined."""


class RedefinedSectionError(ConfigSchemaError):
    """A section in a config file cannot be redefined."""


class InvalidSectionNameError(ConfigSchemaError):
    """The section name contains more than one category."""


class NoCategoryError(LookupError):
    """No `ISectionSchema`s belong to the category name."""


class UnknownSectionError(ConfigSchemaError):
    """The config has a section that is not in the schema."""


class UnknownKeyError(ConfigSchemaError):
    """The section has a key that is not in the schema."""

class NoConfigError(ConfigSchemaError):
    """No config has the name."""

class ConfigErrors(ConfigSchemaError):
    """The errors in a Config.

    The list of errors can be accessed via the errors attribute.
    """

    def __init__(self, message, errors=None):
        """Initialize the error with a message and errors.

        :param message: a message string
        :param errors: a list of errors in the config, or None
        """
        self.message = message
        self.errors = errors

    def __str__(self):
        return '%s: %s' % (self.__class__.__name__, self.message)


class ISectionSchema(Interface):
    """Defines the valid keys and default values for a configuration group."""
    name = Attribute("The section name.")
    optional = Attribute("Is the section optional in the config?")

    def __iter__():
        """Iterate over the keys."""

    def __contains__(name):
        """Return True or False if name is a key."""

    def __getitem__(key):
        """Return the default value of the key.

        :raise `KeyError`: if the key does not exist.
        """


class ISection(ISectionSchema):
    """Defines the values for a configuration group."""
    schema = Attribute("The ISectionSchema that defines this ISection.")


class IConfigLoader(Interface):
    """A configuration file loader."""

    def load(filename):
        """Load a configuration from the file at filename."""

    def loadFile(source_file, filename=None):
        """Load a configuration from the open source_file.

        :param source_file: A file-like object that supports read() and
            readline()
        :param filename: The name of the configuration. If filename is None,
            The name will be taken from source_file.name.
        """


class IConfigSchema(Interface):
    """A process configuration schema.

    The config file contains sections enclosed in square brackets ([]).
    The section name may be divided into major and minor categories using a
    dot (.). Beneath each section is a list of key-value pairs, separated
    by a colon (:). Multiple sections with the same major category may have
    their keys defined in another section that appends the '.template'
    suffix to the category name. A section with '.optional' suffix is not
    required. Lines that start with a hash (#) are comments.
    """
    name = Attribute('The basename of the config filename.')
    filename = Attribute('The path to config file')
    category_names = Attribute('The list of section category names.')

    def __iter__():
        """Iterate over the `ISectionSchema`s."""

    def __contains__(name):
        """Return True or False if the name matches a `ISectionSchema`."""

    def __getitem__(name):
        """Return the `ISectionSchema` with the matching name.

        :raise `NoSectionError`: if the no ISectionSchema has the name.
        """

    def getByCategory(name):
        """Return a list of ISectionSchemas that belong to the category name.

        ISectionSchema names may be made from a category name and a group
        name, separated by a dot (.). The category is synonymous with a
        arbitrary resource such as a database or a vhost. Thus database.bugs
        and database.answers are two sections that both use the database
        resource.

        :raise `CategoryNotFound`: if no sections have a name that starts
            with the category name.
        """


class IConfigData(IConfigSchema):
    """A process configuration.

    See `IConfigSchema` for more information about the config file format.
    """


class IStackableConfig(Interface):
    """A configuration that is built from configs that extend each other.

    A config may extend another config so that a configuration for a
    process need only define the localized sections and keys. The
    configuration is constructed from a stack of data that defines,
    and redefines, the sections and keys in the configuration. Each config
    overlays its data to define the final configuration.

    A config file declares that is extends another using the 'extends' key
    in the 'meta' section of the config data file:
        [meta]
        extends: common.conf

    The push() and pop() methods can be used to test processes where the
    test environment must be configured differently.
    """
    schema = Attribute("The schema that defines the config.")
    extends = Attribute("The configuration that this config extends.")
    overlays = Attribute("The stack of ConfigData that define this config.")

    def validate():
        """Return True if the config is valid for the schema.

        :raise `ConfigErrors`: if the are errors. A list of all schema
            problems can be retrieved via the errors property.
        """

    def push(conf_name, conf_data):
        """Overlay the config with unparsed config data.

        :param conf_name: the name of the config.
        :param conf_data: a string of unparsed config data.

        This method appends the parsed ConfigData to the overlays property.
        """

    def pop(conf_name):
        """Remove conf_name from the overlays stack.

        :param conf_name: the name of the configdata to remove.
        :return: the tuple of ConfigData that was removed from overlays.
        :raise NoConfigError: if no configdata has the conf_name.

        This method removes the named ConfigData from the stack; Configdata
        above the named configdata are removed too.
        """
