from __future__ import print_function

import re
import pbs_ifl as ifl
import os
import socket
import sys

import nas_xstat_config as conf

pbs_conf = ifl.cvar.pbs_conf


def get_server(job_id):
    '''Split job ID into its pieces

    Also works for reservations.
    Args:
        job_id = job id in one of its various forms
    Returns:
        (job_id, server) tuple
        job_id will be None on error
    Based on C routine by the same name.
    '''
    job_id = job_id.strip()
    if job_id.startswith('@'):
        return (None, job_id[1:])
    server_out = None
    pbs_server_name = pbs_conf.pbs_server_name
    t = parse_jobid(job_id)
    if t is None:
        return (None, None)
    (seq_num, parent_server, current_server, _, _) = t
    if seq_num is None:
        return (None, None)
    if parent_server and not pbs_server_name:
        pbs_server_name = parent_server
        server_out = parent_server
    if current_server:
        server_out = current_server
    job_id_out = seq_num
    if parent_server:
        if pbs_server_name:
            s = parent_server.lower()
            t = pbs_server_name.lower()
            if s == t:
                job_id_out = job_id_out + '.' + pbs_server_name
                return (job_id_out, server_out)
            try:
                (hname, alias, ipaddr) = socket.gethostbyname_ex(parent_server)
                parent_server = hname
            except socket.herror:
                pass
            job_id_out = job_id_out + '.' + parent_server
            if not server_out:
                server_out = parent_server
            return (job_id_out, server_out)
    if not pbs_server_name:
        return (None, None)
    job_id_out = job_id_out + '.' + pbs_server_name
    return (job_id_out, server_out)


patt = \
        r'((?P<seq>[0-9]+)(?P<idx>\[[0-9]*\])?)?' \
        r'(\.(?P<parent>[^\s@]+))?' \
        r'(@(?P<current>[^\s@]+))?' \
        r'$'
comp = re.compile(patt)


def parse_jobid(job_id):
    '''Split job ID into its pieces

    Also works for reservations.
    Args:
        job_id = job id in one of its various forms
    Returns:
        None if invalid form, else
        (seq_num, parent_server, current_server, array_idx, resv_type) tuple
    Based on C routine by the same name in qstat.c
    '''
    if job_id is None:
        return None
    job_id = job_id.strip()
    seq_num = None
    parent = None
    current = None
    array_idx = None
    resv_type = None
    # Deal with reservation type prefix
    if job_id[0] in 'RSM':
        resv_type = job_id[0]
        job_id = job_id[1:]
    mo = comp.match(job_id)
    if not mo:
        return None
    seq_num = mo.group('seq')
    if resv_type:
        seq_num = resv_type + seq_num
    parent = mo.group('parent')
    current = mo.group('current')
    array_idx = mo.group('idx')
    # Cannot have array index on reservation
    if resv_type is not None and array_idx is not None:
        return None

    return (seq_num, parent, current, array_idx, resv_type)

def file_to_stat(host, stat, attrs=[]):
    '''Load faked PBS statXXX results from file

    That is, check if one of the --debug arguments specified a file
    to use in place of an actual pbs_statxyz call. Load the file
    if so.

    E.g., You might take the output from pbsnodes -av and convert it
    to look like the result from a pbs_statvnodes() call.

    Args:
        host = Hostname of faked data of interest
        stat = Which kind of info is being queried (e.g., jobs)
        attrs = List of interesting attribute names. Can also
            be the attropl that would be passed to the pbs_xyz call.
    Returns:
        None if there isn't any appropriate fake file specified.
        Else a dictionary with the attributes and values.
    '''
    mo = re.search('fake_%s_%s=([^\s]+)' % (stat, host), conf.gdebug)
    if not mo:
        return None
    fname = mo.group(1)
    # Convert attropl to simple list if necessary
    lst = None
    if isinstance(attrs, ifl.attropl) or isinstance(attrs, ifl.attrl):
        lst = []
        cur = attrs
        while cur:
            key = cur.name
            if cur.resource:
                key = key + '.' + cur.resource
            lst.append(key)
            cur = cur.next
    with open(fname) as fd:
        lines = fd.read()
        bs = lines_to_stat(lines, attrs if lst is None else lst)
    return bs

def lines_to_stat(lines, attrs=[]):
    '''Convert file contents to PBS statXXX result

    Args:
        lines = Contents of file
        attrs = Names of interesting attributes
    Returns:
        List of dicts with attribute/value pairs
    '''
    item_list = []
    item = None
    line_cnt = 0
    attrset = set(attrs)
    for line in lines.split('\n'):
        line_cnt += 1
        if line == '':
            if item:
                item_list.append(item)
            item = None
            continue
        if '=' not in line:
            if item:    # Should not happen
                item_list.append(item)
            # New item
            item = dict()
            # First line of an item has the item ID, possibly
            # preceded by, e.g., 'Job: ' or 'Resv ID: '.
            item['id'] = line.split(':')[-1].strip()
            continue
        flds = line.split('=', 1)
        if len(flds) != 2:
            print("Garbage input at line %d: %s" % (line_cnt, line),
                  file=sys.stderr)
            continue
        key = flds[0].strip()
        if (attrset and key.split('.')[0] not in attrset):
            continue
        value = flds[1].strip()
        # Hack to recognize epoch + timestamp and convert to just epoch
        # E.g., 1624104854 (Sat Jun 19 05:14:14 PDT 2021)
        mo = re.match(r'(\d{9,15}) \(', value)
        if mo:
            value = mo.group(1)
        item[key] = value
    if item:
        item_list.append(item)
    return item_list


def load_userexits(prefix):
    '''Load text of userexit overrides

    Args:
        prefix = prefix for userexit file name
    Returns:
        Catenation of all userexit file contents
    '''
    code = ''
    # Load system userexit, if present.
    pbs_exec = pbs_conf.pbs_exec_path
    t = os.environ.get('NAS_QSTAT_EXEC')
    if t:
        pbs_exec = t
    if pbs_exec:
        path = os.path.join(pbs_exec, 'lib', 'site', '%s_userexits' % prefix)
        try:
            if os.stat(path):
                with open(path) as f:
                    code += f.read()
        except OSError:
            pass
    # Append any user's userexit code
    home = os.environ.get('HOME')
    if not home:
        home = os.path.expanduser('~')
    if home is not None:
        path = os.path.join(home, '.%s_userexits' % prefix)
        try:
            if os.stat(path):
                with open(path) as f:
                    code += f.read()
        except OSError:
            pass
    return code

# Dummy userexit routines that can be overridden by user/system


def userexit_post_opts(gbl, lcl):
    pass


def userexit_add_fields(gbl, lcl):
    pass


def userexit_add_fields_a(gbl, lcl):
    pass


def userexit_interest(gbl, lcl):
    pass


def userexit_last_chance_a(gbl, lcl):
    pass


def userexit_set_server(gbl, lcl):
    pass


def userexit_post_statresv(gbl, lcl):
    pass


def stack_userexit(old, ext):
    '''Extend a userexit routine

    That is, given a userexit routine foo and a new userexit routine bar,
    create a routine to replace foo that calls the old foo and then bar.
    E.g.:
        def my_post_opts(gbl, lcl):
            pass
        userexit_post_opts = stack_userexit(userexit_post_opts, my_post_opts)

    Args:
        old = existing userexit to stack on
        ext = new userexit routine to extend the userexit.
    Returns:
        Extended routine
    '''
    def wrapper(gbl, lcl, orig=old, newer=ext):
        orig(gbl, lcl)
        newer(gbl, lcl)
    return wrapper


# List of known userexits, used as prefix to site/user supplied code.
userexits_header = 'global %s\n' % ','.join(
    [
        'userexit_post_opts',
        'userexit_add_fields',
        'userexit_add_fields_a',
        'userexit_interest',
        'userexit_last_chance_a',
        'userexit_set_server',
        'userexit_post_statresv'
    ]
    )

# vi:ts=4:sw=4:expandtab
