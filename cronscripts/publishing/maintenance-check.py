#!/usr/bin/python
#
# python port of the nice maintainace-check script by  Nick Barcet
# 
# taken from:
#  https://code.edge.launchpad.net/~mvo/ubuntu-maintenance-check/python-port
# (where it will vanish once taken here)

import apt
import apt_pkg
import logging
import os
import sys
import urllib2
import urlparse

from optparse import OptionParser

# This is fun! We have a bunch of cases for 10.04 LTS
#
#  - distro "ubuntu" follows SUPPORT_TIMEFRAME_LTS but only for
#    amd64/i386
#  - distros "kubuntu", "edubuntu" and "netbook" need to be
#    considered *but* only follow SUPPORT_TIMEFRAME
#  - anything that is in armel follows SUPPORT_TIMEFRAME
#  

# codename of the lts releases
LTS_RELEASES = [ "dapper", "hardy", "lucid" ]

# architectures that are full supported (including LTS time)
PRIMARY_ARCHES =  ["i386", "amd64"]

# architectures we support (but not for LTS time)
SUPPORTED_ARCHES = PRIMARY_ARCHES + ["armel"]

# what defines the seeds is documented in wiki.ubuntu.com/SeedManagement
SERVER_SEEDS = [ "supported-server", "server-ship"]
DESKTOP_SEEDS = ["ship", "supported-desktop"]
SUPPORTED_SEEDS = [ "all" ]

# normal support timeframe
# time, seeds, arches
SUPPORT_TIMEFRAME = [
    ("18m", SUPPORTED_SEEDS),
]

# lts support timeframe
# time, seeds, arches
SUPPORT_TIMEFRAME_LTS = [
    ("5y", SERVER_SEEDS),
    ("3y", DESKTOP_SEEDS),
    ("18m", SUPPORTED_SEEDS),
]

# distro names and if they get LTS support (order is important)
DISTRO_NAMES_AND_LTS_SUPPORT = [ ("ubuntu",   True),
                                 ("kubuntu",  False),
                                 ("edubuntu", False),
                                 ("netbook",  False),
                               ]

# germinate output base directory
BASE_URL = "http://people.canonical.com/~ubuntu-archive/germinate-output/"

# hints dir url, hints file is "$distro.hints" by default
# (e.g. lucid.hints)
HINTS_DIR_URL = "http://people.canonical.com/~ubuntu-archive/seeds/platform.%s/SUPPORTED_HINTS"

# we need the archive root to parse the Sources file to support
# by-source hints
ARCHIVE_ROOT = "http://archive.ubuntu.com/ubuntu"

# support timeframe tag used in the Packages file
SUPPORT_TAG = "Supported"

def get_binaries_for_source_pkg(srcname):
    """ Return all binary package names for the given source package name.

    :param srcname: The source package name.
    :return: A list of binary package names.
    """
    pkgnames = set()
    recs = apt_pkg.GetPkgSrcRecords()
    while recs.Lookup(srcname):
        for binary in recs.Binaries:
            pkgnames.add(binary)
    return pkgnames

def expand_src_pkgname(pkgname):
    """ Expand a package name if it is prefixed with src.

    If the package name is prefixed with src it will be expanded
    to a list of binary package names. Otherwise the original
    package name will be returned.
    
    :param pkgname: The package name (that may include src:prefix).
    :return: A list of binary package names (the list may be one element long).
    """
    if not pkgname.startswith("src:"):
        return [pkgname]
    return get_binaries_for_source_pkg(pkgname.split("src:")[1])

def create_and_update_deb_src_source_list(distroseries):
    """ Create sources.list and update cache.

    This creates a sources.list file with deb-src entries for a given 
    distroseries and apt.Cache.update() to make sure the data is up-to-date.
    :param distro: The code name of the distribution series (e.g. lucid).
    :return: None
    :raises: IOError: When cache update fails.
    """
    # apt root dir
    rootdir="./aptroot.%s" % distroseries
    sources_list_dir = os.path.join(rootdir, "etc","apt")
    if not os.path.exists(sources_list_dir):
        os.makedirs(sources_list_dir)
    sources_list = open(os.path.join(sources_list_dir, "sources.list"),"w")
    for pocket in [
        "%s" % distroseries, 
        "%s-updates" % distroseries, 
        "%s-security" % distroseries]:
        sources_list.write(
            "deb-src %s %s main restricted\n" % (
                ARCHIVE_ROOT, pocket))
    sources_list.close()
    cache = apt.Cache(rootdir=rootdir)
    cache.update(apt.progress.FetchProgress())

def get_structure(distroname, version):
    """ Get structure file conent for named distro and distro version.
    
    :param name: Name of the distribution (e.g. kubuntu, ubuntu, xubuntu).
    :param version: Code name of the distribution version (e.g. lucid).
    :return: List of strings with the structure file content
    """
    f = urllib2.urlopen("%s/%s.%s/structure" % (BASE_URL, distroname, version))
    structure = f.readlines()
    f.close()
    return structure

def expand_seeds(structure, seedname):
    """ Expand seed by its dependencies using the strucure file.

    :param structure: The content of the STRUCTURE file as string list.
    :param seedname: The name of the seed as string that needs to be expanded.
    :return: a set() for the seed dependencies (excluding the original seedname)
    """
    seeds = []
    for line in structure:
        if line.startswith("%s:" % seedname):
            seeds += line.split(":")[1].split()
            for seed in seeds:
                seeds += expand_seeds(structure, seed)
    return set(seeds)

def get_packages_for_seeds(name, distro, seeds):
    """
    get packages for the given name (e.g. ubuntu) and distro release 
    (e.g. lucid) that are in the given list of seeds
    returns a set() of package names
    """
    pkgs_in_seeds = {}
    for bseed in seeds:
        for seed in [bseed]: #, bseed+".build-depends", bseed+".seed"]:
            pkgs_in_seeds[seed] = set()
            seedurl = "%s/%s.%s/%s" % (BASE_URL,name, distro, seed)
            logging.debug("looking for '%s'" % seedurl)
            try:
                f = urllib2.urlopen(seedurl)
                for line in f:
                    # ignore lines that are not a package name (headers etc)
                    if line[0] < 'a' or line[0] > 'z':
                        continue
                    # lines are (package,source,why,maintainer,size,inst-size)
                    if options.source_packages:
                        pkgname = line.split("|")[1]
                    else:
                        pkgname = line.split("|")[0]
                    pkgs_in_seeds[seed].add(pkgname.strip())
                f.close()
            except Exception, e:
                logging.error("seed %s failed (%s)" % (seedurl, e))
    return pkgs_in_seeds

def what_seeds(pkgname, seeds):
    in_seeds = set()
    for s in seeds:
        if pkgname in seeds[s]:
            in_seeds.add(s)
    return in_seeds

def get_packages_support_time(structure, name, pkg_support_time, support_timeframe_list):
    """
    input a structure file and a list of pair<timeframe, seedlist>
    return a dict of pkgnames -> support timeframe string
    """
    for (timeframe, seedlist) in support_timeframe_list:
        expanded = set()
        for s in seedlist:
            expanded.add(s)
            expanded |= expand_seeds(structure, s)
        pkgs_in_seeds = get_packages_for_seeds(name, distro, expanded)
        for seed in pkgs_in_seeds:
            for pkg in pkgs_in_seeds[seed]:
                if not pkg in pkg_support_time:
                    pkg_support_time[pkg] = timeframe
                    if options.with_seeds:
                        pkg_support_time[pkg] += " (%s)" % ", ".join(what_seeds(pkg, pkgs_in_seeds))

    return pkg_support_time

if __name__ == "__main__":
    parser = OptionParser()
    parser.add_option("--with-seeds", "", default=False,
                      action="store_true", 
                      help="add seed(s) of the package that are responsible for the maintaince time")
    parser.add_option("--source-packages", "", default=False,
                      action="store_true", 
                      help="show as source pkgs")
    parser.add_option("--hints-file", "", default=None,
                      help="use diffenrt use hints file location")
    (options, args) = parser.parse_args()

    # init
    if len(args) > 0:
        distro = args[0]
        if distro[0] < 'h':
            print "ERROR: only hardy or later is supported"
            sys.exit(1)
    else:
        distro = "lucid"

    # make sure our deb-src information is up-to-date
    create_and_update_deb_src_source_list(distro)

    if options.hints_file:
        hints_file = options.hints_file
        (schema, netloc, path, query, fragment) = urlparse.urlsplit(hints_file)
        if not schema:
            hints_file = "file:%s" % path
    else:
        hints_file = HINTS_DIR_URL % distro
        
    # go over the distros we need to check
    pkg_support_time = {}
    for (name, lts_supported) in DISTRO_NAMES_AND_LTS_SUPPORT:

        # get basic structure file
        structure = get_structure(name, distro)
    
        # get dicts of pkgname -> support timeframe string
        support_timeframe = SUPPORT_TIMEFRAME
        if lts_supported and distro in LTS_RELEASES:
            support_timeframe =  SUPPORT_TIMEFRAME_LTS
        else:
            support_timeframe = SUPPORT_TIMEFRAME
        get_packages_support_time(structure, name, pkg_support_time, support_timeframe)

    # now check the hints file that is used to overwrite 
    # the default seeds
    try:
        for line in urllib2.urlopen(hints_file):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                (raw_pkgname, support_time) = line.split()
                for pkgname in expand_src_pkgname(raw_pkgname):
                    if support_time == 'unsupported':
                        try:
                            del pkg_support_time[pkgname]
                            sys.stderr.write("hints-file: marking %s unsupported\n" % pkgname)
                        except KeyError:
                            pass
                    else:
                        if pkg_support_time.get(pkgname) != support_time:
                            sys.stderr.write(
                                "hints-file: changing %s from %s to %s\n" % (
                                    pkgname,  pkg_support_time.get(pkgname), 
                                    support_time))
                            pkg_support_time[pkgname] = support_time
            except:
                logging.exception("can not parse line '%s'" % line)
    except urllib2.HTTPError, e:
        if e.getcode() != 404:
            raise
        sys.stderr.write("hints-file: %s gave 404 error\n" % hints_file)
    
    # output suitable for the extra-override file
    for pkgname in sorted(pkg_support_time.keys()):
        # special case, the hints file may contain overrides that
        # are arch-specific (like zsh-doc/armel)
        if "/" in pkgname:
            print "%s %s %s" % (
                pkgname, SUPPORT_TAG, pkg_support_time[pkgname])
        else:
            # go over the supported arches, they are divided in 
            # first-class (PRIMARY) and second-class with different
            # support levels
            for arch in SUPPORTED_ARCHES:
                # ensure we do not overwrite arch-specific overwrites
                pkgname_and_arch = "%s/%s" % (pkgname, arch)
                if pkgname_and_arch in pkg_support_time:
                    break
                if arch in PRIMARY_ARCHES:
                    # arch with full LTS support
                    print "%s %s %s" % (
                        pkgname_and_arch, SUPPORT_TAG, pkg_support_time[pkgname])
                else:
                    # not a LTS supported architecture, gets only regular
                    # support_timeframe
                    print "%s %s %s" % (
                        pkgname_and_arch, SUPPORT_TAG, SUPPORT_TIMEFRAME[0][0])
                
