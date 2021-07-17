from __future__ import print_function

import re
import pbs_ifl as ifl
import os
import socket
import sys

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
    (seq_num, parent_server, current_server, _, _) = parse_jobid(job_id)
    if seq_num == None:
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
            except:
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
    if job_id == None:
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
    parent = mo.group('parent')
    current = mo.group('current')
    array_idx = mo.group('idx')
    # Cannot have array index on reservation
    if resv_type != None and array_idx != None:
        return None

    return (seq_num, parent, current, array_idx, resv_type)

def file_to_stat(lines):
    '''Convert file contents to PBS statXXX result

    E.g., You might take the output from pbsnodes -av and convert it
    to look like the result from a pbs_statvnodes() call.

    Args:
        lines = Contents of file
    Returns:
        List of dicts with attribute/value pairs
    '''
    item_list = []
    item = None
    line_cnt = 0
    for line in lines.split('\n'):
        line_cnt += 1
        if line == '':
            if item:
                item_list.append(item)
            item = None
            continue
        if not '=' in line:
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
        # Hack to recognize epoch + timestamp and convert to just epoch
        # E.g., 1624104854 (Sat Jun 19 05:14:14 PDT 2021)
        value = flds[1].strip()
        mo = re.match(r'(\d{9,15}) \(', value)
        if mo:
            value = mo.group(1)
        item[flds[0].strip()] = value
    if item:
        item_list.append(item)
    return item_list

def load_sysexits(prefix):
    '''Load text of sysexit overrides

    Args:
        prefix = prefix for sysexit file name
    Returns:
        Catenation of all sysexit file contents
    '''
    code = ''
    # Load system sysexit, if present.
    pbs_exec = pbs_conf.pbs_exec_path
    t = os.environ.get('NAS_QSTAT_EXEC')
    if t:
        pbs_exec = t
    if pbs_exec:
        path = os.path.join(pbs_exec, 'lib', 'site', '%s_sysexits' % prefix)
        try:
            if os.stat(path):
                with open(path) as f:
                    code += f.read()
        except OSError:
            pass
    # Append any user's sysexit code
    home = os.environ.get('HOME')
    if not home:
        home = os.path.expanduser('~')
    if home != None:
        path = os.path.join(home, '.%s_sysexits' % prefix)
        try:
            if os.stat(path):
                with open(path) as f:
                    code += f.read()
        except OSError:
            pass
    return code

# Dummy sysexit routines that can be overridden by user/system

def sysexit_post_opts(g, l):
    pass

def sysexit_add_fields(g, l):
    pass

def sysexit_add_fields_a(g, l):
    pass

def sysexit_interest(g, l):
    pass

def sysexit_last_chance_a(g, l):
    pass

def sysexit_set_server(g, l):
    pass

def sysexit_post_statresv(g, l):
    pass

def stack_sysexit(old, ext):
    '''Extend a sysexit routine

    That is, given a sysexit routine foo and a new sysexit routine bar,
    create a routine to replace foo that calls the old foo and then bar.
    E.g.:
        def my_post_opts(g, l):
            pass
        sysexit_post_opts = stack_sysexit(sysexit_post_opts, my_post_opts)

    Args:
        old = existing sysexit to stack on
        ext = new sysexit routine to extend the sysexit.
    Returns:
        Extended routine
    '''
    def wrapper(g, l, orig=old, newer=ext):
        orig(g, l)
        newer(g, l)
    return wrapper

# List of known sysexits, used as prefix to site/user supplied code.
sysexits_header = 'global sysexit_post_opts,sysexit_add_fields,sysexit_add_fields_a,sysexit_interest,sysexit_last_chance_a,sysexit_set_server,sysexit_post_statresv\n'

# vi:ts=4:sw=4:expandtab
