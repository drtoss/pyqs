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

# These defaults should be overridden by the caller.
# See set_fs_info() for how to change them.
fs_decay_interval = 24 * 3600.0
fs_decay_factor = 0.5
unknown_alloc = 10
unknown_grp_id = 0
sched_priv = '/var/spool/pbs/sched_priv'
sched_config = os.path.join(sched_priv, 'sched_config')
formula_file = None
groups_file = os.path.join(sched_priv, 'resource_group')
nas_shares_file = os.path.join(sched_priv, 'shares')
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
        self.children = list()      # children of this node
        self.fs_factor = 0.0
        self.depth = 0              # indent to print in tree form


def set_fs_info(*lst, **kwds):
    '''Set global values for other routines

    Args:
        hn = hostname
        df = fs_decay_factor (float)
        di = fs_decay_interval (seconds)
        ff = job sort formula file
        gf = groups_file (resource_groups) path
        rs = reset global maps
        sc = sched_config file
        sf = NAS shares file
        sp = sched_priv directory
        ua = unknown_alloc (float)
        uf = usage_file path
    '''
    global shost, fs_decay_factor, fs_decay_interval, groups_file, unknown_alloc
    global usage_file, trust_job_info, gnow, asof_time, nas_shares_file
    global sched_priv, sched_config, formula_file
    args = dict(lst)
    if kwds:
        args.update(kwds)
    for (key, value) in args.items():
        if key == 'df':
            fs_decay_factor = value
        elif key == 'di':
            fs_decay_interval = value
        elif key == 'ff':
            formula_file = value
        elif key == 'hn':
            shost = value.split('.')[0]
        elif key == 'gf':
            groups_file = value
        elif key == 'sc':
            sched_config = value
        elif key == 'sp':
            # When sched_priv directory changes, point other files there
            sched_priv = value
            sched_config = os.path.join(sched_priv, 'sched_config')
            groups_file = os.path.join(sched_priv, 'resource_group')
            nas_shares_file = os.path.join(sched_priv, 'shares')
            usage_file = os.path.join(sched_priv, 'usage')
        elif key == 'sf':
            nas_shares_file = value
        elif key == 'tj':
            trust_job_info = value
        elif key == 'ua':
            unknown_alloc = int(value)
        elif key == 'uf':
            usage_file = value
        elif key == 'rs':
            share_name_map.clear()
            share_id_map.clear()
            map_cache.clear()
            trust_job_info = False
            gnow = time.time()
            asof_time = gnow
        else:
            print(f'Unknown parameter to set_fs_info: {key}', file=stderr)
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
    root_usage = 1.0 if tree.usage == 0.0 else tree.usage
    for share in tree.children:
        share.usage_factor = share.usage / root_usage
        calc_fs_tree_usage_helper(root_usage, share)


def calc_fs_tree_usage_helper(root_usage, child):
    '''Helper routine to recurse through subtree

    Args:
        root_usage = total usage in tree
        child = a node in the tree to start with
    '''
    if not child:
        return
    parent = child.parent
    if not parent:
        return
    portion = child.usage / root_usage
    child.usage_factor = portion + \
        (parent.usage_factor - portion) * child.grp_pct
    for share in child.children:
        calc_fs_tree_usage_helper(root_usage, share)


def calc_fs_percent(share):
    '''Calc group share percent of total

    Args:
        share = base of subtree
    '''

    if not share or not share.parent:
        return
    parent = share.parent
    grp_alloc = count_alloc(parent)
    # Detect no alloc
    if grp_alloc * parent.tree_pct == 0:
        share.grp_pct = 0.0
        share.tree_pct = 0.0
    else:
        share.grp_pct = float(share.alloc) / grp_alloc
        share.tree_pct = share.grp_pct * parent.tree_pct
    for child in share.children:
        calc_fs_percent(child)


def count_alloc(share):
    '''Count allocations in a group

    The group includes the share and all of its sibs

    Args:
        share = the start of a sib list
    Returns:
        sum of the allocations for the sib list
    '''
    tot_alloc = sum([x.alloc for x in share.children])
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
    t = [tree]
    for child in tree.children:
        t.extend(depth_first(child, depth+1))
    return t


def depth_first_attr(tree, attr, depth, rev=False):
    '''Visit tree in depth first order sorted on attr

    Args:
        tree to visit
            nodes will have their depth value updated
        attr = name of attribute to sort on
        depth = current depth
        rev = sort high to low
    Returns:
        Tree nodes, depth first, sorted on attr
    '''
    if not tree:
        return []
    tree.depth = depth
    t = [tree]
    chlds = sorted(tree.children, key=lambda x: getattr(x, attr), reverse=rev)
    for child in chlds:
        t.extend(depth_first_attr(child, attr, depth+1, rev))
    return t


def insert_child(parent, child):
    '''Add a child to a share's child chain

    In alphabetical order

    Args:
        parent = share to add child to
        child = child to add
    '''
    name = child.name
    children = parent.children
    # Find out where child fits in current children list
    for i in range(len(children)):
        if name < children[i].name:
            children.insert(i, child)
            break
    else:
        children.append(child)
    return


def load_usage(root):
    '''Read group usage data from file

    Args:
        root = root of shares tree
    Globals
        usage_file = path to group usage data
        asof_time = set based on timestamp from usage_file
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
    # The timestamp in the usage file header is the time of the most
    # recent decay. So, we can accept anything up to next decay.
    asof_time = header[2] + fs_decay_interval - 1
    use_fmt = '50sd'
    for entry in struct.iter_unpack(use_fmt, buf[sz:]):
        name = str(entry[0].partition(b'\0')[0], encoding='utf-8')
        # Handle entities not in group file
        if name not in share_name_map:
            share = add_unknown_group(name)
            if share is None:
                name = UNKNOWN_GROUP_NAME
        share_name_map[name].usage += entry[1]
    # Set values for any children of unknown
    calc_fs_percent(share_name_map[UNKNOWN_GROUP_NAME])
    return


def add_unknown_group(name):
    '''Add a child of the unknown group

    Args:
        name = entity to add
    Returns:
        entity's Share
        None if not allowed to have unknown entities
    '''
    global unknown_grp_id
    unk = share_name_map[UNKNOWN_GROUP_NAME]
    if unk.alloc == 0:
        return None
    share = new_group(name, unk.grp_id, unknown_grp_id)
    unknown_grp_id += 1
    # Link it in
    share.alloc = unknown_alloc
    share.parent = unk
    share.par_id = unk.grp_id
    insert_child(unk, share)
    share.grp_path = create_group_path(share)
    return share


def load_usage_from_jobs(fname, tree, patts, weights, args={}):
    '''Compute usage from job info.

    Re-calculate usage info from job info dump.

    Args:
        fname = path to file with nas_qstat -xf output
        tree = entity tree build from groups file
        patts = [NAS only] patterns to map egroup:euser to entity
        weights = [NAS only] mapping from node model info to SBU rating
        args = options dict
    Returns:
        True on success
    '''
    global asof_time
    from nas_pbsutil import lines_to_stat, info_to_file
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
                   'Account_Name', 'job_state', 'obittime', 'stime',
                   'etime',
                   'group_list', 'Resource_List']
    if args.new_jobs:
        # If writing updated jobs file, keep all attributes
        interesting = []
    jobs = lines_to_stat(lines, interesting)
    del lines
    for job in jobs:
        jobname = job['id']
        job_state = job.get('job_state', '?')
        # Ignore jobs with no start time
        t = job.get('stime')
        if t is None:
            continue
        stime = int(t.split()[0])
        if stime > asof_time:
            # Ignore jobs started after as-of time
            print(f'{jobname} starts after end of window')
            continue
        # Get walltime to compute end time
        t = job.get('resources_used.walltime')
        if t is None:
            continue
        t = clocktosecs(t)
        etime = stime + t
        entity = set_entity_name(job, patts)
        if entity not in share_name_map:
            share = add_unknown(entity)
            if share is None:
                print(f'Unknown entity for job {jobname}: {entity}',
                      file=stderr)
                entity = UNKNOWN_GROUP_NAME
        sbu_rate = set_sbu_rate_nh(job, weights)
        if isinstance(sbu_rate, str):
            print(f'Cannot compute SBU rate for job {jobname} {sbu_rate}',
                  file=stderr)
            continue
        # Multiply sbu_rate by decayed walltime
        use_scale = compute_scale(stime, etime, asof_time)
        eff_sbus = sbu_rate * use_scale
        share = share_name_map[entity]
        share.usage += eff_sbus
    # Set values for any children of unknown
    calc_fs_percent(share_name_map[UNKNOWN_GROUP_NAME])
    # Write updated job file
    if args.new_jobs:
        with open(args.new_jobs, 'w') as fd:
            info_to_file(fd, jobs, 'Job')
    return True


def compute_scale(stime, etime, asof):
    '''Compute the decay factor for a constant usage

    That is, given a constant job usage rate from stime to etime,
    compute the factor the usage rate should be multiplied by to
    determine the total usage, taking decays into account.

    Args:
        stime = job start time (epoch)
        etime = job end time (epoch)
        asof = timestamp to compute factor relative to
    Globals:
        fs_decay_factor = multiplier at each decay interval
        fs_decay_interval = seconds between decays
    Returns:
        scale factor
    '''
    # Adjust etime if needed to not exceed as-of time.
    if etime > asof:
        etime = asof
    # Don't start later than finish
    if stime > etime:
        stime = etime
    # We break time backward from asof into decay intervals and compute
    # the weight of the job's usage during that interval.
    t_end = asof
    t_start = t_end - fs_decay_interval
    factor = 0.0
    scale = 1.0
    while stime < t_end:
        # Compute how much time the job was active in the interval
        jb = max(stime, t_start)
        je = min(etime, t_end)
        used = je - jb
        if used > 0:
            factor += scale * used
        scale *= fs_decay_factor
        t_end = t_start
        t_start -= fs_decay_interval
    return factor


def set_entity_name(job, patts, requestor=None):
    '''Set job's entity

    We're assuming the Account_Name will be used by fairshare as the
    entity to associate with job usage (fairshare_entity).

    If the event requestor is a manager, we use whatever entity they
    specified.

    Args:
        job = job info
        patts = patterns mapping group:user to entity
        requestor = user requesting action (for qsub)
    Returns:
        selected entity, also put in job's entity attribute
        None if lookup failed
    '''
    entity = job.get('NAS_entity')
    if entity:
        return entity
    entity = job.get('Account_Name')
    if entity and trust_job_info:
        if entity not in share_name_map:
            entity = UNKNOWN_GROUP_NAME
        job['NAS_entity'] = entity
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
        job['NAS_entity'] = entity
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
        rate = float(rate)
        job['Resource_List.sbu_rate'] = rate
        return rate
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
    # First, build parent and child links
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
    # Compute total alloc of root's children
    root.alloc = sum([share.alloc for share in root.children])
    unk = share_name_map[UNKNOWN_GROUP_NAME]
    unk.alloc = unknown_alloc
    for child in root.children:
        calc_fs_percent(child)
    return True


def reconcile_usage(root):
    # Add current use values for leaf nodes into their ancesters
    for share in share_id_map.values():
        if share.children:
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


def load_fs_info(fname, sname=None):
    '''Read and parse fairshare info file(s)

    Args:
        fname = path to file to load groups from
        sname = if given, path to load patterns and weights from
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
    buf2 = None
    if sname:
        try:
            with open(sname) as fs:
                buf2 = fs.read()
        except OSError:
            return f'Cannot read {sname}'
    (nlines, plines, wlines) = split_share_info(fname, buf, sname, buf2)
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
    global unknown_grp_id
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
        if grp_id > unknown_grp_id:
            unknown_grp_id = grp_id
        share.alloc = alloc
    # Add the unknown group at end
    unknown = new_group(UNKNOWN_GROUP_NAME, 0, 1)
    unknown.alloc = unknown_alloc
    unknown_grp_id += 1
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
            return f'Unknown entity name {entity} {loc}'
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


def split_share_info(fname, buf, sname, buf2):
    '''Split the text of a shares file into its pieces.

    Examine each line to decide which type it is.
    Remove comments.

    Args:
        fname = name of source file (for error messages)
        buf = contents of file
        sname = name of NAS shares file (for error messages)
        buf2 = contents of file
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
    # Repeat with info from NAS shares file
    lineno = 0
    if buf2 is None:
        buf2 = ''
    for line in buf2.splitlines():
        lineno += 1
        # Truncate line at comments
        line = line.partition('#')[0].strip()
        flds = line.split()
        if line == '':
            continue
        if flds[0] == 'type':
            weights.append((lineno, flds[2:]))
            continue
        if len(flds) == 2:
            patterns.append((lineno, flds))
            continue
        print(f'Unknown line time in {sname} at {lineno}', file=sys.stderr)
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
        # Write out only non-zero leaf usage
        if share.usage <= 0.0 or share.children:
            continue
        t = struct.pack(use_fmt, bytes(share.name, 'utf-8'), share.usage)
        buf += t
    with open(fname, mode='wb') as fs:
        fs.write(buf)
    return


def load_sched_conf(fname):
    '''Read sched_config file

    Read the file and return a dict of the keys and values

    Args:
        fname = path to sched_config file
    Returns:
        dict
        str with text on error
    '''
    try:
        with open(fname) as fs:
            buf = fs.read()
    except IOError:
        return "Unable to read config file" + fname
    settings = dict()
    lineno = 0
    for line in buf.splitlines():
        lineno += 1
        if line.startswith('#'):
            continue
        if line.strip() == '':
            continue
        line = line.expandtabs()
        flds = line.split(':', 1)
        if len(flds) != 2:
            return f"Bad format at {fname}:{lineno} {line}"
        key = flds[0].strip()
        value = flds[1].strip()
        if not key.isidentifier():
            return f"Bad line at {fname}:{lineno} {line}"
        # Handle keys that can appear multiple times
        if key.endswith('_sort_key'):
            if key in settings:
                settings[key].extend([value])
            else:
                settings[key] = [value]
        else:
            settings[key] = value
    return settings


def set_from_conf():
    '''Set fairshare values from scheduler config file
    '''
    global fs_usage_res, fs_entity, fs_decay_interval, fs_decay_factor
    global unknown_alloc
    fsparam = load_sched_conf(sched_config)
    if fsparam.get('fairshare_decay_factor'):
        fs_decay_factor = float(fsparam['fairshare_decay_factor'])
    if fsparam.get('fairshare_decay_time'):
        fs_decay_interval = clocktosecs(fsparam['fairshare_decay_time'])
    if fsparam.get('fairshare_entity'):
        fs_entity = fsparam['fairshare_entity']
    if fsparam.get('fairshare_usage_res'):
        fs_usage_res = fsparam['fairshare_usage_res']
    if fsparam.get('unknown_shares'):
        unknown_alloc = int(fsparam['unknown_shares'])
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


if __name__ == 'XXX__main__':
    print(load_sched_conf('sched_config'))
    sys.exit(0)


# vi:ts=4:sw=4:expandtab
