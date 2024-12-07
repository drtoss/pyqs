#!/usr/bin/python3

import sys
import os
import grp
import math
import pwd
import re
import stat
import struct
import time
from sys import stdin, stdout, stderr


gdebug = ''
version = "0.2"
share_name_map = dict()
share_id_map = dict()
map_cache = dict()

# XXX The following should be loaded from running system
# See set_fs_info() for how to change at runtime
fs_decay_time = 24 * 3600.0
fs_decay_factor = 0.5
unknown_alloc = 10
sched_priv = '/var/spool/pbs/sched_priv'
groups_file = os.path.join(sched_priv, 'resource_group')
usage_file = os.path.join(sched_priv, 'usage')
shost = 'localhost'

gnow = time.time()
asof_time = gnow
trust_job_info = False                 # True if running for a manager

# Constants
FAIRSHARE_ROOT_NAME = 'TREEROOT'
UNKNOWN_GROUP_NAME = 'unknown'
UNSPECIFIED = None
MAGIC_NAME = 'PBS_MAG!'


class Share:
    def __init__(self, name, par_id, grp_id):
        self.name = name
        self.par_id = par_id        # resgroup
        self.grp_id = grp_id        # cresgroup
        self.alloc = UNSPECIFIED    # shares
        self.tree_pct = 0.0         # tree_percentage
        self.grp_pct = 0.0          # shares/group_shares
        self.usage = 0.0            # usage in fairshare_rec units
        self.usage_factor = 0.0     # actual usage vs allocation (range 0 - 1)
        #                             also called fairshare_tree_usage
        self.grp_path = list()      # path from root to node
        self.parent = None          # link up the tree
        self.sibling = None         # chain of nodes with same parent as us
        self.child = None           # link to head of our sibling chain
        self.fs_factor = 0.0
        self.depth = 0              # indent to print in tree form


def set_fs_info(hn, **kwds):
    '''Set global values for other routines

    Args:
        hn = hostname
        df = fs_decay_factor (float)
        dt = fs_decay_time (seconds)
        gf = groups_file (resource_groups) path
        rs = reset global maps
        ua = unknown_alloc (float)
        uf = usage_file path
    '''
    global shost, fs_decay_factor, fs_decay_time, groups_file, unknown_alloc
    global usage_file, trust_job_info, gnow, asof_time
    if hn:
        shost = hn.split('.')[0]
    for (key, value) in kwds.items():
        if key == 'df':
            fs_decay_factor = value
        if key == 'dt':
            fs_decay_time = value
        if key == 'gf':
            groups_file = value
        if key == 'tj':
            trust_job_info = value
        if key == 'ua':
            unknown_alloc = value
        if key == 'uf':
            usage_file = value
        if key == 'rs':
            share_name_map.clear()
            share_id_map.clear()
            map_cache.clear()
            trust_job_info = False
            gnow = time.time()
            asof_time = gnow
    do_debugging()
    return


def do_debugging():
    '''Help debugging the program

    Examine an environment variable for overrides to selected paths.
    '''
    global gdebug
    debugstr = os.getenv('NAS_FSUTIL_DEBUG')
    if not debugstr:
        debugstr = ''
    debugstr = gdebug + ' ' + debugstr
    # Path overrides:
    for s in re.split(r'[\s,]+', debugstr):
        mo = re.match(r'(\w+)=(.+)', s)
        if not mo:
            continue
        (name, path) = mo.group(1, 2)
        if '/' not in path:
            continue
        globals()[name] = path
    return


def calc_fs_factor(tree):
    '''Calculate fairshare_factor

    This is the number to use to learn which entities should be favored
    most when scheduling. Lower is better.

    Args:
        tree = root of fs tree
    '''
    for share in share_id_map.values():
        if share.tree_pct == 0.0:
            share.fs_factor = 0.0
        else:
            share.fs_factor = pow(2, -(share.usage_factor / share.tree_pct))


def calc_fs_tree_usage(tree):
    '''Calculate usage factor for tree

    Each node's usage_factor is calculated. Called fairshare_tree_usage
    in Admin Guide.  The factor takes each node's usage and part of its
    parent's usage into account

    Args:
        tree = base of tree to work on
    '''
    if not tree:
        return
    share = tree.child
    while share:
        usage = 1.0 if tree.usage == 0.0 else tree.usage
        share.usage_factor = share.usage / usage
        calc_fs_tree_usage_helper(tree, share.child)
        share = share.sibling


def calc_fs_tree_usage_helper(root, child):
    '''Helper routine to recurse through tree at root

    Args:
        root = base of tree to work on
        child = a node in the tree to start with
    '''
    if not root or not child:
        return
    parent = child.parent
    if not parent:
        return
    if root.usage == 0.0:
        portion = 0.0
    else:
        portion = child.usage / root.usage
    child.usage_factor = portion + \
        (parent.usage_factor - portion) * child.grp_pct
    calc_fs_tree_usage_helper(root, child.sibling)
    calc_fs_tree_usage_helper(root, child.child)


def calc_fs_percent(root, alloc):
    '''Calc group share percent of total

    Args:
        root = base of subtree
        alloc = allocation for the group
            UNSPECIFIED implies calculate it
    '''

    if not root or not root.parent:
        return
    cur_alloc = alloc if alloc != UNSPECIFIED else count_alloc(root)
    parent = root.parent
    # Detect no alloc
    if cur_alloc * parent.tree_pct == 0:
        root.grp_pct = 0.0
        root.tree_pct = 0.0
    else:
        root.grp_pct = float(root.alloc) / cur_alloc
        root.tree_pct = root.grp_pct * parent.tree_pct
    calc_fs_percent(root.sibling, cur_alloc)
    calc_fs_percent(root.child, UNSPECIFIED)


def count_alloc(share):
    '''Count allocations in a group

    The group includes the share and all of its sibs

    Args:
        share = the start of a sib list
    Returns:
        sum of the allocations for the sib list
    '''
    tot_alloc = 0
    while share:
        if share.alloc:
            tot_alloc += share.alloc
        share = share.sibling
    return tot_alloc


def depth_first(tree, depth):
    '''Visit tree in depth first order

    Args:
        tree to visit
            nodes will have their depth value updated
    Returns
        Tree nodes in depth_first order.
    '''
    if not tree:
        return []
    tree.depth = depth
    clist = depth_first(tree.child, depth+1)
    slist = depth_first(tree.sibling, depth)
    t = [tree]
    t += clist
    t += slist
    return t


def insert_child(parent, child):
    '''Add a child to a share's child chain

    In alphabetical order

    Args:
        parent = share to add child to
        child = child to add
    '''
    name = child.name
    cur_child = parent.child
    # Deal with first child
    if not cur_child:
        child.sibling = None
        parent.child = child
        return
    # If new child fits in at beginning
    if name < cur_child.name:
        child.sibling = cur_child
        parent.child = child
        return
    # Scan sib chain to find where to insert
    while cur_child:
        if name > cur_child.name:
            prev = cur_child
            cur_child = cur_child.sibling
            continue
        break
    child.sibling = cur_child
    prev.sibling = child
    return


def load_usage(root):
    '''Read group usage data from file

    Args:
        root = root of shares tree
    Globals
        usage_file = path to group usage data
        asof_time = set to timestamp from usage_file
    '''
    global asof_time
    with open(usage_file, 'rb') as fd:
        buf = fd.read()
    hdr_fmt = '9sdl'
    sz = struct.calcsize(hdr_fmt)
    header = struct.unpack(hdr_fmt, buf[0:sz])
    # The stuff with partition is because the string fields are zero filled
    # and we need to truncate at the first zero.
    magic = str(header[0].partition(b'\0')[0], encoding='utf-8')
    if magic != MAGIC_NAME or header[1] != 2.0:
        print(f"Bad usage file header: {usage_file}", file=stderr)
        sys.exit(1)
    asof_time = header[2]
    use_fmt = '50sd'
    for entry in struct.iter_unpack(use_fmt, buf[sz:]):
        name = str(entry[0].partition(b'\0')[0], encoding='utf-8')
        if name not in share_name_map:
            name = UNKNOWN_GROUP_NAME
        share_name_map[name].usage = entry[1]
    return


def load_usage_from_jobs(fname, tree, patts, weights):
    global asof_time
    from nas_pbsutil import lines_to_stat
    if fname == '-':
        fs = stdin
    else:
        fs = open(fname)
        stat_buf = os.stat(fname)
        asof_time = stat_buf.st_mtime
    lines = fs.read()
    if fname != '-':
        fs.close()
    interesting = ['egroup', 'euser', 'resources_used', 'schedselect',
                   'Account_Name', 'job_state', 'obittime', 'stime']
    jobs = lines_to_stat(lines, interesting)
    del lines
    for job in jobs:
        jobname = job['id']
        entity = set_account_name(job, patts)
        if entity not in share_name_map:
            print(f'Unknown entity for job {jobname}', file=stderr)
            entity = UNKNOWN_GROUP_NAME
        sbu_rate = set_sbu_rate_nh(job, weights)
        if isinstance(sbu_rate, str):
            print(f'Cannot compute SBU rate for job {jobname} {sbu_rate}',
                  file=stderr)
            continue
        effective_wt = calc_aged_walltime(job)
        eff_sbus = sbu_rate * effective_wt
        share = share_name_map[entity]
        share.usage += eff_sbus
    return True


def calc_aged_walltime(job):
    '''Calculate walltime after decay

    Args:
        info = info for job
    Returns:
        aged walltime

    The basic formula for the walltime multiplier is:

        mult = (1 - r^(n)) / (1 - r)

        where r is the decay rate (fairshare_decay_factor) and n
        is the number of fairshare_decay_time intervals that have
        elapsed during walltime.
        This gets further shrunk by the number of intervals that
        have elapsed between when the walltime was sampled and now.
    '''
    global asof_time
    global fs_decay_time, fs_decay_factor
    state = job.get('job_state')
    # Skip jobs still in queue
    if state in 'HQTW':
        return 0.0
    walltime = job.get('resources_used.walltime')
    if walltime is None:
        return 0.0
    walltime = clocktosecs(walltime)
    asof = asof_time
    # Jobs no longer running:
    if state in 'FMX':
        asof = job.get('obittime')
        if asof is None:
            # Guess at job end time
            stime = job.get('stime')
            if stime is None:
                return 0.0
            stime = clocktosecs(stime)
            asof = stime + walltime
        else:
            asof = clocktosecs(asof)
    (f, n) = math.modf(walltime / fs_decay_time)
    fact = (1.0 - math.pow(fs_decay_factor, n)) / (1.0 - fs_decay_factor)
    # Fact is factor as of last walltime update. Do further decaying if
    # that was in the past
    result = fs_decay_time * (f + fact)
    if asof < gnow:
        fact2 = math.pow(fs_decay_factor, (gnow - asof) / fs_decay_time)
        result *= fact2
    return result


def set_account_name(job, patts, requestor=None):
    '''Set job's Account_Name

    We're assuming the Account_Name will be used by fairshare as the
    entity to associate with job usage (fairshare_entity).

    If the event requestor is a manager, we use whatever entity they
    specified.

    Args:
        job = job info
        patts = patterns mapping group:user to entity
        requestor = user requesting action (for qsub)
    Returns:
        selected entity, also put in job's Account_Name attribute
        None if lookup failed
    '''
    entity = job.get('Account_Name')
    if entity and trust_job_info:
        return entity
    euser = job.get('euser')
    if euser is None:
        if requestor is None:
            return None
        euser = requestor.split('@')[0]
    egroup = job.get('egroup')
    if egroup is None:
        gl = job.get('group_list')
        if gl:
            egroup = str(gl).split(',')[0].split('@')[0]
    if egroup is None:
        try:
            pwinfo = pwd.getpwnam(euser)
            grinfo = grp.getgrgid(pwinfo[3])
            egroup = grinfo[0]
        except KeyError:
            return None
    entity = get_share_name(egroup, euser, patts)
    if entity:
        job['Account_Name'] = entity
    return entity


def get_share_name(egroup, euser, patts):
    global map_cache
    # Check if mapping is in cache
    key = egroup + ':' + euser
    entity = map_cache.get(key)
    if entity:
        return entity
    # Scan list of patterns for first match
    for (rcomp, entity) in patts:
        if not rcomp.match(key):
            continue
        map_cache[key] = entity
        return entity
    return None


def set_sbu_rate_nh(job, weights):
    '''Get and set job SBU rate when not in hook context

    Args:
        job = info for job
        weights = dict mapping model to (cpus, sbus) tuple
    Returns:
        computed sbu rate
    '''
    rate = job.get('Resource_List.sbu_rate')
    if rate and trust_job_info:
        return float(rate)
    select = job.get('schedselect')
    if not select:
        select = job.get('Resource_List.select')
    if not select:
        return 0.0
    if 'model' not in select:
        select += ':model=bro'
    rate = calc_sbus(select, weights)
    if isinstance(rate, str):
        return rate
    job['Resource_List.sbu_rate'] = rate
    return rate


def set_sbu_rate_hook(job, weights):
    '''Set job SBU rate when running in hook context

    Args:
        job = info for job
        weights = dict mapping model to (cpus, sbus) tuple
    Returns:
        computed sbu rate
    '''
    hjob = job.job
    R = hjob.Resource_List
    try:
        rate = R['sbu_rate']
    except Exception:
        rate = None
    if rate and trust_job_info:
        return rate
    select = job['schedselect']
    if not select:
        select = R['select']
    if not select:
        return 0.0
    select = str(select)
    if 'model' not in select:
        return 'Model must be specified in select attribute'
    rate = calc_sbus(select, weights)
    if isinstance(rate, str):
        return rate
    R['sbu_rate'] = rate
    return rate


def calc_sbus(select, weights):
    '''Calculate SBU rate from select statement

    Args:
        select = select statement from job
        weights = dict mapping model to (cpus, sbus) tuple
    Returns:
        computed sbu rate as float
        string message on error
    '''
    rate = 0.0
    # Compute rate for each chunk in select
    # Format is count:...model=xyz...
    for chunk in select.split('+'):
        idx = chunk.index(':')
        if idx < 0:
            return f'Unexpected select attribute {select}'
        count = chunk[:idx]
        try:
            count = int(count)
        except Exception:
            return f'Bad count in select {count}'
        mo = re.search(r'\bmodel=(\w+)\b', chunk)
        if not mo:
            return f'Model type missing from select chunk {chunk}'
        model = mo.group(1)
        weight = weights.get(model)
        if weight is None:
            return f'Unknown model type {model}'
        # TODO We should deal with shared nodes here, but not yet
        rate += count * weight[1]
    return rate


def new_group(name, par_id, grp_id):
    '''Create a new share object

    Initialized to default values

    Args:
        name = name of the share
        par_id = resource group this child belongs to
        grp_id = resource group of any children

    Returns:
        Partially filled-out share object
        Object added to share_maps
    '''
    share = Share(name, par_id, grp_id)
    share_name_map[name] = share
    share_id_map[grp_id] = share
    return share


def reconcile_tree(root):
    '''Fill in a bare share tree

    Args:
        root = root of the tree
    Returns:
        True if no problems found
        False if errors reported.
    '''
    # First, build parent, child, and sibling links
    for (name, share) in share_name_map.items():
        par_id = share.par_id
        if par_id < 0:
            continue
        parent = share_id_map[par_id]
        share.parent = parent
        share.par_id = parent.grp_id
        insert_child(parent, share)
    # Now, build the paths from the share to the root
    for share in share_id_map.values():
        share.grp_path = create_group_path(share)
    # Fill in special shares: root and unknown
    root = share_name_map[FAIRSHARE_ROOT_NAME]
    root.tree_pct = 1.0
    root.alloc = 0
    tot_alloc = sum([share.alloc for share in share_id_map.values()])
    root.alloc = tot_alloc
    unk = share_name_map[UNKNOWN_GROUP_NAME]
    unk.alloc = unknown_alloc
    calc_fs_percent(root.child, UNSPECIFIED)
    return True


def reconcile_usage(root):
    # Add current use values for leaf nodes into their ancesters
    for share in share_id_map.values():
        if share.child:
            continue    # Not leaf
        usage = share.usage
        for name in share.grp_path:
            node = share_name_map[name]
            if node is not share:
                node.usage += usage
    calc_fs_tree_usage(root)
    calc_fs_factor(root)
    return True


def create_group_path(share):
    path = list()
    while share:
        path.insert(0, share.name)
        share = share.parent
    return path


def load_fs_info(fname):
    '''Read and parse fairshare info file

    Args:
        fname = path to file to load from
    Returns:
        Tuple (tree, pattern, weights) where
            tree is tree of entity Shares
            patterns is list of tuples (pattern, share) where:
                pattern is a compiled pattern
                share is the Share for the matching entity
            weights is dict with key model_name value (cpus, sbus)
        err string on error
    '''
    try:
        with open(fname) as fs:
            buf = fs.read()
    except OSError:
        return f'Cannot read {fname}'
    (nlines, plines, wlines) = split_share_info(fname, buf)
    # We need the share tree to validate the patterns, so process it first
    tree = build_tree(fname, nlines)
    if isinstance(tree, str):
        return tree
    patt_list = build_patterns(fname, plines, share_name_map)
    if isinstance(patt_list, str):
        return patt_list
    weight_dict = build_weights(fname, wlines)
    if isinstance(weight_dict, str):
        return weight_dict
    return (tree, patt_list, weight_dict)


def build_tree(fname, lines):
    '''Build tree(fname, lines)

    Build tree of Shares from lines
    Lines have the form
        (entity_name grp_id parent_name allocation)
    '''
    root = new_group(FAIRSHARE_ROOT_NAME, -1, 0)
    share_name_map['root'] = root
    for (lineno, flds) in lines:
        loc = f'at {fname}:{lineno}'
        if len(flds) != 4:
            return f'Wrong format {loc}'
        (name, grp_id, parent, alloc) = flds
        if not name.isidentifier():
            return f'Bad group name {name} {loc}'
        try:
            grp_id = int(grp_id)
        except Exception:
            return f'Non_integer grp_id {grp_id} {loc}'
        if not parent.isidentifier():
            return f'Bad parent name {parent} {loc}'
        try:
            alloc = int(alloc)
        except Exception:
            return f'Non-integer allocation {alloc} {loc}'
        # Semantic checks
        if name in share_name_map:
            return f'Duplicate share name {name} {loc}'
        if grp_id in share_id_map:
            return f'Group id already in use: {grp_id} {loc}'
        if parent not in share_name_map:
            return f'Unknown parent share {parent} {loc}'
        par_id = share_name_map[parent].grp_id
        share = new_group(name, par_id, grp_id)
        share.alloc = alloc
    # Add the unknown group at end
    unknown = new_group(UNKNOWN_GROUP_NAME, 0, 1)
    unknown.alloc = unknown_alloc
    result = reconcile_tree(root)
    return root


def build_patterns(fname, plines, entities):
    '''Create list of entity patterns

    Args:
        fname = name of file the patterns came from
        plines = split-out pattern lines
        entities = dict with known entities as keys
    Returns:
        list of (compiled pattern, entity name) tuples in same order
        as in the file.
        returns string message on error
    '''
    plist = list()
    for (lineno, flds) in plines:
        loc = f'at {fname}:{lineno}'
        if len(flds) != 2:
            return f'Invalid pattern line {loc}'
        (patt, entity) = flds
        if entity not in entities:
            return 'Unknown entity name {entity} {loc}'
        try:
            t = re.compile(patt + '$')
        except Exception:
            return f'Invalid pattern {patt} {loc}'
        plist.append((t, entity))
    return plist


def build_weights(fname, wlines):
    '''Create dict of model types and weights

    Args:
        fname = name of file the weights came from
        wlines = split-out model weight lines
    Returns:
        dict with model name as key and (CPUs, SBUs) tuple as value
        returns string message on error
    '''
    weights = dict()
    for (lineno, flds) in wlines:
        loc = f'at {fname}:{lineno}'
        if len(flds) != 3:
            return f'Invalid model line {loc}'
        (name, cpus, sbus) = flds
        if name in weights:
            return f'Duplicate model {name} {loc}'
        try:
            cpus = int(cpus)
        except Exception:
            return f'Invalid #CPUs {cpus} {loc}'
        try:
            sbus = float(sbus)
        except Exception:
            return f'Invalid SBU rating {sbus} {loc}'
        weights[name] = (cpus, sbus)
    return weights


def split_share_info(fname, buf):
    '''Split the text of a shares file into its pieces.

    Examine each line to decide which type it is.
    Remove comments.

    Args:
        fname = name of source file (for error messages)
        buf = contents of file
    Returns:
        tuple of lists (nodes, patterns, weights)
            where each is a list of tuples (lineno, line)
    '''
    nodes = list()
    patterns = list()
    weights = list()
    lineno = 0
    for line in buf.splitlines():
        lineno += 1
        # Truncate line at comments
        if line.startswith('#map') or line.startswith('#model'):
            line = '#' + line[1:].partition('#')[0]
        else:
            line = line.partition('#')[0]
        line = line.strip()
        flds = line.split()
        # skip empty or comment lines
        if line == '':
            continue
        if flds[0] == '#map':
            patterns.append((lineno, flds[1:]))
            continue
        if flds[0] == '#model':
            weights.append((lineno, flds[1:]))
            continue
        nodes.append((lineno, flds))
    return (nodes, patterns, weights)


def write_new_usage(fname, shares):
    '''Write out current usage information in Altair binary format

    Args:
        fname = file to write to
        shares = current shares info
    '''
    # Write out header
    global gnow
    buf = bytearray()
    hdr_fmt = '9sdl'
    t = struct.pack(hdr_fmt, bytes(MAGIC_NAME, 'utf-8'), 2.0, int(gnow))
    buf += t
    use_fmt = '50sd'
    for share in shares:
        if share.usage <= 0.0:
            continue
        t = struct.pack(use_fmt, bytes(share.name, 'utf-8'), share.usage)
        buf += t
    with open(fname, mode='wb') as fs:
        fs.write(buf)
    return


clockre = re.compile(r'((\d+)\+)?(\d+):(\d+)(:(\d+))?$')


def clocktosecs(v):
    '''Convert clock time string to integer seconds

    Args:
        v = time, in format [days+]hh:mm[:ss]
    '''
    if v in [None, '', '--']:
        return v
    if v.isdigit():
        return int(v)
    mo = clockre.match(v)
    if not mo:
        return '--'
    (days, hours, minutes, seconds) = mo.group(2, 3, 4, 6)
    days = int(days) if days else 0
    hours = int(hours) if hours else 0
    minutes = int(minutes) if minutes else 0
    seconds = int(seconds) if seconds else 0
    return seconds + 60 * (minutes + 60 * (hours + 24 * days))


if __name__ == '__main__':

    sys.exit(main())
# vi:ts=4:sw=4:expandtab
