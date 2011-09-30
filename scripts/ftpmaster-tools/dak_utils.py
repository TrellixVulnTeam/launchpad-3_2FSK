#!/usr/bin/python

# Utility functions from the dak suite
# Copyright (C) 2000, 2001, 2002, 2003, 2004, 2005, 2006  James Troup <james@nocrew.org>

################################################################################

# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.

# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 59 Temple Place, Suite 330, Boston, MA  02111-1307  USA

################################################################################

import os
import re
import sys
import tempfile

################################################################################

re_no_epoch = re.compile(r"^\d+\:")

################################################################################

def fubar(msg, exit_code=1):
    sys.stderr.write("E: %s\n" % (msg))
    sys.exit(exit_code)

def warn(msg):
    sys.stderr.write("W: %s\n" % (msg))

################################################################################

def prefix_multi_line_string(str, prefix, include_blank_lines=0):
    out = ""
    for line in str.split('\n'):
        line = line.strip()
        if line or include_blank_lines:
            out += "%s%s\n" % (prefix, line)
    # Strip trailing new line
    if out:
        out = out[:-1]
    return out

################################################################################

def temp_filename(directory=None, dotprefix=None, perms=0700):
    """Return a secure and unique filename by pre-creating it.
If 'directory' is non-null, it will be the directory the file is pre-created in.
If 'dotprefix' is non-null, the filename will be prefixed with a '.'."""

    if directory:
        old_tempdir = tempfile.tempdir;
        tempfile.tempdir = directory;

    filename = tempfile.mktemp();

    if dotprefix:
        filename = "%s/.%s" % (os.path.dirname(filename), os.path.basename(filename));
    fd = os.open(filename, os.O_RDWR|os.O_CREAT|os.O_EXCL, perms);
    os.close(fd);

    if directory:
        tempfile.tempdir = old_tempdir;

    return filename;
