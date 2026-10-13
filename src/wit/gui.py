"""The window (WIT.exe without arguments). Same engine as the command line.

Built with ttkbootstrap (themed tkinter, pinned to 1.10.1). Layout:

  Period     years and months, each multi-select: every chosen year x every chosen month
             (future months are left out)
  Outputs    Balance / Performance / Collateral switches
  Deals      all deals, or a selection (search filters; selection kept while searching).
             The deal list's filter (e.g. active deals only) is applied in the background.
  Actions    Check reports (which PDFs would be read) | Run | Stop, progress bar, log
Output folders are fixed in config/settings.yaml and not shown.

The engine runs in a background thread; it only talks to the window through a queue, so the
window stays responsive.
"""
import datetime as dt
import queue
import threading
import tkinter as tk
from tkinter import messagebox

import ttkbootstrap as tb

from .config import OUTPUT_NAMES, load_settings
from .run import OUTPUTS, run
from .sources import active_deals, plan

MONTH_NAMES = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

THEME = "flatly"


class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.busy = False
        self.stop_flag = False
        self.deals, self.shown, self.picked = [], [], set()
        try:
            self.settings = load_settings()
        except Exception as e:                       # noqa: BLE001  show any config problem
            messagebox.showerror("WIT", f"config/settings.yaml could not be read:\n{e}")
            raise SystemExit(1)
        self._build()
        self._load_deals()
        root.after(100, self._poll)

    # ---- layout ------------------------------------------------------------------------------
    def _build(self):
        r = self.root
        head = tb.Frame(r)
        head.pack(fill="x", padx=12, pady=(10, 0))
        tb.Label(head, text="WIT", font=("Segoe UI", 18, "bold"), bootstyle="primary").pack(side="left")
        tb.Label(head, text="  trustee reports → Balance · Performance · Collateral",
                 font=("Segoe UI", 11), bootstyle="secondary").pack(side="left", pady=(6, 0))

        self._period()
        self._outputs()
        self._deals_box()
        self._actions()

    def _period(self):
        f = tb.Labelframe(self.root, text=" Period ", padding=8)
        f.pack(fill="x", padx=10, pady=6)
        today = dt.date.today()
        last = today.replace(day=1) - dt.timedelta(days=1)            # last month: selected at start
        self.year_vars = {y: tk.BooleanVar(value=y == last.year) for y in range(today.year - 5, today.year + 1)}
        self.month_vars = {m: tk.BooleanVar(value=m == last.month) for m in range(1, 13)}
        for row, (label, items) in enumerate((
                ("Years", [(str(y), v) for y, v in self.year_vars.items()]),
                ("Months", [(MONTH_NAMES[m - 1], v) for m, v in self.month_vars.items()]))):
            tb.Label(f, text=label, width=8).grid(row=row, column=0, sticky="w", pady=3)
            line = tb.Frame(f)
            line.grid(row=row, column=1, sticky="w", pady=3)
            for text, var in items:
                tb.Checkbutton(line, text=text, variable=var, bootstyle="primary-outline-toolbutton", width=5,
                               command=self._update_period).pack(side="left", padx=2)
            group = self.year_vars if label == "Years" else self.month_vars
            tb.Button(line, text="All", bootstyle="link",
                      command=lambda g=group: self._set_all(g, True)).pack(side="left", padx=(8, 0))
            tb.Button(line, text="None", bootstyle="link",
                      command=lambda g=group: self._set_all(g, False)).pack(side="left")
            if label == "Years":
                self.period_count = tb.Label(line, text="", bootstyle="info")
                self.period_count.pack(side="left", padx=(16, 0))
        self._update_period()

    def _set_all(self, group, value):
        for v in group.values():
            v.set(value)
        self._update_period()

    def _selected_months(self):
        """Every chosen year x every chosen month, up to the current month."""
        today = dt.date.today()
        return [(y, m) for y, yv in self.year_vars.items() if yv.get()
                for m, mv in self.month_vars.items() if mv.get() and (y, m) <= (today.year, today.month)]

    def _update_period(self):
        n = len(self._selected_months())
        self.period_count.configure(text=f"{n} month{'s' if n != 1 else ''}")

    def _outputs(self):
        f = tb.Labelframe(self.root, text=" Outputs ", padding=8)
        f.pack(fill="x", padx=10, pady=6)
        self.out_vars = {o: tk.BooleanVar(value=True) for o in OUTPUTS}
        for o in OUTPUTS:
            tb.Checkbutton(f, text=OUTPUT_NAMES[o], variable=self.out_vars[o],
                           bootstyle="success-round-toggle").pack(side="left", padx=10)

    def _deals_box(self):
        f = tb.Labelframe(self.root, text=" Deals ", padding=8)
        f.pack(fill="both", expand=True, padx=10, pady=6)
        bar = tb.Frame(f)
        bar.pack(fill="x")
        self.all_deals = tk.BooleanVar(value=True)
        tb.Checkbutton(bar, text="All deals", variable=self.all_deals, bootstyle="primary-round-toggle",
                       command=self._toggle_all).pack(side="left")
        tb.Label(bar, text="Search").pack(side="left", padx=(20, 4))
        self.search = tk.StringVar()
        self.search.trace_add("write", lambda *_: self._fill_list())
        self.search_entry = tb.Entry(bar, textvariable=self.search, width=32)
        self.search_entry.pack(side="left")
        self.b_sel = tb.Button(bar, text="Select shown", bootstyle="secondary-outline", command=self._select_shown)
        self.b_clr = tb.Button(bar, text="Clear", bootstyle="secondary-outline", command=self._clear)
        self.b_sel.pack(side="left", padx=(10, 4))
        self.b_clr.pack(side="left")
        self.count = tb.Label(bar, text="", bootstyle="info")
        self.count.pack(side="right")
        box = tb.Frame(f)
        box.pack(fill="both", expand=True, pady=(8, 0))
        c = tb.Style().colors
        self.lst = tk.Listbox(box, selectmode="extended", height=9, exportselection=False, relief="flat",
                              highlightthickness=1, highlightbackground=c.border, bg=c.inputbg, fg=c.inputfg,
                              selectbackground=c.primary, selectforeground=c.selectfg, font=("Segoe UI", 10))
        sb = tb.Scrollbar(box, command=self.lst.yview, bootstyle="round")
        self.lst.configure(yscrollcommand=sb.set)
        self.lst.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lst.bind("<<ListboxSelect>>", lambda *_: self._on_select())

    def _actions(self):
        f = tb.Frame(self.root)
        f.pack(fill="x", padx=10, pady=(6, 2))
        self.b_check = tb.Button(f, text="Check reports", bootstyle="primary-outline",
                                 command=lambda: self._start(check=True))
        self.b_run = tb.Button(f, text="Run", bootstyle="success", width=10, command=lambda: self._start(check=False))
        self.b_stop = tb.Button(f, text="Stop", bootstyle="danger-outline", command=self._stop, state="disabled")
        for b in (self.b_check, self.b_run, self.b_stop):
            b.pack(side="left", padx=(0, 8))
        self.status = tb.Label(f, text="", bootstyle="secondary")
        self.status.pack(side="right")
        self.bar = tb.Progressbar(self.root, bootstyle="success-striped", maximum=1, value=0)
        self.bar.pack(fill="x", padx=10, pady=(4, 4))

        box = tb.Frame(self.root)
        box.pack(fill="both", expand=True, padx=10, pady=(2, 10))
        c = tb.Style().colors
        self.log = tk.Text(box, height=10, wrap="none", relief="flat", highlightthickness=1,
                           highlightbackground=c.border, bg=c.inputbg, fg=c.inputfg, font=("Consolas", 9))
        sb = tb.Scrollbar(box, command=self.log.yview, bootstyle="round")
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._toggle_all()

    # ---- deals -------------------------------------------------------------------------------
    def _load_deals(self):
        try:
            self.deals = active_deals(self.settings)
            self._say(f"{len(self.deals)} deals")
        except Exception as e:                       # noqa: BLE001
            self._say(f"deal list could not be read ({self.settings['deal_list']['path']}): {e}")
        self._fill_list()

    def _fill_list(self):
        s = self.search.get().strip().lower()
        self.shown = [d for d in self.deals if s in d["deal"].lower() or s in d["trustee"].lower()]
        state = self.lst.cget("state")
        self.lst.configure(state="normal")           # a disabled listbox ignores changes
        self.lst.delete(0, "end")
        for k, d in enumerate(self.shown):
            self.lst.insert("end", f"  {d['deal']}    ·  {d['trustee']}")
            if d["deal"] in self.picked:
                self.lst.selection_set(k)
        self.lst.configure(state=state)
        self._update_count()

    def _on_select(self):
        sel = set(self.lst.curselection())
        for k, d in enumerate(self.shown):
            (self.picked.add if k in sel else self.picked.discard)(d["deal"])
        self._update_count()

    def _select_shown(self):
        self.picked.update(d["deal"] for d in self.shown)
        self._fill_list()

    def _clear(self):
        self.picked.clear()
        self._fill_list()

    def _toggle_all(self):
        state = "disabled" if self.all_deals.get() else "normal"
        for w in (self.lst, self.search_entry, self.b_sel, self.b_clr):
            w.configure(state=state)
        self._update_count()

    def _update_count(self):
        n = len(self.deals) if self.all_deals.get() else len(self.picked)
        self.count.configure(text=f"{n} deal{'s' if n != 1 else ''} selected")

    def _selected_deals(self):
        if self.all_deals.get():
            return None
        return [d["deal"] for d in self.deals if d["deal"] in self.picked]

    # ---- actions -----------------------------------------------------------------------------
    def _stop(self):
        self.stop_flag = True
        self._say("stopping after the current deal ...")

    def _start(self, check):
        if self.busy:
            return
        months = self._selected_months()
        if not months:
            messagebox.showerror("WIT", "Select at least one year and one month (not in the future).")
            return
        names = self._selected_deals()
        if names == []:
            messagebox.showerror("WIT", "Select at least one deal, or switch on 'All deals'.")
            return
        outputs = [o for o in OUTPUTS if self.out_vars[o].get()]
        if not outputs and not check:
            messagebox.showerror("WIT", "Switch on at least one output.")
            return
        self.busy, self.stop_flag = True, False
        self._buttons(running=True)
        self.bar.configure(value=0, maximum=1)
        threading.Thread(target=self._work, args=(months, names, outputs, check), daemon=True).start()

    def _work(self, months, names, outputs, check):
        try:
            jobs = plan(self.settings, months, names)
            found = sum(1 for j in jobs if j["pdf"])
            self._say(f"{len(months)} month(s) x {len(jobs) // max(len(months), 1)} deal(s): "
                      f"{found} of {len(jobs)} reports found")
            if check:
                for j in jobs:
                    note = f"  ({j['file_note']})" if j["file_note"] else ""
                    self._say(f"  {j['year']}-{j['month']:02d}  {j['deal']}: {j['file_status']}{note}")
            else:
                run(jobs, outputs, self.settings, self._say, stop=lambda: self.stop_flag,
                    progress=lambda n, total: self.q.put(("progress", (n, total))))
                self._say("done")
        except Exception as e:                       # noqa: BLE001
            self._say(f"ERROR: {type(e).__name__}: {e}")
        finally:
            self.q.put(("done", None))

    def _buttons(self, running):
        for b in (self.b_check, self.b_run):
            b.configure(state="disabled" if running else "normal")
        self.b_stop.configure(state="normal" if running else "disabled")
        self.status.configure(text="running ..." if running else "")

    # ---- log and progress (worker -> queue -> window) ----------------------------------------
    def _say(self, text):
        self.q.put(("log", text))

    def _poll(self):
        while not self.q.empty():
            kind, data = self.q.get()
            if kind == "log":
                self.log.insert("end", data + "\n")
                self.log.see("end")
            elif kind == "progress":
                n, total = data
                self.bar.configure(maximum=total, value=n)
                self.status.configure(text=f"{n} / {total}")
            else:
                self.busy = False
                self._buttons(running=False)
        self.root.after(100, self._poll)


def main():
    root = tb.Window(title="WIT - trustee report extraction", themename=THEME, size=(1000, 760),
                     minsize=(820, 600))
    App(root)
    root.mainloop()
