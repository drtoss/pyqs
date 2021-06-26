#!/usr/bin/python3
'''
Module that encapsulates all the information needed by layout routines
to format columnar fields.

There is one class, NAS_field_format, whose function is just to hold
all the relevant information for one display type.

The rest of the module is functions that know how to convert various
PBS attributes into strings.
'''

import re
import time
import math

class NAS_field_format(object):

  def __init__(self, default_fields, verbose = False, opts_W = None):
    ''' Create new display formatter

    The arguments are saved away for later use.

    Args:
        default_fields = List of names of default fields
        verbose = boolean to enable extra debugging output
        opts_W = List of -W command line arguments that affect formatting
    '''
    self.default_fields = default_fields
    self.verbose = verbose
    self.W = opts_W
    self.known_fields = []
    self.field_list = []

  def adjust_formats(self, fl, optW=None):
    '''Adjust layout options for fields

    Take a list of field_info dictionaries and modify the layout parameters
    from the -W options. The options we are interested in look like:
    fmt_xxx="key:value key:value"

    Args:
        fl = list of field_info data
        optW = list of -W options, default is W instance var
    Returns: True if no errors, else error messages
    '''

    errlist = []
    valid_keys = ('title',
            'df', 'dj', 'ds', 'dt',
            'hf', 'hj', 'hs', 'ht',
            'maxw', 'minw',
            'rf', 'rj', 'rs', 'rt', 'suppress'
            )
    if optW == None:
        optW = self.W
    for wopt in optW:
        # Is it our kind of W option?
        mo = re.match(r'fmt_(\w+)=(.+)', wopt)
        if not mo:
            continue
        # Do we care about it?
        name = mo.group(1)
        for i in range(len(fl)):
            if fl[i]['name'] == name:
                idx = i
                break
        else:
            continue
        # Parse formatting options (key:value key:value)
        opt_str = mo.group(2).strip()
        opts = []
        while opt_str != '':
            mo = re.match(r'(\w+)[:=]\s*([^ ]*)(.*)', opt_str)
            if not mo:
                errlist.append("Garbage in format spec for %s: %s" % \
                    (name, opt_str))
                break
            key = mo.group(1)
            value = mo.group(2)
            opt_str = mo.group(3)
            opt_str = opt_str.strip() if opt_str else ''
            # Validate keys. There's probably a better place to do this.
            if not key in valid_keys:
                errlist.append("Unknown formatting spec for field %s: %s" % \
                    (name, key))
                errlist.append("Valid specs are: " + ", ".join(valid_keys))
                break
            opts.append((key, value))
        # Ignore if parse problem
        if opt_str != '':
            continue
        # Update field list format with new values
        for (key, value) in opts:
            if key == 'title':
                # Might need to convert title to multi-line list
                title = re.sub(r'\\n','\n',value)
                if title != value:
                    title = title.split('\n')
                fl[idx]['title'] = title
            elif key in ['minw', 'maxw']:
                fl[idx]['format'][key] = int(value)
            elif key in ['suppress']:
                fl[idx]['format'][key] = bool(value)
            else:
                # Handle special names for hard to input values
                if value == '""' or value == "''":
                    value = ''
                elif value == 'space':
                    value = ' '
                elif value == 'tab' or value == '\\t':
                    value = '\t'
                fl[idx]['format'][key] = value
    if errlist:
        return '\n'.join(errlist)
    return True

  def collect_fields(self):
    '''Generate list of fields

    Instance vars:
        default_fields = List of default field names
        known_fields = List of info about known fields
    Returns:
        (fl, aset, msg) where
L           fl = list of field_info dictionaries describing field selected
                for display
            aset = set of PBS attributes holding data for fields in fl
            msg = Text of any errors, None if no errors
    '''
    fl = self.default_fields
    W = self.W
    errlist = []
    if W is None:
        W = []
    for opt in W:
        # Check for request to list fields
        if opt == 'o=?':
            names = [x['name'] for x in self.known_fields]
            errlist.append("Known fields: " + ', '.join(names))
            return (None, None, errlist)
        # Only interested in changes to list of fields
        mo = re.match(r'o=([+-]?)(.*)', opt)
        if not mo:
            continue
        plusminus = mo.group(1)
        names = mo.group(2).split(',')
        if plusminus == '':
            fl = [n.strip() for n in names]
        elif plusminus == '-':
            for name in names:
                name = name.strip()
                while name in fl:
                    fl.remove(name)
        else:
            for name in names:
                fl.append(name.strip())
    # Now, validate fields and constuct results
    knownmap = dict([[x['name'], x] for x in self.known_fields])
    knowns = set(knownmap.keys())
    requested = set(fl)
    unknowns = requested.difference(knowns)
    if unknowns:
        plural = 's' if len(unknowns) > 1 else ''
        errlist.append("Unknown field name%s: %s" % (plural, ', '.join(sorted(unknowns))))
        errlist.append("Known fields are: %s" % ', '.join(sorted(knowns)))
    fil = [knownmap[x] for x in fl if x in knownmap]
    alist = list()
    for x in fil:
        t = x['sources']
        if t:
            alist.extend(t)
    aset = set(alist)
    if self.verbose:
        print("Need these attributes: %s" % ', '.join(sorted(aset)))
    return (fil, aset, '\n'.join(errlist) if errlist else None)

def gen_field(name, title, form, func, source, opt=None):
    '''Create a field_info dict

    Args:
        name = name of field
        title = display title for field
        form = dictionary of non-default formatting options for field
        func = name of function to calculate display value of field
        source = list of PBS attributes used by func
        opt = additional info for use by func
    '''
    if form is None:
        form = {}
    else:
        # Need unique format dict for each field
        form = form.copy()
    if func is None:
        func = 'get_by_name'
    if source is None:
        source = ''
    fi = {'name': name,
        'title': title,
        'format': form,
        'func': func,
        'sources': source.split() if source else None,
        'opt': opt
        }
    return fi

# Module global values

def set_field_vars(opts):
    ''' Set global options from command line arguments

    That is, certain command line arguments affect the formatting for
    multiple field types. Check for and remember those arguments.
    '''
    global gnow, gropt, gszunits, ghuman

    # gszunits = units for display of sizes
    gszunits = 'G' if 'G' in opts else 'M' if 'M' in opts else 'b'
    # ghuman = True to use human readable
    ghuman = '-H' in opts or 'human' in opts or gszunits != 'b'
    # gnow = current epoch time
    gnow = int(time.time())
    # gropt = True if -W raw for raw values
    gropt = '-r' in opts or 'raw' in opts

def set_entity_map(themap):
    '''Save reference to entity map

    Some formatters need access to share entity information.
    Save away a reference to that info.
    '''
    global gshare_entity_info
    gshare_entity_info = themap

# Functions to compute specific values for display
# fmt_xxx(fi, info, opts)
# Args:
#   fi = field info
#   info = dict with info for job/reservation
#   opts = dict of formatting options

def fmt_by_attr(fi, info, opts):
    t = fi['sources']
    attr_name = t[0] if t else None
    return fmt_by_name(fi, info, opts, attr_name)

def fmt_by_name(fi, info, opts, name=None):
    if name == None:
        name = fi['name']
    if name in info:
        result = info[name]
    else:
        t = 'Resource_List.' + name
        if t in info:
            result = info[t]
        else:
            result = '--'
    return result

def fmt_aoe(fi, info, opts):
    rawv = fmt_by_attr(fi, info, opts)
    mo = re.search(r'\baoe=(\w+)', rawv)
    if (mo):
        return mo.group(1)
    return '--'

def fmt_comment(fi, info, opts):
    rawv = fmt_by_attr(fi, info, opts)
    if gropt or rawv == '--':
        return rawv
    t = str.maketrans(' \t\n\r', '____')
    return rawv.translate(t)

def fmt_date(fi, info, opts):
    rawv = fmt_by_attr(fi, info, opts)
    if gropt or rawv == '--':
        return rawv
    result = time.strftime(r'%y-%m-%d/%H:%M', time.localtime(int(rawv)))
    return result

def fmt_date_full(fi, info, opts):
    rawv = fmt_by_attr(fi, info, opts)
    if gropt or rawv == '--':
        return rawv
    result = time.strftime(r'%c', time.localtime(int(rawv)))
    return result
    
def fmt_duration(fi, info, opts):
    rawv = fmt_by_attr(fi, info, opts)
    if gropt or rawv == '--':
        return rawv
    return secstoclock(int(rawv))

def fmt_efficiency(fi, info, opts):
    ncpus = info.get('resources_used.ncpus')
    cpu_pct = info.get('resources_used.cpupercent')
    if not ncpus or not cpu_pct or ncpus == "0":
        return '--'
    eff = float(cpu_pct) / float(ncpus)
    # There is a bug where the cpupercent goes up, but never goes
    # back down. So, if we have cputime and walltime, compute a
    # better value.
    cput = info.get('resources_used.cput')
    walltime = info.get('resources_used.walltime')
    if cput and walltime:
        cputs = clocktosecs(cput)
        walls = clocktosecs(walltime)
        cpus = float(ncpus)
        if cpus > 0 and walls > 0:
            effc = 100.0 * cputs / (cpus * walls)
            if effc < eff:
                eff = effc
    return "%.0f%%" % eff

def fmt_elapsed(fi, info, opts):
    state = info.get('job_state', '?')
    if state in 'RSBEFX':
        rawv = info.get('resources_used.walltime', '--')
        if gropt or rawv == '--':
            return rawv
        return secstoclock(clocktosecs(rawv), False, ghuman)
    etime = info.get('etime', gnow)
    t = gnow - int(etime)
    return secstoclock(t, False, ghuman)

def fmt_elig_time(fi, info, opts):
    rawv = info.get('eligible_time', '--')
    return secstoclock(clocktosecs(rawv), False, ghuman)

def fmt_est_end(fi, info, opts):
    guess = ''
    start = info.get('stime', None)
    if start == None:
        start = info.get('estimated.start_time', None)
        guess = '?'
    if start == None:
        return '--'
    start = int(start)
    walltime = None
    jobstate = info.get('job_state', '?')
    if jobstate == "F":
        walltime = info.get('resources_used.walltime', None)
    if walltime == None:
        walltime = info.get('Resource_List.walltime', None)
    if walltime == None:
        return '--'
    wtime = clocktosecs(walltime)
    t = time.strftime(r'%y-%m-%d/%H:%M',time.localtime(start + wtime))
    return t + guess

def fmt_from_rsrc(fi, info, opts):
    # Pick one item out of a resource list
    key = fi['opt']
    for src in fi['sources']:
        rawv = info.get(src + '.' + key, '--')
        if rawv != '--':
            break
    else:
        rawv = '--'
    return rawv

def fmt_from_rsrc_tm(fi, info, opts):
    # Pick one duration item out of a resource list
    key = fi['opt']
    for src in fi['sources']:
        rawv = info.get(src + '.' + key, '--')
        if rawv != '--':
            break
    else:
        rawv = '--'
    if rawv == '--':
        return rawv
    t = secstoclock(clocktosecs(rawv), False, ghuman)
    return t

def fmt_from_rsrc_sz(fi, info, opts):
    # Pick one size item out of a resource list
    key = fi['opt']
    for src in fi['sources']:
        rawv = info.get(src + '.' + key, '--')
        if rawv != '--':
            break
    else:
        rawv = '--'
    if rawv == '--':
        return rawv
    t = ensuffix(unsuffix(rawv))
    return t

def fmt_future_date(fi, info, opts):
    rawv = fmt_from_rsrc(fi, info, opts)
    if rawv == '--':
        return rawv
    est = int(rawv)
    # Round to quarter hours
    rounding = 15 * 60
    eststart = (math.ceil(est / rounding) * rounding)
    delta = eststart - gnow
    if delta <= 0:
        return '--'
    if delta > 84600:
        # More than 23 1/5 hours ahead -- use date format
        t = time.strftime(r'%m/%d', time.localtime(eststart))
        s = time.localtime(eststart)
        ampm = 'P' if s[3] > 11 else 'A'
        return t + ampm
    t = time.strftime(r'%H:%M', time.localtime(eststart))
    return t

def fmt_id(fi, info, opts):
    rawv = info['id']
    if gropt or rawv == '--':
        return rawv
    return rawv.split('.')[0]

def fmt_jobid(fi, info, opts):
    rawv = info['id']
    t = rawv.split('.')
    if len(t) <= 1:
        return rawv
    return t[0] + '.' + t[1]

def fmt_jobstate(fi, info, opts):
    jobstate = info.get('job_state', None)
    holds = info.get('Hold_Types', '')
    if holds == 'n':
        holds = ''
    elif holds == 's':
        deps = info.get('depend', '')
        if deps:
            holds = 'd'
    itv = 'I' if info.get('interactive', None) == 'True' else ''
    return jobstate + itv + holds

def fmt_lifetime(fi, info, opts):
    qtime = info.get('qtime', None)
    if qtime:
        jobstate = info.get('job_state', None)
        if jobstate in ['F', 'X']:
            # Until there is an end time attribute, assume
            # the mod time corresponds to the end time.
            mtime = info.get('mtime', gnow)
            lifetime = int(mtime) - int(qtime)
        else:
            lifetime = gnow - int(qtime)
        t = secstoclock(lifetime, False, ghuman)
    else:
        t = '--'
    return t

def fmt_mission(fi, info, opts):
    global gshare_entity_info
    entity = info.get('share_entity', None)
    t = gshare_entity_info.get(entity, dict())
    leader = t.get('leader', '--')
    return leader

modelre = re.compile(r'^(\d+)?.*\bmodel=(\w+)')
def fmt_model(fi, info, opts):
    # Raw format: 4:ncpus=3:model=sky_gpu:bigmem=false
    rawv = fmt_by_attr(fi, info, opts)
    if gropt or rawv== '--':
        return rawv
    models=[]
    for chunk in rawv.split('+'):
        mo = modelre.search(chunk)
        if (mo):
            count = mo.group(1)
            if count == None:
                continue
            models.append(count + ':' + mo.group(2))
    if models:
        return '+'.join(models)
    return '--'

def fmt_name(fi, info, opts):
    return fmt_by_attr(fi, info, opts)

def fmt_nodes(fi, info, opts):
    # Raw format:  (r789i0n4:ncpus=1)+(r789i0n5:ncpus=1)
    rawv = fmt_by_attr(fi, info, opts)
    if gropt or rawv == '--':
        return rawv
    items = rawv.split('+')
    nodes = list()
    for item in items:
        mo = re.match(r'\(?([^:]+)', item)
        if mo:
            nodes.append(mo.group(1))
    return ",".join(nodes)

def fmt_no_space(fi, info, opts):
    # Reformat so value won't get split by awk, etc.
    rawv = fmt_by_attr(fi, info, opts)
    return re.sub(r'\s+', '_', rawv)

def fmt_queue_info(fi, info, opts):
    # Select interesting info about queue status
    stuff = []
    t = info.get('enabled', None)
    if t != 'True':
        stuff.append('disabled')
    t = info.get('started', None)
    if t != 'True':
        stuff.append('stopped')
    return " ".join(stuff)

def fmt_rank0(fi, info, opts):
    # Raw format:  node1/0+node1/1+node2/0
    rawv = fmt_by_attr(fi, info, opts)
    if gropt or rawv == '--':
        return rawv
    rank0 = rawv.split('/',1)[0]
    if rank0:
        return rank0
    return '--'

def fmt_remaining(fi, info, opts):
    req = info.get('Resource_List.walltime', None)
    if req == None:
        return '--'
    jstate = info.get('job_state', ' ')
    if jstate in 'BERSU':
        elap = info.get('resources_used.walltime', '0')
        rem = clocktosecs(req) - clocktosecs(elap)
    else:
        if jstate in 'FX':
            rem = '--'
        else:
            rem = clocktosecs(req)
    return secstoclock(rem, False, ghuman)

def fmt_resv_state(fi, info, opts):
    rawv = fmt_by_attr(fi, info, opts)
    if gropt or rawv == '--':
        return rawv
    return decode_resv_state(rawv)

def fmt_seqno(fi, info, opts):
    rawv = info.get('id', '--')
    return rawv.split('.')[0]

def fmt_server_info(fi, info, opts):
    # Select interesting info about server status
    stuff = []
    t = info.get('server_state', None)
    if t and not t in ['Active', 'Idle']:
        stuff.append(t)
    t = info.get('scheduling', None)
    if t and not t == 'True':
        stuff.append("Scheduling stopped")
    t = info.get('comment', None)
    if t and not t == '':
        stuff.append(t)
    return " ".join(stuff)

def fmt_state_count(fi, info, opts):
    # State counts already formatted into pretty_sc attribute
    t = info.get('pretty_sc', '--')
    return t

def fmt_user(fi, info, opts):
    # Raw format: user@host, or just user
    rawv = fmt_by_attr(fi, info, opts)
    # If -W -r, return raw value
    if gropt or rawv == '--':
        return rawv
    return rawv.split('@')[0]

# Misc helper functions for formatting routines

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
    (days, hours, minutes, seconds) = mo.group(2,3,4,6)
    days = int(days) if days else 0
    hours = int(hours) if hours else 0
    minutes = int(minutes) if minutes else 0
    seconds = int(seconds) if seconds else 0
    return seconds + 60 * (minutes + 60 * (hours + 24 * days))

def decode_epoch_full(rawv):
    result = time.strftime('%c', time.localtime(int(rawv)))
    return result

def decode_resv_state(rawv):
    return ("--",  "UN", "CO", "WT", "TR", "RN", "FN", "BD", "DE", "DJ", "DG", "AL", "IC")[int(rawv)]

def decode_resv_state_full(rawv):
    return ("RESV_NONE", "RESV_UNCONFIRMED", "RESV_CONFIRMED",
            "RESV_WAIT", "RESV_TIME_TO_RUN", "RESV_RUNNING",
            "RESV_FINISHED", "RESV_BEING_DELETED", "RESV_DELETED",
            "RESV_DELETING_JOBS", "RESV_DEGRADED", "RESV_BEING_ALTERED",
            "RESV_IN_CONFLICT")[int(rawv)]

def ensuffix(v):
    '''Scale a memory value

    Convert a raw byte count to the form 1234xB where x denotes
    kilo-, mega-, ...
    The global settings for -M and -G force particular scaling

    Args:
        v = value to convert
    Returns
        String equivalent, rounded to 3-4 places with a suffix.
    '''
    if v == '--' or v == '':
        return v
    if v < 0:
        sign = -1
        v = 0.0 - v
    else:
        sign = 1
    if gszunits == 'M':
        factor = 8.0 * 1024 * 1024
        scale = 'MW'
    elif gszunits == 'G':
        factor = 1024.0 * 1024 * 1024
        scale = 'GB'
    else:
        factor = 1.0
        scale = ''
        for t in ['KB', 'MB', 'GB', 'TB', 'PB']:
            if v < 20000 * factor:
                break
            factor *= 1024.
            scale = t
    t = sign * round( v / factor, 0 )
    t = int(t)
    if t == 0:
        return "0"
    return "%d%s" % (t, scale)

def secstoclock(v, sf=False, df=False):
    '''Convert time in seconds for display

    Args:
        v = time, in seconds
        sf = True to display seconds also
        df = True to convert time over 48 hours into days
    Returns:
        string in form [days+]hh:mm[:ss]
    '''
    if v == '' or v == '--':
        return v
    if v < 0:
        sign = '-'
        v = 0 - v
    else:
        sign = ''
    if sf:
        secsuf = ":%02d" % (v % 60)
        dhm = v // 60
    else:
        secsuf = ""
        dhm = (v + 30) // 60
    if df and dhm // 60 > 48:
        d = dhm // (24 * 60)
        daypfx = "%dd+" % d
        dhm = dhm - d * 24 * 60
    else:
        daypfx = ""
    hh = dhm // 60
    mm = dhm % 60
    return r'%s%s%02d:%02d%s' % (sign, daypfx, hh, mm, secsuf)

sizere = re.compile(r'(-?)([\d.]+)([kmgtp]?)([bw]?)$')
def unsuffix(v):
    '''Convert a memory size value based on suffix

    That is, given a string like 1.23gb, return the result
    in bytes as a float

    Args:
        v = size string to convert
    Returns:
        size in bytes
    '''
    if isinstance(v, float):
        return v        # Already converted
    mo = sizere.match(v.lower())
    if not mo:
        return v
    neg = mo.group(1)
    try:
        value = float(mo.group(2))
    except:
        return v
    scale = mo.group(3)
    words = mo.group(4)
    factor = {'k': 1024.,
            'm': 1024. * 1024,
            'g': 1024. * 1024 * 1024,
            't': 1024. * 1024 * 1024 * 1024,
            'p': 1024. * 1024 * 1024 * 1024 * 1024,
            '': 1.0}.get(scale, 1.0)
    if words == 'w':
        factor *= 8.0
    value *= factor
    if neg == '-':
        value = 0.0 - value
    return value

# vi:ts=4:sw=4:expandtab
