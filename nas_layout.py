#!/usr/bin/python3
"""
"""

def layout(config, rows, skip = 0, show_hdr = True):
    '''Layout data for printing

    Given a configuration and a list of rows of field values,
    create a list of lines ready for output containing headers
    followed by one line for each row, where the values are
    aligned within their columns.

    Args:
        config = described below
        rows = list of row values, each row is a list of field
            values.
        skip = number of leading rows to ignore
        show_hdr = False to skip headers

    Returns:
        A list of lines of formatted data

    The config is built from calls to the add_field() routine.

    Example:
        c = Config()
        c.add_field('fld1')
        c.add_field('fld2', maxw = 3, hj = 'r', hs = '|', rf = '0')
        c.add_field(['fld3', 'cont'], df = '+=', hj = 'r', hs = '')
        layout(c, [['tom', '0', 'one'], ['dick', '1', 'two'],
            ['harry', 1234, 'three']])

      produces:
      ['         | fld3',
       'fld1  ld2| cont',
       '----- ---|+=++=',
       'tom   000|  one',
       'dick  001|  two',
       'harry 234|three']
'''
    # Figure out how many header lines we'll need.
    hdrrows = config.bottom_just_titles()
    hdrcnt = len(hdrrows)
    # And how many fields
    fldcnt = len(config.config)
    # Compute widths of title/dash/data values for
    # each column. Start with the configured
    # minimum widths, possibly increase that for
    # wider values, then impose maxw limits.
    dashrow = [x.df for x in config.config]
    colw = [x.minw for x in config.config]
    config.layout_max(colw, hdrrows)
    config.layout_max(colw, [dashrow])
    config.layout_max(colw, rows, skip)
    for i in range(fldcnt):
        t = config.config[i].maxw
        if t >= 0 and t < colw[i]:
            colw[i] = config.config[i].maxw
    # Layout headers
    result = []
    if show_hdr:
        for row in hdrrows:
            line = ''
            sep = ''
            for i in range(fldcnt):
                fs = config.config[i]
                fval = layout_field(fs.hj, fs.hf, colw[i], row[i], fs.ht)
                line += sep + fval
                sep = fs.hs
            result.append(line)
        # Layout horizontal separator line
        if config.config[0].df != '':
            line = ''
            sep = ''
            for i in range(fldcnt):
                fs = config.config[i]
                fval = layout_field(fs.dj, fs.df, colw[i], dashrow[i], fs.dt)
                line += sep + fval
                sep = fs.ds
            result.append(line)
    # Layout data rows
    for row in rows:
        line = ''
        sep = ''
        for i in range(fldcnt):
            fs = config.config[i]
            fval = layout_field(fs.rj, fs.rf, colw[i], row[skip+i], fs.rt)
            line += sep + fval
            sep = fs.rs
        result.append(line)

    return result

class Config(object):
    def __init__(self):
        self.config = list()

    class fieldspec(object):
        def __init__(self, title, df='-', dj=None, ds=None, dt='',
            hf=' ', hj='l', hs=None, ht=None, maxw=-1, minw=0,
            rf=None, rj=None, rs=None, rt=None):

            # Set contingent defaults
            if hs == None:
                if maxw == 0:
                    hs = ''
                else:
                    hs = ' '
            if dj == None:
                dj = hj
            if ds == None:
                ds = hs
            if dt == None:
                dt = ht
            if rf == None:
                rf = hf
            if rj == None:
                rj = hj
            if rs == None:
                rs = hs
            if rt == None:
                rt = ht
            self.title = title
            self.df = df
            self.dj = dj
            self.ds = ds
            self.dt = dt
            self.hf = hf
            self.hj = hj
            self.hs = hs
            self.ht = ht
            self.maxw = int(maxw)
            self.minw = int(minw)
            self.rf = rf
            self.rj = rj
            self.rs = rs
            self.rt = rt

    def add_field(self, title, **kwargs):
        '''Add settings for one field to config.

        The settings are contained in a fieldspec object.

        Args:
            title = title of field. If the title is a list,
            it will be split across multiple lines in the
            headers.
            df = dashfill   String to repeat to form horizontal
                            separater between headers and data
                            (default -)
            dj = dashjust   Justification for dashfill
                            (default, hj)
            ds = dashseparator Character between this field and
                            the next
                            (default, hs)
            dt = dashtrunc  String to indicate truncation of field
                            (default, ht)
            hf = headerfill String to fill header text to width
                            of column
                            (default space)
            hj = headerjust Header justification (l, c, r, lr)
                            (default l)
            hs = headerseparator Character between the field
                            header and the next
                            (default, space, unless maxw == 0)
            ht = headertrunc String to indicate truncation of the field
            maxw            Maximum width of column, -1 implies
                            no maximum
            minw            Minimum width of column
            rf = rowfill    String to fill data values to width
                            of column
                            (default, hf)
            rj = rowjust    Data justification
                            (default, hj)
            rs = rowseparator Character between this data field
                            and the next
                            (default, hs)
            rt = rowtrunc   String to indicate truncation of field
                            (default, ht)
        '''
        c = self.fieldspec(title, **kwargs)
        self.config.append(c)

    def bottom_just_titles(self):
        '''Bottom justify titles

        Adjust titles so they are all lists with the same
        number of elements, prepending short lists with
        empty strings.

        Returns: A list of title pieces in same structure
        as data rows.
        '''
        cnt = max([1 if isinstance(x.title, str) else len(x.title) for x in self.config])
        for fs in self.config:
            if isinstance(fs.title, str):
                fs.title = [fs.title]
            while len(fs.title) < cnt:
                fs.title.insert(0, '')
        rows = list()
        for i in range(cnt):
            flds = [x.title[i] for x in self.config]
            rows.append(flds)
        return rows

    def layout_max(self, colw, rows, skip = 0):
        '''Compute max widths needed for each column

        Args:
            colw = list to contain column widths
            rows = list of lists of column values
            skip = number of fields to skip in rows
        Exit:
            colw updated
        '''
        fldcnt = len(rows[0])
        for i in range(len(colw), fldcnt):
            colw.append(0)
        for row in rows:
            for i in range(fldcnt):
                t = len(row[i+skip])
                if t > colw[i]:
                    colw[i] = t

def layout_field(just, fill, width, value, trunc=None):
    '''layout one field's value

    Args:
        just = justification
        fill = fill character/string
        width = field width to justify within
        value = text value to layout
        trunc = truncation character/string
    Returns:
        string with value laid out
    '''
    def leftmost(s, n, e=None):
        '''Take leftmost characters of string

        Args:
            s = the string
            n = the max number of characters
            e = elipses string to indicate truncated field
        Returns:
            leftmost part of s
        '''
        if len(s) <= n:
            return s
        if not e:
            return s[0:n]
        if len(e) > n:
            e = e[0:n]
        return s[0:n - len(e)] + e
    def rightmost(s, n, e=None):
        if len(s) <= n:
            return s
        if not e:
            return s[len(s) - n:]
        if len(e) > n:
            e = e[len(e) - n:]
        return e + s[len(s) - n + len(e):]
    def centermost(s, n, e=None):
        '''Return n characters from center of string'''
        sl = len(s)
        if n >= sl:
            return s
        if not e:
            f = (sl - n) // 2
            l = f + n
            return s[f:l]
        if n < 2 * len(e):
            s = e + e
            sl = len(s)
            f = (sl - n) // 2
            l = f + n
            return s[f:l]
        f = (sl - n) // 2 + len(e)
        l = f + n - 2 * len(e)
        return e + s[f:l] + e
    def endmost(s, n, e=None):
        '''Return n characters from ends of string'''
        sl = len(s)
        if n >= sl:
            return s
        if not e:
            half = n // 2
            return s[0:half] + s[sl - (n - half):]
        el = len(e)
        half = (n - el) // 2
        return s[0:half] + e + s[sl - (n - half) + el:]

    if width == 0:
        return ''
    # Determine how much fill is needed
    vlen = len(value)
    if (fill == ''): fill = ' ' # Protect from empty fill
    fplen = len(fill)           # Len of fill pattern
    flen = width - vlen         # Amount of fill needed
    # Convert lr justification to either l or r based on value
    if just == 'lr':
        just = 'r' if value.startswith(' ') else 'l'
    # Set left fill, right fill and value
    if flen < 0:
        # No fill needed
        lfill = ''
        rfill = ''
        if just == 'l':
            result = leftmost(value, width, trunc)
        elif just == 'r':
            result = rightmost(value, width, trunc)
        elif just == 'c':
            result = centermost(value, width, trunc)
        elif just == 'e':
            result = endmost(value, width, trunc)
        else:
            result = leftmost(value, width, trunc)
    else:
        result = value
        flm1 = flen - 1
        reps = (flen + fplen - 1) // fplen
        filler = fill * reps
        if just == 'l':
            lfill = ''
            rfill = rightmost(filler, flen)
        elif just == 'r':
            lfill = leftmost(filler, flen)
            rfill = ''
        elif just == 'c':
            halff = flen // 2
            lfill = leftmost(filler, halff)
            rfill = rightmost(filler, flen - halff)
        else:
            lfill = ''
            rfill = rightmost(filler, flen)
    return lfill + result + rfill

def test():
    print(layout_field('l', '--', 10, 'abc', '*'))
    print(layout_field('l', '--', 5, 'abcdefg'))
    print(layout_field('l', '--', 5, 'abcdefg', '*'))
    print(layout_field('l', '--', 5, 'abcdefg', '...'))
    print(layout_field('c', '.', 10, 'abc'))
    print(layout_field('c', '.', 11, 'abc'))
    print(layout_field('c', '.', 10, 'abcd'))
    print(layout_field('c', '.', 11, 'abcd'))
    print(layout_field('c', '.', 5, 'abcdefg'))
    print(layout_field('c', '.', 5, 'abcdefg', '*'))
    print(layout_field('c', '.', 5, 'abcdefg', '__'))
    print(layout_field('c', '.', 5, 'abcdefg', '123'))
    print(layout_field('r', '.', 5, 'abcdefg'))
    print(layout_field('r', '.', 5, 'abcdefg', '*'))
    print(layout_field('r', '.', 10, 'abcdefg'))
    print(layout_field('e', '.', 5, 'abcdefg'))
    print(layout_field('e', '.', 5, 'abcdefg', '*'))
    print(layout_field('e', '.', 6, 'abcdefg', '*'))
    print(layout_field('e', '.', 10, 'abcdefg'))

    print(layout_field('l', '.', 0, 'abcdef'))

    c = Config()
    c.add_field('fld1')
    c.add_field('fld2', maxw = 3, hj = 'r', hs = '|', rf = '0')
    c.add_field(['fld3', 'cont'], df = '+=', hj = 'r', hs = '')
    c.add_field('fld4', maxw = 0)
    r = layout(c, [['tom', '0', 'one', 'hidden'], ['dick', '1', 'two', ''],
        ['harry', '1234', 'three', 'boo']])
    print('\n'.join(r))
    print(repr(r))


if __name__ == '__main__':
    import sys
    sys.exit(test())

# vi:ts=4:sw=4:expandtab
