
import ctypes
import os
import queue
import sys
import threading
import time
import tkinter as tk
from pathlib import Path

import cv2
import keyboard
import mss
import numpy as np

cv2.setNumThreads(1)

ROOT = Path(__file__).resolve().parent
REF_PATH = ROOT / "blackflag_board_reference.png"
REF = cv2.imread(str(REF_PATH)) if REF_PATH.is_file() else None

RX, RY, PITCH = 52.0, 53.0, 105.5
PATCH = 26
ANCHORS = ((3, 3), (4, 4), (2, 2), (5, 5), (1, 1), (6, 6))
SCALES = (
    .44, .50, .56, .62, .68, .74, .80, .86,
    .92, 1., 1.08, 1.16, 1.26, 1.38, 1.52, 1.70
)

REFERENCE = []

if REF is not None:
    gray = cv2.cvtColor(REF, cv2.COLOR_BGR2GRAY)

    for row, col in ANCHORS:
        x = round(RX + col * PITCH)
        y = round(RY + row * PITCH)

        REFERENCE.append(
            gray[
                y-PATCH:y+PATCH+1,
                x-PATCH:x+PATCH+1
            ].copy()
        )

if os.name == "nt":
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except (AttributeError, OSError):
        ctypes.windll.user32.SetProcessDPIAware()

    user32 = ctypes.windll.user32

    class POINT(ctypes.Structure):
        _fields_ = [
            ("x", ctypes.c_long),
            ("y", ctypes.c_long)
        ]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [
            ("dx", ctypes.c_long),
            ("dy", ctypes.c_long),
            ("data", ctypes.c_ulong),
            ("flags", ctypes.c_ulong),
            ("time", ctypes.c_ulong),
            ("extra", ctypes.c_size_t)
        ]

    class INPUTUNION(ctypes.Union):
        _fields_ = [
            ("mouse", MOUSEINPUT)
        ]

    class INPUT(ctypes.Structure):
        _anonymous_ = ("data",)

        _fields_ = [
            ("type", ctypes.c_ulong),
            ("data", INPUTUNION)
        ]

    user32.SendInput.argtypes = (
        ctypes.c_uint,
        ctypes.POINTER(INPUT),
        ctypes.c_int
    )

    user32.SendInput.restype = ctypes.c_uint

running = threading.Event()
enabled = threading.Event()
scan_now = threading.Event()
first_override = threading.Event()

messages = queue.Queue()
highlights = queue.Queue()
local = threading.local()

last_location = None
last_monitor = None
next_search = 0.0
session = None


def log(message, kind="INFO"):
    messages.put((kind, message))
    print(f"[{kind}] {message}", flush=True)


def capture_context():
    if not hasattr(local, "capture"):
        local.capture = mss.mss()

    return local.capture


def shot(monitor_id):
    sct = capture_context()
    monitor = sct.monitors[monitor_id]

    image = np.asarray(
        sct.grab(monitor)
    )[:, :, :3].copy()

    return image, monitor


def match(image, template, area=None):
    if area is None:
        x0 = y0 = 0
        view = image
    else:
        x0, y0, x1, y1 = area
        view = image[y0:y1, x0:x1]

    if (
        view.shape[0] < template.shape[0]
        or view.shape[1] < template.shape[1]
    ):
        return None

    response = cv2.matchTemplate(
        view,
        template,
        cv2.TM_CCOEFF_NORMED
    )

    _, strength, _, (x, y) = cv2.minMaxLoc(response)

    return float(strength), (x+x0, y+y0)


def verify_anchors(gray, location):
    ox, oy, scale = location
    scores = []
    origins = []
    h, w = gray.shape

    for (r, c), patch in zip(ANCHORS, REFERENCE):
        template = cv2.resize(
            patch,
            None,
            fx=scale,
            fy=scale,
            interpolation=cv2.INTER_AREA
        )

        rx = RX + PITCH*c-PATCH
        ry = RY + PITCH*r-PATCH

        expected_x = ox + rx*scale
        expected_y = oy + ry*scale

        gap = max(7, int(16*scale))

        bounds = (
            max(0, round(expected_x-gap)),
            max(0, round(expected_y-gap)),
            min(w, round(expected_x+template.shape[1]+gap)),
            min(h, round(expected_y+template.shape[0]+gap))
        )

        result = match(gray, template, bounds)

        if result is None:
            return None

        score, (x, y) = result

        scores.append(score)
        origins.append((x-rx*scale, y-ry*scale))

    spread = np.std(origins, axis=0)

    if (
        min(scores) < .47
        or np.median(scores) < .65
        or max(spread) > max(5, 7*scale)
    ):
        return None

    ox, oy = np.median(origins, axis=0)

    return (
        (float(ox), float(oy), float(scale)),
        float(np.mean(scores))
    )


def texture_location(frame):
    if not REFERENCE:
        return None

    gray = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2GRAY
    )

    half = cv2.resize(
        gray,
        None,
        fx=.5,
        fy=.5,
        interpolation=cv2.INTER_AREA
    )

    r, c = ANCHORS[0]
    rx = RX+PITCH*c-PATCH
    ry = RY+PITCH*r-PATCH

    possible = []

    for scale in SCALES:
        template = cv2.resize(
            REFERENCE[0],
            None,
            fx=scale*.5,
            fy=scale*.5,
            interpolation=cv2.INTER_AREA
        )

        if min(template.shape) < 8:
            continue

        scores = cv2.matchTemplate(
            half,
            template,
            cv2.TM_CCOEFF_NORMED
        )

        for _ in range(6):
            _, value, _, (x, y) = cv2.minMaxLoc(scores)

            if value < .34:
                break

            possible.append((
                value,
                2*x-rx*scale,
                2*y-ry*scale,
                scale
            ))

            scores[
                max(0, y-15):y+16,
                max(0, x-15):x+16
            ] = -1

    possible.sort(reverse=True)
    best = None

    for _, ox, oy, scale in possible[:65]:
        checked = verify_anchors(
            gray,
            (ox, oy, scale)
        )

        if checked is not None:
            if best is None or checked[1] > best[1]:
                best = checked

                if checked[1] > .95:
                    break

    return best


def checker_strength(gray, location):
    ox, oy, scale = location
    bright = []
    dark = []

    points = (
        (3, 3),
        (4, 4),
        (4, 6),
        (3, 4),
        (4, 3),
        (3, 5)
    )

    for r, c in points:
        x = round(ox + (RX+c*PITCH)*scale)
        y = round(oy + (RY+r*PITCH)*scale)

        if (
            x < 5
            or y < 5
            or y+5 >= gray.shape[0]
            or x+5 >= gray.shape[1]
        ):
            return 0

        value = float(
            np.median(
                gray[y-4:y+5, x-4:x+5]
            )
        )

        if (r+c) % 2:
            bright.append(value)
        else:
            dark.append(value)

    return float(
        np.median(bright) - np.median(dark)
    )


def geometry_location(frame):
    h, w = frame.shape[:2]

    half = cv2.resize(
        frame,
        (w//2, h//2),
        interpolation=cv2.INTER_AREA
    )

    sat = cv2.cvtColor(
        half,
        cv2.COLOR_BGR2HSV
    )[:, :, 1]

    gray = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2GRAY
    )

    possibilities = []

    for threshold in (175, 155):
        binary = np.uint8(sat > threshold)*255

        binary = cv2.morphologyEx(
            binary,
            cv2.MORPH_CLOSE,
            np.ones((17, 17), np.uint8)
        )

        contours, _ = cv2.findContours(
            binary,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )

        for contour in contours:
            x, y, cw, ch = cv2.boundingRect(contour)

            if (
                cw < 115
                or ch < 115
                or not .80 < cw/ch < 1.33
                or cw*ch < .02*half.shape[0]*half.shape[1]
            ):
                continue

            fill = cv2.contourArea(contour)/(cw*ch)

            if fill < .70:
                continue

            X = 2*x
            Y = 2*y
            W = 2*cw

            location = (
                X+W*.10,
                Y+W*.05,
                W/(848*1.23)
            )

            contrast = checker_strength(
                gray,
                location
            )

            if contrast < 16:
                continue

            score = max(
                0.,
                min(.9, .6+contrast/350)
            )

            possibilities.append(
                (score, location)
            )

    possibilities.sort(
        reverse=True,
        key=lambda value: value[0]
    )

    if not possibilities:
        return None

    score, location = possibilities[0]

    if REFERENCE:
        for _, proposal in possibilities[:4]:
            verified = verify_anchors(
                gray,
                proposal
            )

            if verified:
                return verified

    return location, score


def locate(frame, monitor_id, allow_full):
    global last_location
    global last_monitor

    if (
        last_location is not None
        and last_monitor == monitor_id
    ):
        gray = cv2.cvtColor(
            frame,
            cv2.COLOR_BGR2GRAY
        )

        old = (
            verify_anchors(gray, last_location)
            if REFERENCE
            else None
        )

        if (
            old is None
            and checker_strength(gray, last_location) > 22
        ):
            old = last_location, .72

        if old is not None:
            last_location = old[0]
            return (*old, "tracking")

    if not allow_full:
        return None

    methods = (
        ("texture", texture_location),
        ("geometry", geometry_location)
    )

    for method, fn in methods:
        result = fn(frame)

        if result is not None:
            last_location = result[0]
            last_monitor = monitor_id

            return (*result, method)

    return None


def locate_screen(force=False, debug=False):
    global next_search

    sct = capture_context()
    monitors = list(range(1, len(sct.monitors)))

    if last_monitor in monitors:
        monitors.remove(last_monitor)
        monitors.insert(0, last_monitor)

    scan_full = (
        force
        or time.monotonic() >= next_search
    )

    for display in monitors:
        frame, mon = shot(display)

        result = locate(
            frame,
            display,
            scan_full
        )

        if result is not None:
            loc, score, method = result

            if debug:
                log(
                    f"Board found on monitor {display} "
                    f"using {method}, confidence {score:.3f}",
                    "SCAN"
                )

            return frame, mon, loc, score, method

    next_search = time.monotonic()+.9

    return None, None, None, 0., "not found"


def center(index, monitor, location):
    r, c = divmod(index, 8)
    ox, oy, scale = location

    return (
        round(
            monitor["left"]
            + ox
            + (RX+c*PITCH)*scale
        ),
        round(
            monitor["top"]
            + oy
            + (RY+r*PITCH)*scale
        )
    )


def detect_occupied(frame, monitor, location):
    lab = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2LAB
    )

    radius = max(
        8,
        round(PITCH*location[2]*.40)
    )

    yy, xx = np.ogrid[
        -radius:radius+1,
        -radius:radius+1
    ]

    distance = np.hypot(xx, yy)

    ring = (
        (distance > radius*.44)
        & (distance < radius*.91)
    )

    values = []
    squares = []

    for index in range(64):
        r, c = divmod(index, 8)

        if (r+c) % 2 == 0:
            continue

        x, y = center(
            index,
            monitor,
            location
        )

        x -= monitor["left"]
        y -= monitor["top"]

        if (
            x-radius < 0
            or y-radius < 0
            or x+radius >= lab.shape[1]
            or y+radius >= lab.shape[0]
        ):
            return None

        patch = lab[
            y-radius:y+radius+1,
            x-radius:x+radius+1,
            0
        ]

        values.append(
            float(
                np.percentile(
                    patch[ring],
                    5
                )
            )
        )

        squares.append(index)

    cv2.setRNGSeed(42)

    _, labels, means = cv2.kmeans(
        np.array(
            values,
            dtype="float32"
        ).reshape(-1, 1),
        3,
        None,
        (
            cv2.TERM_CRITERIA_EPS
            + cv2.TERM_CRITERIA_MAX_ITER,
            30,
            .15
        ),
        3,
        cv2.KMEANS_PP_CENTERS
    )

    ordered = {
        int(k): i
        for i, k in enumerate(
            np.argsort(means.ravel())
        )
    }

    candidates = [
        (values[i], squares[i])
        for i, lab in enumerate(labels.ravel())
        if ordered[int(lab)] != 2
    ]

    if len(candidates) > 24:
        candidates.sort()
        candidates = candidates[:24]

    result = [0]*64

    for _, index in candidates:
        result[index] = 1

    return tuple(result)


def snapshot(debug=False):
    try:
        frame, mon, loc, score, method = locate_screen(
            force=debug,
            debug=debug
        )

        if debug:
            if frame is None:
                sct = capture_context()

                for display in range(
                    1,
                    len(sct.monitors)
                ):
                    image, _ = shot(display)

                    outfile = (
                        ROOT
                        / f"checkers_debug_monitor_{display}.png"
                    )

                    cv2.imwrite(
                        str(outfile),
                        image
                    )

                    log(
                        f"Saved screen {display} to {outfile}",
                        "SCAN"
                    )

            else:
                outfile = ROOT / "checkers_debug.png"
                preview = frame.copy()

                if loc is not None:
                    ox, oy, scale = loc

                    x0 = round(ox)
                    y0 = round(oy)

                    x1 = round(
                        ox+8*PITCH*scale
                    )

                    y1 = round(
                        oy+8*PITCH*scale
                    )

                    cv2.rectangle(
                        preview,
                        (x0, y0),
                        (x1, y1),
                        (0, 255, 0),
                        3
                    )

                cv2.imwrite(
                    str(outfile),
                    preview
                )

                log(
                    f"Saved annotated screenshot to {outfile}",
                    "SCAN"
                )

        if loc is None:
            if debug:
                log(
                    "Board not found by texture or shape. "
                    "Screenshot saved for diagnosis.",
                    "SCAN"
                )

            return None, None, None, 0.

        board = detect_occupied(
            frame,
            mon,
            loc
        )

        if debug:
            count = sum(board) if board else 0

            log(
                f"Board alignment {score:.3f} using "
                f"{method}; {count} pieces detected",
                "SCAN"
            )

            if board:
                for r in range(8):
                    print(
                        " ".join(
                            "o" if board[8*r+c]
                            else "."
                            for c in range(8)
                        ),
                        flush=True
                    )

        return board, mon, loc, score

    except Exception as err:
        log(
            f"Screen-capture error: "
            f"{type(err).__name__}: {err}",
            "ERROR"
        )

        return None, None, None, 0.


def stable_snapshot():
    first = snapshot()

    if first[0] is None:
        return first

    time.sleep(.12)
    second = snapshot()

    if first[0] != second[0]:
        return (
            None,
            second[1],
            second[2],
            second[3]
        )

    return second


def start_position():
    return tuple(
        (
            -1 if r < 3
            else 1 if r > 4
            else 0
        )
        if (r+c) % 2
        else 0
        for r in range(8)
        for c in range(8)
    )


def dirs(piece):
    if abs(piece) == 2:
        return (
            (-1, -1),
            (-1, 1),
            (1, -1),
            (1, 1)
        )

    return (
        ((-1, -1), (-1, 1))
        if piece > 0
        else ((1, -1), (1, 1))
    )


def legal(board, side):
    captures = []
    regular = []

    def jumps(state, at, path):
        p = state[at]
        r, c = divmod(at, 8)
        possible = False

        for dr, dc in dirs(p):
            mr = r+dr
            mc = c+dc

            nr = r+2*dr
            nc = c+2*dc

            if not (
                0 <= mr < 8
                and 0 <= mc < 8
                and 0 <= nr < 8
                and 0 <= nc < 8
            ):
                continue

            mid = 8*mr+mc
            target = 8*nr+nc

            if (
                state[mid]*side >= 0
                or state[target]
            ):
                continue

            possible = True
            nxt = list(state)

            nxt[at] = 0
            nxt[mid] = 0
            nxt[target] = p

            more = path+(target,)

            if (
                abs(p) == 1
                and nr == (0 if side > 0 else 7)
            ):
                captures.append(more)
            else:
                jumps(
                    tuple(nxt),
                    target,
                    more
                )

        if (
            not possible
            and len(path) > 1
        ):
            captures.append(path)

    for i, p in enumerate(board):
        if p*side <= 0:
            continue

        jumps(board, i, (i,))

        r, c = divmod(i, 8)

        for dr, dc in dirs(p):
            nr = r+dr
            nc = c+dc

            if (
                0 <= nr < 8
                and 0 <= nc < 8
                and board[8*nr+nc] == 0
            ):
                regular.append(
                    (i, 8*nr+nc)
                )

    return captures if captures else regular


def moved(board, path):
    nxt = list(board)

    p = nxt[path[0]]
    nxt[path[0]] = 0

    for src, dst in zip(
        path,
        path[1:]
    ):
        r, c = divmod(src, 8)
        u, v = divmod(dst, 8)

        if abs(r-u) == 2:
            nxt[
                8*((r+u)//2)+(c+v)//2
            ] = 0

    if (
        abs(p) == 1
        and path[-1]//8 == (
            0 if p > 0 else 7
        )
    ):
        p *= 2

    nxt[path[-1]] = p

    return tuple(nxt)


def occupancy(board):
    return tuple(
        1 if value else 0
        for value in board
    )


def unique_transition(board, observed, side):
    found = [
        moved(board, m)
        for m in legal(board, side)
        if occupancy(moved(board, m)) == observed
    ]

    return (
        found[0]
        if len(found) == 1
        else None
    )


def score(board):
    total = 0

    for i, p in enumerate(board):
        if p:
            row, col = divmod(i, 8)

            val = (
                190
                if abs(p) == 2
                else 100+4*(
                    7-row if p > 0 else row
                )
            )

            total += (
                (1 if p > 0 else -1)
                * (
                    val
                    + 2*(3.5-abs(3.5-col))
                )
            )

    return total


def label(move):
    return " -> ".join(
        f"{i//8+1},{i%8+1}"
        for i in move
    )


def best_move(board, side=1, limit=.6):
    options = legal(board, side)

    if not options:
        return None

    deadline = time.monotonic()+limit

    ranked = sorted(
        options,
        key=lambda m: score(
            moved(board, m)
        ),
        reverse=side > 0
    )

    log(
        "Considering "
        + ", ".join(
            label(m)
            for m in ranked[:4]
        ),
        "THINKING"
    )

    chosen = ranked[0]

    class OutOfTime(Exception):
        pass

    def recurse(
        pos,
        side,
        depth,
        alpha,
        beta
    ):
        if time.monotonic() >= deadline:
            raise OutOfTime()

        moves = legal(pos, side)

        if not moves:
            return -100000*side

        if depth <= 0:
            return score(pos)

        if side > 0:
            val = -10**8

            for m in moves:
                val = max(
                    val,
                    recurse(
                        moved(pos, m),
                        -side,
                        depth-1,
                        alpha,
                        beta
                    )
                )

                alpha = max(alpha, val)

                if alpha >= beta:
                    break

        else:
            val = 10**8

            for m in moves:
                val = min(
                    val,
                    recurse(
                        moved(pos, m),
                        -side,
                        depth-1,
                        alpha,
                        beta
                    )
                )

                beta = min(beta, val)

                if alpha >= beta:
                    break

        return val

    for depth in range(1, 10):
        try:
            values = [
                (
                    recurse(
                        moved(board, m),
                        -side,
                        depth-1,
                        -10**8,
                        10**8
                    ),
                    m
                )
                for m in ranked
            ]

            chosen = (
                max(
                    values,
                    key=lambda x: x[0]
                )
                if side > 0
                else min(
                    values,
                    key=lambda x: x[0]
                )
            )[1]

        except OutOfTime:
            break

    log(
        "Selected "+label(chosen),
        "PLAN"
    )

    return chosen


def infer_midgame(frame, mon, loc, observed):
    if observed is None:
        return None

    lab = cv2.cvtColor(
        frame,
        cv2.COLOR_BGR2LAB
    )

    rad = max(
        7,
        round(PITCH*loc[2]*.23)
    )

    yy, xx = np.ogrid[
        -rad:rad+1,
        -rad:rad+1
    ]

    mask = (
        xx*xx+yy*yy
        < (rad*.80)**2
    )

    info = {}

    for i, present in enumerate(observed):
        if not present:
            continue

        x, y = center(i, mon, loc)

        x -= mon["left"]
        y -= mon["top"]

        if (
            x-rad < 0
            or y-rad < 0
            or x+rad >= lab.shape[1]
            or y+rad >= lab.shape[0]
        ):
            return None

        crop = lab[
            y-rad:y+rad+1,
            x-rad:x+rad+1
        ][mask]

        info[i] = np.concatenate((
            np.percentile(
                crop,
                25,
                axis=0
            ),
            np.median(
                crop,
                axis=0
            )
        ))

    top = [
        f for i, f in info.items()
        if i//8 < 2
    ]

    bottom = [
        f for i, f in info.items()
        if i//8 > 5
    ]

    if len(top) < 2 or len(bottom) < 2:
        return None

    a = np.median(top, axis=0)
    b = np.median(bottom, axis=0)

    gap = np.linalg.norm(a-b)

    if gap < 12:
        return None

    board = [0]*64

    for i, f in info.items():
        d1 = np.linalg.norm(f-a)
        d2 = np.linalg.norm(f-b)

        if abs(d1-d2) < gap*.12:
            return None

        board[i] = (
            -1 if d1 < d2
            else 1
        )

    if (
        sum(p > 0 for p in board) > 12
        or sum(p < 0 for p in board) > 12
    ):
        return None

    for i, p in enumerate(board):
        if (
            (p > 0 and i//8 == 0)
            or (p < 0 and i//8 == 7)
        ):
            board[i] *= 2

    return tuple(board)


def position():
    p = POINT()
    user32.GetCursorPos(ctypes.byref(p))

    return p.x, p.y


def mouse_event(flags, x=0, y=0):
    inp = INPUT(
        type=0,
        mouse=MOUSEINPUT(
            x, y, 0, flags, 0, 0
        )
    )

    if user32.SendInput(
        1,
        ctypes.byref(inp),
        ctypes.sizeof(inp)
    ) != 1:
        raise OSError(
            "Mouse SendInput failed"
        )


def click_at(x, y):
    left = user32.GetSystemMetrics(76)
    top = user32.GetSystemMetrics(77)

    width = user32.GetSystemMetrics(78)
    height = user32.GetSystemMetrics(79)

    if not (
        left <= x < left+width
        and top <= y < top+height
    ):
        raise OSError(
            "Target is outside the desktop"
        )

    mx = round(
        (x-left)*65535/max(1, width-1)
    )

    my = round(
        (y-top)*65535/max(1, height-1)
    )

    mouse_event(
        0x8001 | 0x4000,
        mx,
        my
    )

    time.sleep(.12)

    actual = position()

    if max(
        abs(actual[0]-x),
        abs(actual[1]-y)
    ) > 5:
        user32.SetCursorPos(x, y)
        time.sleep(.12)
        actual = position()

    if max(
        abs(actual[0]-x),
        abs(actual[1]-y)
    ) > 6:
        raise OSError(
            f"Cursor landed at {actual} "
            f"rather than {(x, y)}"
        )

    mouse_event(2)

    try:
        time.sleep(.12)
    finally:
        mouse_event(4)

    time.sleep(.13)


def play_move(path):
    for index in path:
        if not enabled.is_set():
            return False

        frame, mon, loc, value, _ = locate_screen(
            force=True
        )

        if loc is None or value < .65:
            raise RuntimeError(
                "Lost board before clicking"
            )

        x, y = center(
            index,
            mon,
            loc
        )

        log(
            f"Clicking {index//8+1},"
            f"{index%8+1} at ({x},{y})",
            "CLICKING"
        )

        click_at(x, y)

    return True


def confirm(expected, seconds=5):
    deadline = time.monotonic()+seconds

    while (
        time.monotonic() < deadline
        and enabled.is_set()
    ):
        seen, _, _, _ = stable_snapshot()

        if seen is not None:
            if seen == occupancy(expected):
                return expected, False

            reply = unique_transition(
                expected,
                seen,
                -1
            )

            if reply is not None:
                return reply, True

        time.sleep(.15)

    return None, False


def worker():
    global session

    log(
        "Paused. Switch to Black Flag "
        "and press Ctrl+H.",
        "READY"
    )

    last_status = None

    def announce(message, kind="WAITING"):
        nonlocal last_status

        if (message, kind) != last_status:
            last_status = (message, kind)
            log(message, kind)

    while not running.is_set():
        if scan_now.is_set():
            scan_now.clear()
            snapshot(debug=True)

        if not enabled.is_set():
            time.sleep(.09)
            continue

        seen, mon, loc, confidence = (
            stable_snapshot()
        )

        if loc is None:
            announce(
                "Searching for board. "
                "Press F8 to save a diagnostic screenshot.",
                "SEARCHING"
            )

            time.sleep(.3)
            continue

        if seen is None:
            announce(
                "Board found, waiting for "
                "the pieces to settle.",
                "SCANNING"
            )

            time.sleep(.2)
            continue

        now = time.monotonic()

        if session is None:
            start = start_position()

            if occupancy(start) == seen:
                session = {
                    "board": start,
                    "turn": None,
                    "start": now,
                    "opening": True
                }

                announce(
                    "Starting board recognized. "
                    "Waiting for the first move.",
                    "DETECTING"
                )

            else:
                first = unique_transition(
                    start,
                    seen,
                    -1
                )

                if first is not None:
                    session = {
                        "board": first,
                        "turn": "player",
                        "start": now
                    }

                    announce(
                        "Opponent moved first. Your turn.",
                        "YOUR TURN"
                    )

                else:
                    frame, mon = shot(last_monitor)

                    partial = infer_midgame(
                        frame,
                        mon,
                        loc,
                        seen
                    )

                    if partial is not None:
                        session = {
                            "board": partial,
                            "turn": None,
                            "start": now,
                            "midgame": True
                        }

                        announce(
                            "Midgame pieces recognized; "
                            "turn unknown.",
                            "DETECTING"
                        )

                    else:
                        announce(
                            "Cannot confidently reconstruct "
                            "this midgame yet.",
                            "UNCERTAIN"
                        )

            time.sleep(.14)
            continue

        current = session["board"]

        if occupancy(current) != seen:
            if session["turn"] in (
                None,
                "opponent"
            ):
                result = unique_transition(
                    current,
                    seen,
                    -1
                )

                if result is not None:
                    session = {
                        "board": result,
                        "turn": "player",
                        "start": now
                    }

                    announce(
                        "Opponent move confirmed.",
                        "YOUR TURN"
                    )

                    continue

            announce(
                "Waiting for a stable move "
                "or animation.",
                "ANIMATING"
            )

            time.sleep(.2)
            continue

        if session["turn"] is None:
            if first_override.is_set():
                first_override.clear()
                session["turn"] = "player"

            elif session.get("midgame"):
                announce(
                    "Turn uncertain in midgame. "
                    "F10 confirms yours.",
                    "TURN UNKNOWN"
                )

                time.sleep(.2)
                continue

            elif now-session["start"] > 3.2:
                session["turn"] = "player"

                announce(
                    "No opponent move seen; "
                    "testing player first.",
                    "TURN CHECK"
                )

            else:
                time.sleep(.15)
                continue

        if session["turn"] == "opponent":
            announce(
                "Waiting for the opponent to move.",
                "WAITING"
            )

            time.sleep(.18)
            continue

        path = best_move(current)

        if path is None:
            announce(
                "No legal moves. Paused.",
                "STOPPED"
            )

            enabled.clear()
            continue

        boxes = []

        for i in (path[0], path[-1]):
            x, y = center(i, mon, loc)

            boxes.append((
                x,
                y,
                round(PITCH*loc[2]*.76)
            ))

        highlights.put(boxes)

        announce(
            "Playing "+label(path),
            "PLAYING"
        )

        try:
            clicked = play_move(path)
        except Exception as err:
            clicked = False

            announce(
                "Click error: "+str(err),
                "ERROR"
            )

        highlights.put([])

        if not clicked:
            enabled.clear()
            session = None
            continue

        expected = moved(
            current,
            path
        )

        announce(
            "Clicks sent. Checking the board.",
            "VERIFYING"
        )

        result, answered = confirm(expected)

        if result is None:
            announce(
                "Move not confirmed. Paused.",
                "ERROR"
            )

            enabled.clear()
            session = None
            continue

        session = {
            "board": result,
            "turn": (
                "player" if answered
                else "opponent"
            ),
            "start": time.monotonic()
        }

        announce(
            "Opponent already replied."
            if answered
            else "Move confirmed.",
            "YOUR TURN"
            if answered
            else "WAITING"
        )


def toggle():
    global session

    if enabled.is_set():
        enabled.clear()
        highlights.put([])
        session = None

        log(
            "Paused. Press Ctrl+H to resume.",
            "PAUSED"
        )

    else:
        session = None
        first_override.clear()
        enabled.set()

        log(
            "Bot on. Looking for the board...",
            "ON"
        )


class Borders:
    def __init__(self, root):
        self.windows = []

        for _ in range(8):
            w = tk.Toplevel(root)

            w.overrideredirect(True)
            w.configure(bg="#00fb6e")
            w.withdraw()
            w.update_idletasks()

            hwnd = (
                user32.GetParent(w.winfo_id())
                or w.winfo_id()
            )

            flags = user32.GetWindowLongW(
                hwnd,
                -20
            )

            user32.SetWindowLongW(
                hwnd,
                -20,
                flags
                | 0x20
                | 0x80
                | 0x08000000
            )

            self.windows.append(w)

    def show(self, boxes):
        rects = []

        for x, y, size in boxes[:2]:
            a = x-size//2
            b = y-size//2
            t = 4

            rects.extend((
                (a, b, size, t),
                (a, b+size-t, size, t),
                (a, b, t, size),
                (a+size-t, b, t, size)
            ))

        for i, w in enumerate(self.windows):
            if i < len(rects):
                x, y, bw, bh = rects[i]

                w.geometry(
                    f"{bw}x{bh}{x:+}{y:+}"
                )

                w.deiconify()
                w.attributes("-topmost", True)

            else:
                w.withdraw()


def live():
    root = tk.Tk()

    root.title("Black Flag Checkers Bot")
    root.geometry("475x350+20+80")
    root.configure(bg="#111820")
    root.attributes("-topmost", True)

    tk.Label(
        root,
        text="BLACK FLAG CHECKERS | CPU AI",
        bg="#111820",
        fg="white",
        font=("Segoe UI", 12, "bold")
    ).pack(
        anchor="w",
        padx=12,
        pady=(12, 4)
    )

    heading = tk.Label(
        root,
        text="PAUSED",
        bg="#111820",
        fg="#73f4ac",
        font=("Segoe UI", 11, "bold")
    )

    heading.pack(
        anchor="w",
        padx=12
    )

    detail = tk.StringVar(
        value=(
            "Ctrl+H starts/stops | "
            "F8 scans and saves a screenshot | "
            "F10 your turn"
        )
    )

    tk.Label(
        root,
        textvariable=detail,
        bg="#111820",
        fg="#ced8e3",
        wraplength=440,
        justify="left"
    ).pack(
        anchor="w",
        padx=12,
        pady=8
    )

    history = tk.Text(
        root,
        bg="#08121b",
        fg="#cbdbe8",
        font=("Consolas", 9),
        state="disabled",
        wrap="word",
        height=13
    )

    history.pack(
        fill="both",
        expand=True,
        padx=12,
        pady=(0, 12)
    )

    border = Borders(root)

    keyboard.add_hotkey(
        "ctrl+h",
        toggle
    )

    keyboard.add_hotkey(
        "f8",
        scan_now.set
    )

    keyboard.add_hotkey(
        "f10",
        first_override.set
    )

    keyboard.add_hotkey(
        "esc",
        running.set
    )

    threading.Thread(
        target=worker,
        daemon=True
    ).start()

    def pump():
        latest = None

        while not highlights.empty():
            latest = highlights.get_nowait()

        if latest is not None:
            border.show(latest)

        while not messages.empty():
            phase, text = messages.get_nowait()

            heading.configure(text=phase)
            detail.set(text)

            history.configure(state="normal")

            history.insert(
                "end",
                time.strftime("%H:%M:%S")
                + f" {phase}: {text}\n"
            )

            history.see("end")
            history.configure(state="disabled")

        if running.is_set():
            root.destroy()
        else:
            root.after(100, pump)

    root.protocol(
        "WM_DELETE_WINDOW",
        running.set
    )

    root.after(100, pump)
    root.mainloop()

    keyboard.unhook_all_hotkeys()


def demo():
    root = tk.Tk()

    root.title("Offline Checkers AI")
    root.configure(bg="#111820")

    title = tk.StringVar(
        value="Offline CPU AI test"
    )

    tk.Label(
        root,
        textvariable=title,
        bg="#111820",
        fg="#80f0b0",
        font=("Segoe UI", 12)
    ).pack(pady=10)

    board = [start_position()]
    side = [1]
    enabled_demo = [False]
    token = [0]

    cv = tk.Canvas(
        root,
        width=544,
        height=544,
        highlightthickness=0
    )

    cv.pack(padx=10)

    def draw(path=None):
        cv.delete("all")

        for r in range(8):
            for c in range(8):
                x = c*68
                y = r*68

                cv.create_rectangle(
                    x,
                    y,
                    x+68,
                    y+68,
                    fill=(
                        "#e5bd7e"
                        if (r+c) % 2
                        else "#a46639"
                    ),
                    outline=""
                )

                p = board[0][8*r+c]

                if p:
                    cv.create_oval(
                        x+10,
                        y+10,
                        x+58,
                        y+58,
                        fill=(
                            "#e1e5ec"
                            if p < 0
                            else "#26343b"
                        ),
                        outline="#14232c",
                        width=2
                    )

                    if abs(p) == 2:
                        cv.create_text(
                            x+34,
                            y+34,
                            text="K",
                            fill="#f3c04b",
                            font=(
                                "Segoe UI",
                                17,
                                "bold"
                            )
                        )

        if path:
            for i in (path[0], path[-1]):
                r, c = divmod(i, 8)

                cv.create_rectangle(
                    c*68+3,
                    r*68+3,
                    c*68+65,
                    r*68+65,
                    outline="#00ff66",
                    width=4
                )

    def step(t):
        if (
            not enabled_demo[0]
            or t != token[0]
        ):
            return

        path = best_move(
            board[0],
            side[0],
            .2
        )

        if path is None:
            title.set("Match over")
            enabled_demo[0] = False
            return

        title.set(
            (
                "Dark"
                if side[0] > 0
                else "Light"
            )
            + ": "
            + label(path)
        )

        draw(path)

        def commit():
            if (
                not enabled_demo[0]
                or t != token[0]
            ):
                return

            board[0] = moved(
                board[0],
                path
            )

            side[0] *= -1
            draw()

            root.after(
                240,
                lambda: step(t)
            )

        root.after(
            550,
            commit
        )

    def start():
        if not enabled_demo[0]:
            enabled_demo[0] = True
            token[0] += 1

            root.after(
                10,
                lambda: step(token[0])
            )

    def pause():
        enabled_demo[0] = False
        token[0] += 1
        draw()

    def reset():
        pause()

        board[0] = start_position()
        side[0] = 1
        title.set("Ready")
        draw()

    buttons = tk.Frame(
        root,
        bg="#111820"
    )

    buttons.pack(pady=10)

    for name, action in (
        ("Start", start),
        ("Pause", pause),
        ("Reset", reset)
    ):
        tk.Button(
            buttons,
            text=name,
            command=action,
            width=12
        ).pack(
            side="left",
            padx=5
        )

    draw()
    root.mainloop()


if __name__ == "__main__":
    if "--demo" in sys.argv:
        demo()
    else:
        if os.name != "nt":
            raise SystemExit(
                "Live mode needs Windows"
            )

        live()
