import os
import sys
import nas_xstat_config as conf

'''
Poor man's implementation of pbs_loadconf()

'''


def pbs_conf():
    return dir(pbs_conf)


_subs = dict([
    ['PBS_DEFAULT', 'pbs_server_name'],
    ['PBS_SERVER', 'pbs_server_name'],
    ['PBS_EXEC', 'pbs_exec_path'],
    ['PBS_HOME', 'pbs_home_path'],
    ['PBS_START_MOM', 'start_mom'],
    ['PBS_START_SCHED', 'start_sched'],
    ['PBS_START_SERVER', 'start_server'],
    ['PBS_WEBAPI_PORT', 'pbs_webapi_port'],
    ])


def nas_loadconf(reload=0):
    """
    Populate pieces of a fake pbs_conf structure. Altair does not provide
    access to the real pbs_conf from pbs_ifl module.

    Note: modifies sys.path to include path to Altair python modules.

    Args:
        reload = 0 to populate from scratch, else retain previous values
    Returns:
        True on success, else False
    """
    global pbs_conf
    if not reload or not pbs_conf.get('loaded'):
        t = dir(pbs_conf)
        for attr in t:
            if attr.startswith('__'):
                continue
            delattr(pbs_conf, attr)
    # Load data into pbs_conf attributes

    nas_setconf()

    # Update sys.path now that we know where pbs_ifl module should be
    pbs_exec = pbs_conf.pbs_exec_path
    pymods = os.path.join(pbs_exec, 'lib', 'python', 'altair')
    sys.path.append(pymods)
    import pbs_ifl

    # Also load the real config data
    t = pbs_ifl.pbs_loadconf(reload)
    return True if t else False


def nas_setconf():
    """
    Helper for nas_loadconf that does not need ifl
    """
    global pbs_conf
    # First, locate pbs_conf file
    conf_file = os.getenv('PBS_CONF_FILE', '/etc/pbs.conf')
    # Load values from it
    with open(conf_file, 'r') as fs:
        for line in fs:
            (name, _, value) = line.partition('=')
            if _ == '':
                continue
            name = name.strip()
            value = value.strip()
            if not name.startswith('PBS_'):
                continue
            if value.isdigit():
                value = int(value)
            if name in _subs:
                setattr(pbs_conf, _subs[name], value)
            else:
                name = name[4:]
                setattr(pbs_conf, name.lower(), value)
    # Now, overwrite any from the environment
    for (name, value) in os.environ.items():
        if not name.startswith('PBS_'):
            continue
        if value.isdigit():
            value = int(value)
        if name in _subs:
            setattr(pbs_conf, _subs[name], value)
        else:
            name = name[4:]
            setattr(pbs_conf, name.lower(), value)
    # Mark that conf has been read
    setattr(pbs_conf, 'loaded', 1)
    setattr(pbs_conf, 'pbs_conf_file', conf_file)
    conf.pbs_conf = pbs_conf


__all__ = ['nas_loadconf']
