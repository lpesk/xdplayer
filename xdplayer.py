#!/usr/bin/env python3

import sys
import textwrap
import string
import curses
from collections import namedtuple, defaultdict

UNFILLED = '.'

def getkeystroke(scr):
    k = scr.get_wch()
    if isinstance(k, str):
        if ord(k) >= 32 and ord(k) != 127:  # 127 == DEL or ^?
            return k
        k = ord(k)
    return curses.keyname(k).decode('utf-8')

class ColorMaker:
    def __init__(self):
        self.attrs = {}
        self.color_attrs = {}

        default_bg = curses.COLOR_BLACK

        self.color_attrs['black'] = curses.color_pair(0)

        for c in range(0, 256 or curses.COLORS):
            try:
                curses.init_pair(c+1, c, default_bg)
                self.color_attrs[str(c)] = curses.color_pair(c+1)
            except curses.error as e:
                pass # curses.init_pair gives a curses error on Windows

        for c in 'red green yellow blue magenta cyan white'.split():
            colornum = getattr(curses, 'COLOR_' + c.upper())
            self.color_attrs[c] = curses.color_pair(colornum+1)

        for a in 'normal blink bold dim reverse standout underline'.split():
            self.attrs[a] = getattr(curses, 'A_' + a.upper())

    def __getitem__(self, colornamestr):
        return self._colornames_to_cattr(colornamestr)

    def __getattr__(self, colornamestr):
        return self._colornames_to_cattr(optname).attr

    def _colornames_to_cattr(self, colornamestr):
        color, attr = 0, 0
        for colorname in colornamestr.split(' '):
            if colorname in self.color_attrs:
                if not color:
                    color = self.color_attrs[colorname.lower()]
            elif colorname in self.attrs:
                attr = self.attrs[colorname.lower()]
        return attr | color


class AttrDict(dict):
    'Augment a dict with more convenient .attr syntax.  not-present keys return None.'
    def __init__(self, **kwargs):
        kw = {}
        for k, v in kwargs.items():
            if isinstance(v, list):
                pass
            elif isinstance(v, str):
                v = list(v)
                if ' ' not in v:
                    v.append(' ')
            elif isinstance(v, bool):
                v = [v, not v]
            elif isinstance(v, int):
                v = [v, 0]
            else:
                v = [v]

            assert isinstance(v, list)
            kw[k] = v
        dict.__init__(self, **kw)

    def __getattr__(self, k):
        try:
            v = self[k][0]
            if k.endswith('attr'):
                v = colors[v]
            return v
        except KeyError:
            if k.startswith("__"):
                raise AttributeError

            return None

    def __dir__(self):
        return self.keys()

    def cycle(self, k):
        self[k] = self[k][1:] + [self[k][0]]

BoardClue = namedtuple('BoardClue', 'dir num clue answer coords')

class Crossword:
    def __init__(self, fn):
        self.fn = fn
        contents = open(fn).read()
        metastr, gridstr, cluestr, *notestr = contents.split('\n\n\n')

        self.meta = {}
        for line in metastr.splitlines():
            k, v = line.split(':', maxsplit=1)
            self.meta[k.strip()] = v.strip()

        self.filldir = 'A'
        self.solution = gridstr.splitlines()

        self.clear()
        self.grid = [[x for x in row] for row in self.solution]

        self.clues = {}  # 'A1' -> Clue
        for clue in cluestr.splitlines():
            if clue:
                if ' ~ ' in clue:
                    clue, answer = clue.split(' ~ ')
                else:
                    answer = ''
                dirnum, clue = clue.split('. ', maxsplit=1)
                dir, num = dirnum[0], int(dirnum[1:])
                self.clues[dirnum] = BoardClue(dir, num, clue, answer, [])  # final is board positions, filled in below

        self.cursor_x = 0
        self.cursor_y = 0
        self.clue_layout = {}

        self.move_grid(3, len(self.meta))

        self.options = AttrDict(
            rowattr = ['', 'underline'],
#            curattr = ['reverse 183'],
            curacrattr = ['210'],
            curdownattr = ['74'],
            helpattr = ['bold 69'],
            clueattr = ['7'],

            topch = '▁_',
            topattr = ['', 'underline'],
            botch = '▇⎴',
            botattr = ['reverse'],
            midblankch = '█',
            leftblankch = '▌',
            rightblankch = '▐',
            rightch = '▎▌│',
            leftch = '▊▐│',
            vline = '│┃|┆┇┊┋',
            inside_vline = ' │|┆┃┆┇┊┋',
            leftattr = ['', 'reverse'],
            unsolved_char = '· .?□_▁-˙∙•╺‧',
            dirarrow = '→↪⇢⇨',

            ulch = ' ▗',
            urch = ' ▖',
            blch = ' ▝',
            brch = ' ▘',
            solved = False,
            hotkeys= False,
        )

        self.pos = defaultdict(list)  # (y,x) -> [(dir, num, answer), ...] associated words with that cell
        for dir, num, answer, r, c in self.iteranswers_full():
            for i in range(len(answer)):
                w = self.clues[f'{dir}{num}']
                coord = (r,c+i) if dir == 'A' else (r+i,c)
                self.pos[coord].append(w)
                w[-1].append(coord)

    def move_grid(self, x, y):
        global grid_bottom, grid_right, grid_top, grid_left
        global clue_left, clue_top
        grid_left = x
        grid_top = y
        grid_bottom = grid_top + self.nrows
        grid_right = grid_left + self.ncols*2
        clue_left = grid_right+3
        clue_top = grid_top

    def clear(self):
        self.grid = [['#' if x == '#' else UNFILLED for x in row] for row in self.solution]

    @property
    def acr_clues(self):
        return {k:v for k, v in self.clues.items() if k[0] == 'A'}

    @property
    def down_clues(self):
        return {k:v for k, v in self.clues.items() if k[0] == 'D'}

    @property
    def nrows(self):
        return len(self.grid)

    @property
    def ncols(self):
        return len(self.grid[0])

    @property
    def ncells(self):
        return len([c for r in self.grid for c in r if c != '#'])

    @property
    def nsolved(self):
        return len([c for r in self.grid for c in r if c not in '.#'])

    def cell(self, r, c):
        if r < 0 or c < 0 or r >= self.nrows or c >= self.ncols:
            return '#'
        return self.solution[r][c]

    def iteranswers_full(self):
        'Generate ("A" or "D", clue_num, answer, r, c) for each word in the grid.'

        NON_ANSWER_CHARS = '_#'
        clue_num = 1
        for r, row in enumerate(self.solution):
            for c, cell in enumerate(row):
                # compute number shown in box
                new_clue = False
                if self.cell(r, c - 1) in NON_ANSWER_CHARS:  # across clue start
                    ncells = 0
                    answer = ""
                    while self.cell(r, c + ncells) not in NON_ANSWER_CHARS:
                        cellval = self.cell(r, c + ncells)
                        answer += cellval
                        ncells += 1

                    if ncells > 1:
                        new_clue = True
                        yield "A", clue_num, answer, r, c

                if self.cell(r - 1, c) in NON_ANSWER_CHARS:  # down clue start
                    ncells = 0
                    answer = ""
                    while self.cell(r + ncells, c) not in NON_ANSWER_CHARS:
                        cellval = self.cell(r + ncells, c)
                        answer += cellval
                        ncells += 1

                    if ncells > 1:
                        new_clue = True
                        yield "D", clue_num, answer, r, c

                if new_clue:
                    clue_num += 1

    def draw(self, scr):
        h, w = scr.getmaxyx()
        # draw meta
        y = 0
        for k, v in self.meta.items():
            if y >= h-self.nrows-2:
                break
            scr.addstr(y, 1, '%6s: %s' % (k, v))
            y += 1

        self.move_grid(3, max(0, min(h-self.nrows-2, y+1)))

        # draw grid
        d = self.options
        cursor_words = self.pos[(self.cursor_y, self.cursor_x)]
        if cursor_words:
            cursor_across, cursor_down = sorted(cursor_words)
        else:
            cursor_across, cursor_down = None, None

        for y, row in enumerate(self.grid):
            for x, ch in enumerate(row):
                attr = d.rowattr
                attr2 = d.rowattr

                if ch == '#':
                    ch = d.midblankch
                    ch2 = d.midblankch if x < len(row)-1 and row[x+1] == '#' else d.leftblankch
                else:
                    if d.solved:
                        ch = self.solution[y][x]
                    else:
                        ch = self.grid[y][x]
                        if ch == UNFILLED: ch = d.unsolved_char

                    ch2 = d.inside_vline

                    words = self.pos[(y,x)]
                    across_word, down_word = sorted(words)
                    if cursor_across == across_word and cursor_down == down_word:
                        attr = attr2 = (d.curacrattr if self.filldir == 'A' else d.curdownattr) | curses.A_REVERSE
                    elif cursor_across == across_word:
                        attr = attr2 = d.curacrattr | curses.A_REVERSE
                    elif cursor_down == down_word:
                        attr = attr2 = d.curdownattr | curses.A_REVERSE

                if scr:
                    scr.addstr(grid_top+y, grid_left+x*2, ch, attr)
                    scr.addstr(grid_top+y, grid_left+x*2+1, ch2, attr2)

                if x == 0:
                    if ch == '#' or cursor_down == down_word:
                        ch = d.leftblankch
                    else:
                        ch = d.vline
                    scr.addstr(grid_top+y, grid_left-1, ch, attr)

                if x == len(row)-1:
                    if ch == '#' or cursor_down == down_word:
                        ch = d.rightblankch
                    else:
                        ch = d.vline
                    scr.addstr(grid_top+y, grid_right-1, ch, attr)


        if scr:
            scr.addstr(grid_top-1, grid_left, d.topch*(self.ncols*2-1), d.topattr)
            scr.addstr(grid_bottom,grid_left, d.botch*(self.ncols*2-1), d.rowattr | d.botattr)

            scr.addstr(grid_top-1, grid_left-1, d.ulch)
            scr.addstr(grid_bottom,grid_left-1, d.blch)
            scr.addstr(grid_top-1, grid_right-1, d.urch)
            scr.addstr(grid_bottom,grid_right-1, d.brch)

            scr.move(0,0)

        def draw_clues(d, clue_top, clues, cursor_clue, n):
            'Draw clues around cursor in one direction.'
            dirnums = list(clues.values())
            i = dirnums.index(cursor_clue)
            y=0
            for clue in dirnums[max(i-2,0):]:
                if y >= n:
                    break
                dir, num, cluestr, answer, positions = clue
                if cursor_clue == clue:
                    attr = (d.curacrattr if dir == 'A' else d.curdownattr) | curses.A_REVERSE
                    if self.filldir == dir:
                        scr.addstr(clue_top+y, clue_left-2, f'{d.dirarrow} ', (d.curacrattr if dir == 'A' else d.curdownattr))
                else:
                    attr = d.clueattr

                dirnum = f'{dir}{num}'
                guess = ''.join([self.grid[r][c] for r, c in self.clues[dirnum][-1]])
                self.clue_layout[dirnum] = y
                dnw = len(dirnum)+2
                maxw = min(w-clue_left-dnw-1, 40)
                cluestr += f' [{guess}]'
                for j, line in enumerate(textwrap.wrap(cluestr, width=maxw)):
                    prefix = f'{dirnum}. ' if j == 0 else ' '*dnw
                    line = prefix + line + ' '*(maxw-len(line))
                    self.clue_layout[clue_top+y] = clue
                    scr.addstr(clue_top+y, clue_left, line, attr)
                    y += 1

        clueh = self.nrows//2-1
        draw_clues(d, clue_top, self.acr_clues, cursor_across, clueh)
        draw_clues(d, clue_top+clueh+2, self.down_clues, cursor_down, clueh)

    def draw_hotkeys(self, scr):
        self.hotkeys = {}
        h, w = scr.getmaxyx()
        for i, (k, v) in enumerate(self.options.items()):
            key = "0123456789abcdefghijklmnopqrstuvwxyz"[i]
            self.hotkeys[key] = k

            y = grid_top+self.nrows+i+1
            if y < h-1:
                scr.addstr(y, 3, key)
                scr.addstr(y, 5, k)
                scr.addstr(y, 15, ' '.join(map(str, v)))

    def cursorDown(self, n):
        i = n
        while self.cell(self.cursor_y+i, self.cursor_x) == '#' and self.cursor_y+i >= 0 and self.cursor_y+i < self.nrows-1:
            i += n
        if self.cell(self.cursor_y+i, self.cursor_x) == '#' or self.cursor_y+i < 0 or self.cursor_y+i >= self.nrows:
            return
        self.cursor_y += i

    def cursorRight(self, n):
        i = n
        while self.cell(self.cursor_y, self.cursor_x+i) == '#' and self.cursor_x+i >= 0 and self.cursor_x+i < self.ncols:
            i += n
        if self.cell(self.cursor_y, self.cursor_x+i) == '#' or self.cursor_x+i < 0 or self.cursor_x+i >= self.ncols:
            return
        self.cursor_x += i

    def cursorMove(self, n):
        if self.filldir == 'A':
            self.cursorRight(n)
        else:
            self.cursorDown(n)

    def save(self, fn):
        with open(fn, 'w') as fp:
            for y, (k, v) in enumerate(self.meta.items()):
                fp.write('%s: %s\n' % (k,v))
            fp.write('\n\n')

            for y, line in enumerate(self.grid):
                fp.write(''.join(line)+'\n')
            fp.write('\n\n')

            for clue in self.acr_clues.values():
                dir, num, cluestr, answer, positions = clue
                fp.write(f'{dir}{num}. {cluestr}\n')
            fp.write('\n')

            for clue in self.down_clues.values():
                dir, num, cluestr, answer, positions = clue
                fp.write(f'{dir}{num}. {cluestr}\n')


class CrosswordPlayer:
    def __init__(self):
        self.statuses = []
        self.xd = None
        self.n = 0

    def status(self, s):
        self.statuses.append(s)

    def play_one(self, scr, xd):
        h, w = scr.getmaxyx()
        opt = xd.options
        xd.draw(scr)
        if self.statuses:
            scr.addstr(h-2, clue_left, self.statuses.pop())

        # draw helpstr
        scr.addstr(h-1, 0, " Arrows move | Tab toggle direction | Ctrl+S save | Ctrl+Q quit | Ctrl+R reset", opt.helpattr)

        if opt.hotkeys:
            xd.draw_hotkeys(scr)
            scr.addstr(1, w-20, f'{h}x{w}')
        k = getkeystroke(scr)
        if k == '^Q': return True
        if k == 'KEY_RESIZE': h, w = scr.getmaxyx()
        if k == '^L': scr.clear()

        scr.erase()
        if opt.hotkeys:
            scr.addstr(0, w-20, k)
            scr.addstr(0, w-5, str(self.n))
        self.n += 1

        if k == 'KEY_MOUSE':
            devid, x, y, z, bstate = curses.getmouse()
            if grid_top <= y < grid_bottom and grid_left <= x < grid_right:
                x = (x-grid_left)//2
                y = y-grid_top
                if xd.grid[y][x] != '#':
                    xd.cursor_x = x
                    xd.cursor_y = y
            elif y in xd.clue_layout:
                xd.cursor_y, xd.cursor_x = xd.clue_layout[y][-1][0]
            else:
                self.status(f'{bstate}({y},{x})')

        elif k == 'KEY_DOWN': xd.cursorDown(+1)
        elif k == 'KEY_UP': xd.cursorDown(-1)
        elif k == 'KEY_LEFT': xd.cursorRight(-1)
        elif k == 'KEY_RIGHT': xd.cursorRight(+1)
        elif k == '^I': xd.filldir = 'A' if xd.filldir == 'D' else 'D'
        elif k == '^R': xd.clear()
        elif k == '^X':
            opt.hotkeys = not opt.hotkeys
            return

        elif k == 'KEY_BACKSPACE':  # back up and erase
            xd.cursorMove(-1)
            xd.grid[xd.cursor_y][xd.cursor_x] = UNFILLED
        elif k == ' ':  # erase and advance
            xd.grid[xd.cursor_y][xd.cursor_x] = UNFILLED
            xd.cursorMove(+1)
        elif k == 'KEY_DC':  # erase in place
            xd.grid[xd.cursor_y][xd.cursor_x] = UNFILLED
        elif k == '^S':
            xd.save(xd.fn)
            self.status('saved (%d%% solved)' % (xd.nsolved*100/xd.ncells))
        elif opt.hotkeys and k in xd.hotkeys:
            opt.cycle(xd.hotkeys[k])
        elif k.upper() in string.ascii_uppercase:
            xd.grid[xd.cursor_y][xd.cursor_x] = k.upper()
            xd.cursorMove(+1)



def main(scr):
    global colors

    curses.use_default_colors()
    curses.raw()
    curses.meta(1)
    curses.curs_set(0)
    curses.mousemask(-1)

    colors = ColorMaker()

    plyr = CrosswordPlayer()
    xd = Crossword(sys.argv[1])
    while not plyr.play_one(scr, xd):
        pass

if '--clear' == sys.argv[1]:
    for fn in sys.argv[2:]:
        xd = Crossword(fn)
        xd.clear()
        xd.save(fn)
else:
    curses.wrapper(main)
