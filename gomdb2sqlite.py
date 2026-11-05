#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
gomdb2sqlite -- 把 GOM / Blue 系引擎的 BDE 表(Magic.DB / Monster.DB / StdItems.DB)
转成 SQLite,供 RED 系引擎(DBServer / M2Server)读取。

不依赖任何模板库:目标库不存在时自己建表。

用法:
    python gomdb2sqlite.py --src <含三个.DB的目录> [--out REDM2.DB] [--table Monster,Magic,StdItems]
    python gomdb2sqlite.py --src D:\\MirServer\\Mud2\\DB --out D:\\out\\REDM2.DB

依赖:Python 3.8+,标准库即可。
"""
from __future__ import annotations

import argparse
import os
import re
import sqlite3
import sys

BLOCK = 2048          # 数据块大小
HEAD = 0x800          # 记录区起始
REC_HEAD = 6          # 每条记录的头(记录号等)
DESC_OFF = 0x78       # 字段描述表偏移
NAME_OFF = 0x204      # 字段名表偏移

# BDE 字段类型 -> 字节数;Alpha 的字节数写在描述表第二个字节里
TYPE_SIZE = {0x01: None, 0x02: 4, 0x03: 2, 0x04: 4, 0x05: 8,
             0x06: 8, 0x09: 1, 0x0B: 10, 0x0C: 0, 0x0D: 0}

SCHEMA = {
    "Monster": '''CREATE TABLE IF NOT EXISTS "Monster" (
        "Name" TEXT(40),"Race" INTEGER,"RaceImg" INTEGER,"Appr" INTEGER,"Lvl" INTEGER,
        "Undead" INTEGER,"CoolEye" INTEGER,"HP" INTEGER,"MP" INTEGER,"AC" INTEGER,
        "MAC" INTEGER,"DC" INTEGER,"DCMAX" INTEGER,"MC" INTEGER,"SC" INTEGER,
        "SPEED" INTEGER,"HIT" INTEGER,"WALK_SPD" INTEGER,"WALKSTEP" INTEGER,
        "WALKWAIT" INTEGER,"ATTACK_SPD" INTEGER,"Exp" INTEGER,"ExploreItem" INTEGER,
        "InLevel" INTEGER,"IPExp" INTEGER)''',
    "Magic": '''CREATE TABLE IF NOT EXISTS "Magic" (
        "MagID" INTEGER,"MagName" TEXT(12),"EffectType" INTEGER,"Effect" INTEGER,
        "Spell" INTEGER,"Power" INTEGER,"MaxPower" INTEGER,"DefSpell" INTEGER,
        "DefPower" INTEGER,"DefMaxPower" INTEGER,"Job" INTEGER,
        %s, "MaxTrainLv" INTEGER,"Delay" INTEGER,"Descr" TEXT(12))''' %
        ",".join('"NeedL%d" INTEGER,"L%dTrain" INTEGER' % (i, i) for i in range(1, 16)),
    "StdItems": '''CREATE TABLE IF NOT EXISTS "StdItems" (
        "Idx" INTEGER,"Name" TEXT(40),"Stdmode" INTEGER,"Shape" INTEGER,
        "Weight" INTEGER,"Anicount" INTEGER,"Source" INTEGER,"Reserved" INTEGER,
        "Looks" INTEGER,"DuraMax" INTEGER,"Ac" INTEGER,"Ac2" INTEGER,"Mac" INTEGER,
        "Mac2" INTEGER,"Dc" INTEGER,"Dc2" INTEGER,"Mc" INTEGER,"Mc2" INTEGER,
        "Sc" INTEGER,"Sc2" INTEGER,"Need" INTEGER,"NeedLevel" INTEGER,"Price" INTEGER,
        "Stock" INTEGER,"UniqueItem" INTEGER,"Overlap" INTEGER,"ItemType" INTEGER,
        "ItemSet" INTEGER,"Smite" INTEGER,"DropRate" INTEGER,"IgnDef" INTEGER,
        "DamAdd" INTEGER,"DamReb" INTEGER,"DcRedu" INTEGER,"McRedu" INTEGER,
        "ExpAdd" INTEGER,"Bind" INTEGER,"Shine" INTEGER,"HP" INTEGER,"MP" INTEGER,
        "Reference" TEXT(60),"Light" INTEGER,"Color" INTEGER)''',
}

NAME_COL = {"Monster": "Name", "Magic": "MagName", "StdItems": "Name"}
KEY_COL = {"Monster": None, "Magic": "MagID", "StdItems": "Idx"}


def read_schema(d: bytes):
    """返回 [(type, width)]"""
    nf = d[0x21]
    out = []
    for i in range(nf):
        t = d[DESC_OFF + 2 * i]
        sz = d[DESC_OFF + 2 * i + 1]
        if t == 0:
            break
        out.append((t, sz))
    return out


def read_names(d: bytes, n: int):
    names, cur, i = [], bytearray(), NAME_OFF
    while i < HEAD and len(names) < n:
        c = d[i]
        if c == 0:
            if cur:
                try:
                    names.append(cur.decode("ascii"))
                except Exception:
                    names.append("F%d" % len(names))
                cur = bytearray()
        elif 32 <= c < 127:
            cur.append(c)
        i += 1
    while len(names) < n:
        names.append("F%d" % len(names))
    return names


def width(descs):
    return sum(TYPE_SIZE[t] if TYPE_SIZE.get(t) is not None else sz for t, sz in descs)


def rec_base(i: int, rec: int):
    per = max(1, BLOCK // rec)
    return HEAD + (i // per) * BLOCK + (i % per) * rec


def find_rec_len(d: bytes, descs):
    """记录长 = 6 + 字段区宽度;用名字连续性校验,失败则搜索"""
    cand = REC_HEAD + width(descs)
    names = read_names(d, len(descs))
    npos = [i for i, n in enumerate(names) if n.upper() in ("NAME", "MAGNAME")]
    nfield = npos[0] if npos else 0

    def score(rec):
        per = max(1, BLOCK // rec)
        ok = 0
        for i in range(min(20, per * 4)):
            p = rec_base(i, rec) + REC_HEAD
            for k in range(nfield):
                p += TYPE_SIZE[descs[k][0]] if TYPE_SIZE.get(descs[k][0]) is not None else descs[k][1]
            raw = d[p:p + 40].split(b"\x00")[0]
            if len(raw) < 2:
                break
            try:
                s = raw.decode("gbk")
            except Exception:
                break
            if not s.strip():
                break
            ok += 1
        return ok

    if score(cand) >= 18:
        return cand
    best, brec = -1, cand
    for rec in range(REC_HEAD + 8, 700):
        g = score(rec)
        if g > best:
            best, brec = g, rec
    return brec


def decode(d: bytes, i: int, rec: int, descs, names):
    base = rec_base(i, rec)
    if base + rec > len(d):
        return None
    p = base + REC_HEAD
    out = {}
    for k, (t, sz) in enumerate(descs):
        w = TYPE_SIZE[t] if TYPE_SIZE.get(t) is not None else sz
        if p + w > base + rec:
            break
        raw = d[p:p + w]
        if t == 0x01:                      # Alpha: GBK 字符串
            try:
                v = raw.split(b"\x00")[0].decode("gbk").strip()
            except Exception:
                v = ""
        else:                              # 数值:首字节 0x80 为有效标志
            v = int.from_bytes(raw[1:], "big") if (w and raw[0] == 0x80) else \
                (int.from_bytes(raw, "big") if w else 0)
        out[names[k] if k < len(names) else "F%d" % k] = v
        p += w
    return out


def cut_bytes(s: str, limit: int) -> str:
    """按 GBK 字节截断,不切断双字节字符"""
    b = s.encode("gbk", "ignore")
    if len(b) <= limit:
        return s
    out = b[:limit]
    while out:
        try:
            return out.decode("gbk")
        except Exception:
            out = out[:-1]
    return ""


def clean(con, table):
    """RED 的三条硬要求 + 清垃圾行"""
    namecol = NAME_COL[table]
    cols = [(r[1], r[2]) for r in con.execute("PRAGMA table_info([%s])" % table)]
    rows = con.execute("SELECT rowid, [%s] FROM [%s] ORDER BY rowid" % (namecol, table)).fetchall()
    seen, drop, renamed = set(), [], 0
    for rid, nm in rows:
        s = (nm or "").strip()
        if not s:
            drop.append(rid); continue
        low = s.lower()
        if re.search(r"www\.|\.com|\.cn|\.net|qq群|淘宝|论坛|bbs|微信|公众号", low):
            drop.append(rid); continue
        if set(s) <= set("-_. "):            # -------- 分隔行
            drop.append(rid); continue
        nn = s                              # 名字原样保留, 表结构已放宽到 TEXT(40)
        if nn in seen:                      # 重名追加序号, 不改名本身
            for k in range(2, 100):
                cand = "%s(%d)" % (s, k)
                if cand not in seen:
                    nn = cand; break
        if nn in seen:
            drop.append(rid); continue
        seen.add(nn)
        if nn != s:
            con.execute("UPDATE [%s] SET [%s]=? WHERE rowid=?" % (table, namecol), (nn, rid))
            renamed += 1
    if drop:
        con.executemany("DELETE FROM [%s] WHERE rowid=?" % table, [(x,) for x in drop])
    # NULL -> 默认值(引擎不解 NULL)
    for n, typ in cols:
        dflt = "''" if ("TEXT" in (typ or "").upper() or "CHAR" in (typ or "").upper()) else "0"
        con.execute("UPDATE [%s] SET [%s]=%s WHERE [%s] IS NULL" % (table, n, dflt, n))
    # 键重编连续(引擎按数组下标访问)
    key = KEY_COL[table]
    if key:
        rs = con.execute("SELECT rowid FROM [%s] ORDER BY [%s], rowid" % (table, key)).fetchall()
        base = 1 if table == "Magic" else 0
        for i, (rid,) in enumerate(rs):
            con.execute("UPDATE [%s] SET [%s]=? WHERE rowid=?" % (table, key), (i + base, rid))
    con.commit()
    return {"dropped": len(drop), "renamed": renamed}


def convert(src: str, out_db: str, table: str, src_file: str) -> dict:
    d = open(src_file, "rb").read()
    descs = read_schema(d)
    if not descs:
        raise RuntimeError("%s: 头部没有字段描述, 不是 BDE 表?" % os.path.basename(src_file))
    names = read_names(d, len(descs))
    rec = find_rec_len(d, descs)
    per = max(1, BLOCK // rec)
    total = ((len(d) - HEAD) // BLOCK) * per

    con = sqlite3.connect(out_db)
    con.execute(SCHEMA[table])
    cols = [r[1] for r in con.execute("PRAGMA table_info([%s])" % table)]
    colmap = {c.upper(): c for c in cols}
    keep = [(k, n) for k, n in enumerate(names) if n.upper() in colmap]
    con.execute("DELETE FROM [%s]" % table)
    ins = 0
    for i in range(total):
        v = decode(d, i, rec, descs, names)
        if not v:
            continue
        row = {colmap[names[k].upper()]: v[names[k]] for k, _ in keep if names[k] in v}
        nk = NAME_COL[table]
        if nk in row and not row[nk]:
            continue
        if not row:
            continue
        ks = list(row.keys())
        con.execute("INSERT INTO [%s](%s) VALUES(%s)" % (
            table, ",".join("[%s]" % x for x in ks), ",".join("?" * len(ks))),
            [row[x] for x in ks])
        ins += 1
    con.commit()
    stat = clean(con, table)
    final = con.execute("SELECT count(*) FROM [%s]" % table).fetchone()[0]
    con.close()
    return {"table": table, "fields": len(descs), "rec": rec, "per_block": per,
            "scanned": total, "parsed": ins, "final": final,
            "dropped": stat["dropped"], "renamed": stat["renamed"]}


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="gomdb2sqlite",
        description="GOM/Blue 引擎 BDE 表(Magic.DB/Monster.DB/StdItems.DB)转 RED 引擎用的 SQLite")
    ap.add_argument("--src", required=True, help="三个 .DB 所在目录")
    ap.add_argument("--out", default="REDM2.DB", help="输出 SQLite(默认 REDM2.DB)")
    ap.add_argument("--table", default="Monster,Magic,StdItems",
                    help="要转的表, 逗号分隔")
    ap.add_argument("--report", default="", help="报告写到指定文件")
    args = ap.parse_args(argv)

    files = {"Monster": "Monster.DB", "Magic": "Magic.DB", "StdItems": "StdItems.DB"}
    lines = []
    ok = 0
    # 建表顺序必须固定为 StdItems -> Magic -> Monster。
    # RED 的 DBServer 按 sqlite_master 的顺序遍历表，并且假定第 1 张是物品、第 2 张是技能、第 3 张是怪物；
    # 顺序不对不会报字段错，而是直接弹「物品数据库发生错误！」。
    con = sqlite3.connect(args.out)
    for t in ("StdItems", "Magic", "Monster"):
        con.execute(SCHEMA[t])
    con.commit()
    con.close()
    for t in [x.strip() for x in args.table.split(",") if x.strip()]:
        if t not in files:
            lines.append("跳过未知表 %s" % t); continue
        p = os.path.join(args.src, files[t])
        if not os.path.exists(p):
            lines.append("跳过 %s: 文件不存在" % files[t]); continue
        try:
            r = convert(args.src, args.out, t, p)
            lines.append(
                "%-9s 字段 %2d 记录 %3d 每块 %2d 扫描 %3d 解析 %3d 入库 %3d (剔 %d 改名 %d)"
                % (r["table"], r["fields"], r["rec"], r["per_block"],
                   r["scanned"], r["parsed"], r["final"], r["dropped"], r["renamed"]))
            ok += 1
        except Exception as e:
            lines.append("%-9s 失败: %s" % (t, e))
    lines.append("输出: %s" % os.path.abspath(args.out))
    text = "\n".join(lines)
    print(text)
    if args.report:
        with open(args.report, "w", encoding="utf-8-sig") as f:
            f.write(text + "\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
