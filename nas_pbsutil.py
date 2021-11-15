'''
Miscellaneous routines to interact with PBS
'''

import re
import pbs_ifl as ifl
import os
import socket
import stat
import sys

import nas_xstat_config as conf
import pbs_ifl as ifl
from collections import OrderedDict

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
            except OSError:
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
    mo = re.search(r'fake_%s_%s=([^\s]+)' % (stat, host), conf.gdebug)
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
    user = os.getuid()
    if user == 1000:
        user = 501  # XXX for debugging on MacOS
    # Load system userexit, if present.
    pbs_exec = pbs_conf.pbs_exec_path
    t = os.environ.get('NAS_QSTAT_EXEC')
    if t:
        pbs_exec = t
    if pbs_exec:
        path = os.path.join(pbs_exec, 'lib', 'site', '%s_userexits' % prefix)
        try:
            sbuf = os.stat(path)
            # Be careful about what we load
            if sbuf:
                if sbuf.st_uid == 0 or sbuf.st_uid == user:
                    mode = stat.S_ISDIR(sbuf.st_mode)
                    if (mode & (stat.S_IWGRP | stat.S_IWOTH)) == 0:
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
        mo = re.search(r'userexits=([^\s]+)', conf.gdebug)
        if mo:
            path = mo.group(1)
        try:
            sbuf = os.stat(path)
            if sbuf:
                if sbuf.st_uid == 0 or sbuf.st_uid == user:
                    mode = stat.S_ISDIR(sbuf.st_mode)
                    if (mode & (stat.S_IWGRP | stat.S_IWOTH)) == 0:
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

# Utility functions copied from PTL's BatchUtils class

def list_to_attrl(l):
    """
    Convert a list to a PBS attribute list

    :param l: List to be converted
    :type l: List
    :returns: PBS attribute list
    """
    return list_to_attropl(l, None)

def list_to_attropl(l, op=ifl.SET):
    """
    Convert a list to a PBS attribute operation list

    :param l: List to be converted
    :type l: List
    :returns: PBS attribute operation list
    """
    head = None
    prev = None

    for i in l:
        a = str_to_attropl(i, op)
        if prev is None:
            head = a
        else:
            prev.next = a
        prev = a
        if op is not None:
            a.op = op
    return head

def str_to_attrl(s):
    """
    Convert a string to a PBS attribute list

    :param s: String to be converted
    :type s: str
    :returns: PBS attribute list
    """
    return str_to_attropl(s, None)

def str_to_attropl(s, op=ifl.SET):
    """
    Convert a string to a PBS attribute operation list

    :param s: String to be converted
    :type s: str
    :returns: PBS attribute operation list
    """
    if op is not None:
        a = ifl.attropl()
    else:
        a = ifl.attrl()
    if '.' in s:
        (attribute, resource) = s.split('.')
        a.name = attribute
        a.resource = resource.strip()
    else:
        a.name = s
    a.value = ''
    a.next = None
    if op:
        a.op = op
    return a

def dict_to_attrl(d={}):
    """
    Convert a dictionary to a PBS attribute list

    :param d: Dictionary to be converted
    :type d: Dictionary
    :returns: PBS attribute list
    """
    return dict_to_attropl(d, None)

def dict_to_attropl(d={}, op=ifl.SET):
    """
    Convert a dictionary to a PBS attribute operation list

    :param d: Dictionary to be converted
    :type d: Dictionary
    :returns: PBS attribute operation list
    """
    if len(d.keys()) == 0:
        return None

    prev = None
    head = None

    for k, v in d.items():
        if isinstance(v, tuple):
            op = v[0]
            v = v[1]
        if op is not None:
            a = ifl.attropl()
        else:
            a = ifl.attrl()
        if '.' in k:
            (attribute, resource) = k.split('.')
            a.name = attribute
            a.resource = resource
        else:
            a.name = k
        a.value = str(v)
        if op is not None:
            a.op = op
        a.next = None

        if prev is None:
            head = a
        else:
            prev.next = a
        prev = a
    return head

def convert_to_attrl(attrib):
    """
    Generic call to convert Python type to PBS attribute list

    :param attrib: Attributes to be converted
    :type attrib: List or tuple or dictionary or str
    :returns: PBS attribute list
    """
    return convert_to_attropl(attrib, None)

def convert_to_attropl(attrib, cmd=ifl.MGR_CMD_SET, op=None):
    """
    Generic call to convert Python type to PBS attribute
    operation list

    :param attrib: Attributes to be converted
    :type attrib: List or tuple or dictionary or str
    :returns: PBS attribute operation list
    """
    if op is None:
        op = command_to_op(cmd)

    if isinstance(attrib, (list, tuple)):
        a = list_to_attropl(attrib, op)
    elif isinstance(attrib, (dict, OrderedDict)):
        a = dict_to_attropl(attrib, op)
    elif isinstance(attrib, str):
        a = str_to_attropl(attrib, op)
    else:
        a = None
    return a

def command_to_op(cmd=None):
    """
    Map command to a ``SET`` or ``UNSET`` Operation. An unrecognized
    command will return SET. No command will return None.

    :param cmd: Command to be mapped
    :type cmd: str
    :returns: ``SET`` or ``UNSET`` operation for the command
    """

    if cmd is None:
        return None
    if cmd in (ifl.MGR_CMD_SET, ifl.MGR_CMD_EXPORT, ifl.MGR_CMD_IMPORT):
        return ifl.SET
    if cmd == ifl.MGR_CMD_UNSET:
        return ifl.UNSET
    return ifl.SET


# vi:ts=4:sw=4:expandtab
