#!/usr/bin/env python

'''
Python 2/3 curses epub reader.

Keyboard commands:
    Esc/q          - quit
    Tab/Left/Right - toggle between TOC and chapter views
    TOC view:
        Up         - up a line
        Down       - down a line
        PgUp       - up a page
        PgDown     - down a page
        Home       - first page
        End        - last page
        [0-9]      - go to chapter
        i          - open images on page in web browser
        e          - open source files with vim
        h          - show help
    Chapter view:
        PgUp       - up a page
        PgDown     - down a page
        Up         - up a line
        Down       - down a line
        Home       - first page
        End        - last page
'''

import os, sys, tempfile, mimetypes

PY3 = sys.version_info >= (3,0)
if PY3:
    from html.parser import HTMLParser
    import curses, curses.ascii
else:
    from HTMLParser import HTMLParser
    import curses.wrapper, curses.ascii
    import locale

    locale.setlocale(locale.LC_ALL, 'en_US.utf-8')

from zipfile import ZipFile
from textwrap import wrap

class Tag():
    def __init__(self, name, attrs=None, text='', tags=None):
        self.name  = name
        self.attrs = attrs or dict()
        self._text = text
        self.tags  = tags or []

    def append(self, tag):
        self.tags.append(tag)

    def __repr__(self):
        return "< {0}: {1} [{2}]>{3}</>".format(self.name,
                                                repr(self.attrs),
                                                self._text,
                                                str([repr(t) for t in self.tags]))

    def find(self, tag):
        if self.name == tag:
            return self
        else:
            for d in self.tags:
                v = d.find(tag)
                if v is not None:
                    return v
        return None

    def find_all(self, tag, r=None):
        if r is None:
            r = []
        r = []
        if self.name == tag:
            r.append(self)

        for d in self.tags:
            r += d.find_all(tag)

        return r

    @property
    def text(self):
        t = self._text
        for v in self.tags:
            t += v.text
        if self.name in ['p', 'h1', 'h2', 'h3']:
            t += '\n'
        return t

class MyParser(HTMLParser):
    def __init__(self):
        HTMLParser.__init__(self)
        self.clean()

    def handle_starttag(self, tag, attrs):
        if len(self.cur_tag) == 0:
            self.cur_tag.append(self.DATA)

        t = Tag(tag, attrs=dict(attrs))
        self.cur_tag[-1].append(t)

        self.cur_tag.append(t)

    def handle_endtag(self, tag):
        if len(self.cur_tag) > 0:
            self.cur_tag.pop()

    def handle_data(self, data):
        if len(self.cur_tag) > 0:
            self.cur_tag[-1].append(Tag(None, text=data.strip()))

    def get_data(self):
        return self.DATA

    def clean(self):
        self.DATA    = Tag('root')
        self.cur_tag = []

    def find(self, tag):
        return self.DATA.find(tag)

    def find_all(self, tag):
        return self.DATA.find_all(tag)

class Epub():
    def __init__(self, fl, info=True, maxcol=float("+inf"), help=None):
        if self.check_epub(fl):
            self.fl = ZipFile(fl, 'r')
        else:
            # FIXME
            # Throw exception
            return

        self.help   = help
        self.maxcol = maxcol
        if info:
            self.info = 2
        else:
            self.info = 0
        self.chaps  = self.table_of_contents()

        self.basedir = None
        self.parser  = None

    def check_epub(self, fl):
        return os.path.isfile(fl) and \
               mimetypes.guess_type(fl)[0] == 'application/epub+zip'

    def table_of_contents(self):
        r = []
        p = MyParser()
        p.feed(self.fl.read('META-INF/container.xml').decode('utf-8'))

        opf = p.find('rootfile').attrs['full-path']
        # Clean it up for reuse
        p.clean()

        self.basedir = os.path.dirname(opf)
        if self.basedir:
            self.basedir = '{0}/'.format(self.basedir)

        # Title
        p.feed(self.fl.read(opf).decode('utf-8'))
        r.append((p.find('dc:title').text, None))

        # All files, not in order
        x, ncx = {}, None
        toc_type = None
        for item in p.find('manifest').find_all('item'):
            x[item.attrs['id']] = '{0}{1}'.format(self.basedir, item.attrs['href'])

            if 'properties' in item.attrs and item.attrs['properties'] == 'nav':
                toc_type = 3
                ncx = '{0}{1}'.format(self.basedir, item.attrs['href'])
                basedir = os.path.dirname(ncx)
                if basedir:
                    self.basedir = '{0}/'.format(basedir)
            elif item.attrs['media-type'] == 'application/x-dtbncx+xml':
                toc_type = 0
                ncx = '{0}{1}'.format(self.basedir, item.attrs['href'])

        # Reading order, not all files
        if toc_type == 0:
            y = []
            for item in p.find('spine').find_all('itemref'):
                y.append(x[item.attrs['idref']])

        z = {}
        if ncx:
            # Get titles from the toc
            p.clean()
            p.feed(self.fl.read(ncx).decode('utf-8'))

            if toc_type == 0:
                for navp in p.find_all('navpoint'):
                    # Strip off any anchor text
                    k = navp.find('content').attrs['src']#.split('#')[0]

                    if k:
                        z['{0}{1}'.format(self.basedir,k)] = \
                                navp.find('navlabel').text
            elif toc_type == 3:
                y, z = [], {}
                for a in p.find('nav').find_all('a'):
                    href = '{0}{1}'.format(self.basedir, a.attrs['href'])
                    y.append(href)
                    z[href] = a.text

        p.clean()

        # Output
        for section in y:
            if section in z:
                if PY3:
                    r.append((z[section], section.split('#')[0]))
                else:
                    r.append((z[section].encode('utf-8'), section.split('#')[0]))
            else:
                r.append((u'', section.split('#')[0]))

        return r

    def textify(self, html):
        # FIXME
        # Deal with images
        if not PY3:
            html = html.encode('utf-8')
        rows = ['\n'.join(wrap(v, self.maxcol)) for v in html.splitlines()]
        return '\n\n'.join(rows)

    def dump(self):
        for title, src in self.chaps:
            print(title)
            #print('-' * len(title))

            if src:
                p = MyParser()
                p.feed(self.fl.read(src).decode('utf-8'))
                print(self.textify(p.find('body').text))
                print('\n')

    def curses(self):
        self.chaps_pos  = [0] * len(self.chaps)
        self.cursor_row = 0
        self.start      = 0

        self.cur_chap   = None
        self.cur_text   = None

        try:
            # Manually init curses, colors, etc
            self.screen = curses.initscr()
            curses.start_color()
            curses.noecho()
            curses.cbreak()
            self.screen.keypad(1)

            self.maxy, self.maxx = self.screen.getmaxyx()
            if self.maxcol is None or self.maxcol > self.maxx:
                self.maxcol = self.maxx

            self.curses_loop()
        except:
            pass
        finally:
            self.screen.keypad(0)
            curses.nocbreak()
            curses.echo()
            curses.endwin()
            print(sys.exc_info())

    def curses_loop(self):
        step = 0
        while True:
            if self.cur_chap:
                self.curses_chapter(step)
            else:
                self.curses_toc(step)

            ch = self.screen.getch()
            try:
                char = chr(ch)
            except (ValueError, IndexError):
                char = None

            # up/down line
            if ch == curses.KEY_DOWN or char == 'j':
                step = 1
            elif ch == curses.KEY_UP or char == 'k':
                step = -1
            # up/down page
            elif ch == curses.KEY_NPAGE or char == 'J':
                step = self.maxy - self.info
            elif ch == curses.KEY_PPAGE or char == 'K':
                step = -self.maxy + self.info
            # Position cursor in first chapter / go to first page
            elif ch == curses.KEY_HOME or char == 'H':
                step = -1000000
            # Position cursor in last chapter / go to last page
            elif ch == curses.KEY_END or char == 'L':
                step = 1000000
            # to chapter
            elif ch in [curses.ascii.HT, curses.KEY_RIGHT, curses.KEY_LEFT]:
                step = 0
                self.cur_text = None
                if self.cur_chap is None:
                    # Current chapter number
                    self.cur_chap = self.start + self.cursor_row
                else:
                    self.cur_chap = None
            # Help
            elif char == 'h':
                step = 0
                self.curses_help()
            # Quit
            elif ch == curses.ascii.ESC or char == 'q':
                return
            # edit html
            elif char == 'e':
                step = 0
                if self.cur_chap:
                    tmpfl = tempfile.NamedTemporaryFile(delete=False)
                    tmpfl.write(self.fl.read(self.chaps[self.cur_chap][1]))
                    tmpfl.close()

                    self.run('vim', tmpfl.name)

                    with open(tmpfl.name) as changed:
                        new_html = changed.read()
                        os.unlink(tmpfl.name)
                        if new_html != html:
                            pass
                            # write to zipfile?

    def curses_chapter(self, step=0):
        self.screen.clear()

        # Display chapter page
        if self.cur_text is None:
            chap = self.chaps[self.cur_chap][1]
            if chap:
                p = MyParser()
                p.feed(self.fl.read(chap).decode('utf-8'))
                self.cur_text = self.textify(p.find('body').text).split('\n')
            else:
                self.cur_text = ''

        pos_start = self.chaps_pos[self.cur_chap]

        pos_start += step
        pos_start = max(0, pos_start)
        pos_start = min(len(self.cur_text) - 1, pos_start)

        self.chaps_pos[self.cur_chap] = pos_start

        pos_end = pos_start + self.maxy - self.info

        # Current status info
        # Total number of lines
        n_lines = len(self.cur_text)
        if self.info:
            # Title
            title = self.chaps[self.cur_chap][0]
            # Total number of pages
            n_pages = n_lines / (self.maxy - self.info) + 1

            # Truncate title if too long. Add ellipsis at the end
            if len(title) > self.maxcol - 34:
                title = title[0:self.maxcol - 35] + u'\u2026'.encode('utf-8')
                spaces = ''
            else:
                spaces = ''.join([' '] * (self.maxcol - len(title) - 35))

        for i, line in enumerate(self.cur_text[pos_start:pos_end]):
            self.screen.addstr(i, 0, line)

        if self.info:
            # Current status info
            # Current (last) line number
            cur_line = self.chaps_pos[self.cur_chap]
            # Current page
            cur_page = cur_line / (self.maxy - self.info) + 1
            # Current position (%)
            cur_pos  = 100 * (float(cur_line) / n_lines)

            self.screen.addstr(self.maxy - 1, 0,
                               '%s (%3d/%3d) %s Page %3d/%3d (%5.1f%%)' % (
                                 title,
                                 self.cur_chap,
                                 len(self.chaps) - 1,
                                 spaces,
                                 cur_page,
                                 n_pages,
                                 cur_pos))
        self.screen.refresh()

    def curses_toc(self, step=0):
        self.screen.clear()
        # Display TOC
        # FIXME
        self.cursor_row += step
        if self.cursor_row >= self.maxy or self.cursor_row <= 0:
            self.start += step
            self.cursor_row -= step

        curses.curs_set(1)

        self.cursor_row = max(1, min(self.maxy,
                                     self.cursor_row,
                                     len(self.chaps) - 1))
        self.start = max(0, min(len(self.chaps) - self.maxy, self.start))

        for i, (title, src) in enumerate(self.chaps[self.start: \
                                                    self.start + self.maxy]):
            try:
                if self.start + i == 0:
                    self.screen.addstr(i, 0,
                            '      {0}'.format(title), curses.A_BOLD)
                else:
                    self.screen.addstr(i, 0,
                            '{0:-5} {1}'.format(self.start + i, title))
            except:
                pass

        self.screen.move(self.cursor_row, 0)
        self.screen.refresh()

    def curses_help(self):
        curses.curs_set(0)
        self.screen.clear()

        for i, line in enumerate(self.help.split('\n')):
            self.screen.addstr(i, 0, line)

        self.screen.refresh()
        # Wait for the user to press any key
        self.screen.getch()
        self.screen.clear()


    def run(self, program, *args):
        curses.nocbreak()
        self.screen.keypad(0)
        curses.echo()

        pid = os.fork()
        if not pid:
            os.execvp(program, (program,) +  args)

        os.wait()[0]
        curses.noecho()
        self.screen.keypad(1)
        curses.cbreak()

if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser(
        formatter_class = argparse.RawDescriptionHelpFormatter,
        description = __doc__,
    )
    parser.add_argument('-d', '--dump',
        action  = 'store_true',
        help    = 'dump EPUB to text')
    parser.add_argument('-c', '--cols',
        action  = 'store',
        type    = int,
        default = float("+inf"),
        help    = 'Number of columns to wrap; default is no wrapping.')
    parser.add_argument('-I', '--no-info',
        action  = 'store_true',
        default = False,
        help    = 'Do not display chapter/page info. Defaults to false.')
    parser.add_argument('EPUB', help='view EPUB')

    args = parser.parse_args()
    if args.EPUB:
        epub = Epub(args.EPUB,
                    help=parser.format_help(),
                    info=not args.no_info,
                    maxcol=args.cols)
        if args.dump:
            epub.dump()
        else:
            try:
                epub.curses()
            except KeyboardInterrupt:
                pass
