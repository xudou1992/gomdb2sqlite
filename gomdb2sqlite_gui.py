#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gomdb2sqlite GUI -- GOM/Blue 引擎 BDE 表转 RED 引擎 SQLite 的图形界面

依赖:标准库 tkinter(Python 自带)

启动:
    python gomdb2sqlite_gui.py
或双击 run_gui.bat
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import traceback

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText
except ImportError:                       # 精简版 Python 可能没带 tkinter
    print("当前 Python 没有 tkinter, 请改用命令行版: python gomdb2sqlite.py --help")
    sys.exit(1)

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gomdb2sqlite as core          # noqa: E402

TABLES = [("Monster", "Monster.DB  怪物"), ("Magic", "Magic.DB  技能"),
          ("StdItems", "StdItems.DB  物品")]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GOM → RED 数据库转换器  v1.0")
        self.geometry("760x600")
        self.minsize(700, 540)
        self.q: queue.Queue = queue.Queue()
        self.vars = {}
        self.src_var = tk.StringVar()
        self.out_var = tk.StringVar()
        self._build()
        self.after(120, self._poll)

    # ---------- 界面 ----------
    def _build(self):
        pad = {"padx": 10, "pady": 5}

        top = ttk.LabelFrame(self, text=" 输入 ")
        top.pack(fill="x", **pad)

        r1 = ttk.Frame(top); r1.pack(fill="x", padx=8, pady=6)
        ttk.Label(r1, text="源目录").pack(side="left")
        ttk.Entry(r1, textvariable=self.src_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r1, text="浏览…", command=self.pick_src, width=8).pack(side="left")

        self.detect = ttk.Label(top, text="请选择包含 Magic.DB / Monster.DB / StdItems.DB 的目录",
                                foreground="#666")
        self.detect.pack(anchor="w", padx=12, pady=(0, 6))

        r2 = ttk.Frame(top); r2.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Label(r2, text="输出文件").pack(side="left")
        ttk.Entry(r2, textvariable=self.out_var).pack(side="left", fill="x", expand=True, padx=6)
        ttk.Button(r2, text="另存为…", command=self.pick_out, width=8).pack(side="left")

        mid = ttk.LabelFrame(self, text=" 要转换的表 ")
        mid.pack(fill="x", **pad)
        box = ttk.Frame(mid); box.pack(fill="x", padx=8, pady=8)
        for t, label in TABLES:
            v = tk.BooleanVar(value=True)
            self.vars[t] = v
            ttk.Checkbutton(box, text=label, variable=v).pack(side="left", padx=(0, 18))

        run = ttk.Frame(self); run.pack(fill="x", **pad)
        self.btn = ttk.Button(run, text="开始转换", command=self.start)
        self.btn.pack(side="left")
        self.pb = ttk.Progressbar(run, mode="determinate", maximum=3)
        self.pb.pack(side="left", fill="x", expand=True, padx=10)

        logf = ttk.LabelFrame(self, text=" 日志 ")
        logf.pack(fill="both", expand=True, **pad)
        self.log = ScrolledText(logf, height=16, font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=8, pady=8)
        self._say("就绪。选择源目录 → 勾选表 → 开始转换。")
        self._say("")
        self._say("说明：")
        self._say("  · 输出为 SQLite，RED 引擎放在 MirServer\\Mud2\\DB\\REDM2.DB")
        self._say("  · 转换会剔除广告行、----- 分隔行；重名物品追加 (2)(3) 序号")
        self._say("  · 物品名原样保留，表结构 Name 放宽到 TEXT(40)")
        self._say("  · 转完请启动 DBServer.exe 验证，等满 16 秒看有无报错框")

    # ---------- 交互 ----------
    def pick_src(self):
        d = filedialog.askdirectory(title="选择含 Magic.DB / Monster.DB / StdItems.DB 的目录")
        if not d:
            return
        self.src_var.set(d)
        need = ("Magic.DB", "Monster.DB", "StdItems.DB")
        missing = [x for x in need if not os.path.exists(os.path.join(d, x))]
        if missing:
            self.detect.config(text="已选目录，但缺少: " + "、".join(missing), foreground="#b00")
        else:
            self.detect.config(text="已找到 Magic.DB / Monster.DB / StdItems.DB", foreground="#080")
        if not self.out_var.get() or not os.path.dirname(self.out_var.get()):
            self.out_var.set(os.path.join(d, "REDM2.DB"))

    def pick_out(self):
        f = filedialog.asksaveasfilename(
            title="输出 SQLite", defaultextension=".DB",
            initialfile="REDM2.DB", filetypes=[("SQLite", "*.DB"), ("所有文件", "*.*")])
        if f:
            self.out_var.set(f)

    def start(self):
        src = self.src_var.get().strip().strip('"')
        out = self.out_var.get().strip().strip('"')
        if not src or not os.path.isdir(src):
            messagebox.showwarning("提示", "请选择有效的源目录")
            return
        if not out:
            out = os.path.join(src, "REDM2.DB")
            self.out_var.set(out)
        tables = [t for t, v in self.vars.items() if v.get()]
        if not tables:
            messagebox.showwarning("提示", "至少勾选一张表")
            return
        self.btn.config(state="disabled")
        self.pb["value"] = 0
        self.pb["maximum"] = len(tables)
        threading.Thread(target=self._work, args=(src, out, tables), daemon=True).start()

    # ---------- 转换 ----------
    def _work(self, src, out, tables):
        try:
            if os.path.exists(out):
                bak = out + ".bak"
                try:
                    import shutil
                    shutil.copy2(out, bak)
                    self.q.put(("log", "旧库已备份: %s" % os.path.basename(bak)))
                except Exception as e:
                    self.q.put(("log", "备份失败(忽略): %s" % e))
            files = {"Monster": "Monster.DB", "Magic": "Magic.DB", "StdItems": "StdItems.DB"}
            for t in tables:
                p = os.path.join(src, files[t])
                if not os.path.exists(p):
                    self.q.put(("log", "跳过 %s: 文件不存在" % files[t]))
                    self.q.put(("step", 1))
                    continue
                self.q.put(("log", "转换 %s …" % files[t]))
                try:
                    r = core.convert(src, out, t, p)
                    self.q.put(("log", "  %-9s 字段 %2d 记录 %3d 每块 %2d 扫描 %3d 解析 %3d 入库 %3d (剔 %d 重名 %d)"
                                % (r["table"], r["fields"], r["rec"], r["per_block"],
                                   r["scanned"], r["parsed"], r["final"],
                                   r["dropped"], r["renamed"])))
                except Exception as e:
                    self.q.put(("log", "  %s 失败: %s" % (t, e)))
                self.q.put(("step", 1))
            self.q.put(("done", out))
        except Exception:
            self.q.put(("log", traceback.format_exc()))
            self.q.put(("done", None))

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._say(payload)
                elif kind == "step":
                    self.pb["value"] += 1
                elif kind == "done":
                    self.btn.config(state="normal")
                    if payload:
                        self._say("")
                        self._say("完成 → %s" % payload)
                        self._say("放到 MirServer\\Mud2\\DB\\REDM2.DB 后启动 DBServer.exe 验证（等满 16 秒）。")
                        messagebox.showinfo("完成", "转换完成\n\n%s" % payload)
                    else:
                        messagebox.showerror("失败", "转换过程中出错，详见日志")
        except queue.Empty:
            pass
        self.after(120, self._poll)

    def _say(self, s):
        self.log.insert("end", s + "\n")
        self.log.see("end")


if __name__ == "__main__":
    App().mainloop()
